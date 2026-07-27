import os
import random
import eventlet

eventlet.monkey_patch()

from flask import Flask, render_template
from flask_socketio import SocketIO, emit

app = Flask(__name__, template_folder='.')
app.config['SECRET_KEY'] = 'bingo_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

@app.route('/')
def index():
    return render_template('index.html')

# የጨዋታው ግዛቶች (Game States)
CARD_PRICE = 10
commission_rate = 0.20 # 20% ኮሚሽን

game_state = {
    "status": "WAITING", # WAITING, COUNTDOWN, PLAYING, ENDED
    "countdown": 15,
    "called_numbers": [],
    "players_cards": {}, # player_id -> list of cards
    "derash": 0,
    "total_cards_sold": 0
}

def reset_game():
    global game_state
    game_state["status"] = "WAITING"
    game_state["countdown"] = 15
    game_state["called_numbers"] = []
    game_state["players_cards"] = {}
    game_state["derash"] = 0
    game_state["total_cards_sold"] = 0

def check_winner(card_grid, called_list):
    def is_m(val):
        return val == 0 or val in called_list

    # Rows
    for row in card_grid:
        if all(is_m(n) for n in row): return True
    # Cols
    for col in range(5):
        if all(is_m(card_grid[row][col]) for row in range(5)): return True
    # Diagonals
    d1 = [card_grid[i][i] for i in range(5)]
    d2 = [card_grid[i][4-i] for i in range(5)]
    if all(is_m(n) for n in d1) or all(is_m(n) for n in d2): return True

    return False

def game_loop():
    global game_state
    
    # 1. የ 15 ሰከንድ ቆጠራ (Countdown Phase)
    game_state["status"] = "COUNTDOWN"
    for i in range(15, 0, -1):
        game_state["countdown"] = i
        socketio.emit("update_state", game_state)
        eventlet.sleep(1)

    # 2. የጨዋታው መጀመር (Calling Numbers Phase)
    game_state["status"] = "PLAYING"
    socketio.emit("update_state", game_state)

    all_balls = list(range(1, 76))
    random.shuffle(all_balls)

    winners = []

    for ball in all_balls:
        if game_state["status"] != "PLAYING":
            break

        game_state["called_numbers"].append(ball)
        socketio.emit("number_called", {
            "ball": ball,
            "called_numbers": game_state["called_numbers"]
        })

        # አሸናፊ ማረጋገጥ
        for pid, cards in game_state["players_cards"].items():
            for card in cards:
                if check_winner(card["grid"], game_state["called_numbers"]):
                    winners.append({"player": pid, "card_id": card["id"], "grid": card["grid"]})

        if winners:
            game_state["status"] = "ENDED"
            prize_per_winner = game_state["derash"] // len(winners) if winners else 0
            
            socketio.emit("game_over", {
                "winners": winners,
                "prize": prize_per_winner,
                "derash": game_state["derash"]
            })
            print("🏆 ጨዋታው ተጠናቋል! አሸናፊዎች ተለይተዋል::")
            break

        eventlet.sleep(3) # በየ 3 ሰከንዱ አዲስ ጥሪ

    # 3. ከአጭር እረፍት በኋላ አዲስ ዙር መጀመር
    eventlet.sleep(10)
    reset_game()
    socketio.emit("update_state", game_state)

@socketio.on('join_game')
def handle_join(data):
    # ናሙና የካርቴላ መግዛት ሂደት
    pid = data.get("player_id", "Player_1")
    if game_state["status"] in ["WAITING", "COUNTDOWN"]:
        card_id = random.randint(100, 999)
        # ናሙና 5x5 ካርቴላ
        new_card = {
            "id": card_id,
            "grid": [
                [3, 21, 45, 52, 68],
                [10, 30, 37, 48, 66],
                [13, 26, 0,  56, 70],
                [14, 24, 35, 46, 73],
                [7,  25, 34, 55, 62]
            ]
        }
        
        if pid not in game_state["players_cards"]:
            game_state["players_cards"][pid] = []
            
        game_state["players_cards"][pid].append(new_card)
        game_state["total_cards_sold"] += 1
        
        # ደራሽ ስሌት (ካርቴላ * ዋጋ - ኮሚሽን)
        total_collected = game_state["total_cards_sold"] * CARD_PRICE
        game_state["derash"] = int(total_collected * (1 - commission_rate))

        socketio.emit("update_state", game_state)

        # ቆጠራው ካልተጀመረ ማስጀመር
        if game_state["status"] == "WAITING":
            socketio.start_background_task(game_loop)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)
