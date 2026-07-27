import os
import random
import eventlet

eventlet.monkey_patch()

from flask import Flask, render_template
from flask_socketio import SocketIO, emit

app = Flask(__name__, template_folder='.')
app.config['SECRET_KEY'] = 'bingo_house_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

@app.route('/')
def index():
    return render_template('index.html')

# የጨዋታው መዋቅር (Game Settings)
CARD_PRICE = 10.0
COMMISSION_RATE = 0.20 # 20% የቦት ኮሚሽን

# 88 ካርቴላዎች በስክሪን ላይ የሚታዩት (1-88 Cards Board)
# እያንዳንዱ ካርቴላ የራሱ 5x5 Grid አለው
cards_database = {}

def generate_standard_bingo_grid():
    """ትክክለኛ የቢንጎ ካርቴላ ቁጥሮችን (B:1-15, I:16-30, N:31-45, G:46-60, O:61-75) ይፈጥራል"""
    b = random.sample(range(1, 16), 5)
    i = random.sample(range(16, 31), 5)
    n = random.sample(range(31, 46), 5)
    g = random.sample(range(46, 61), 5)
    o = random.sample(range(61, 76), 5)
    
    n[2] = 0 # የመካከለኛው FREE SPACE (★)

    grid = []
    for r in range(5):
        grid.append([b[r], i[r], n[r], g[r], o[r]])
    return grid

# 88ቱን ካርቴላዎች አስቀድሞ ማዘጋጀት
for card_num in range(1, 89):
    cards_database[str(card_num)] = generate_standard_bingo_grid()

game_state = {
    "status": "WAITING", # WAITING, COUNTDOWN, PLAYING, ENDED
    "countdown": 15,
    "called_numbers": [],
    "selected_cards": {}, # card_num -> player_id
    "players_cards": {},  # player_id -> list of cards
    "derash": 0,
    "total_cards_sold": 0
}

def reset_game():
    global game_state
    game_state["status"] = "WAITING"
    game_state["countdown"] = 15
    game_state["called_numbers"] = []
    game_state["selected_cards"] = {}
    game_state["players_cards"] = {}
    game_state["derash"] = 0
    game_state["total_cards_sold"] = 0

def check_bingo_winner(grid, called_list):
    """ካርቴላው መስመር መሙላቱን መፈተሻ"""
    def is_m(val):
        return val == 0 or val in called_list

    # Rows
    for row in grid:
        if all(is_m(n) for n in row): return True
    # Columns
    for col in range(5):
        if all(is_m(grid[row][col]) for row in range(5)): return True
    # Diagonals
    d1 = [grid[i][i] for i in range(5)]
    d2 = [grid[i][4-i] for i in range(5)]
    if all(is_m(n) for n in d1) or all(is_m(n) for n in d2): return True

    return False

def game_loop():
    global game_state

    # 1. የመጀመሪያው ተጫዋች ካርቴላ እንደያዘ የ15 ሰከንድ ቆጠራ መጀመር
    game_state["status"] = "COUNTDOWN"
    for i in range(15, 0, -1):
        if game_state["status"] != "COUNTDOWN":
            break
        game_state["countdown"] = i
        socketio.emit("update_state", game_state)
        eventlet.sleep(1)

    # ቆጠራው ሲያልቅ ካርቴላ የያዘ ሰው ከሌለ ጨዋታውን መመለስ
    if len(game_state["selected_cards"]) == 0:
        reset_game()
        socketio.emit("update_state", game_state)
        return

    # 2. የጨዋታው መጀመር (Calling Numbers Phase 1-75)
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

        # አሸናፊ መኖሩን መፈተሽ
        for pid, cards in game_state["players_cards"].items():
            for card in cards:
                if check_bingo_winner(card["grid"], game_state["called_numbers"]):
                    winners.append({
                        "player": pid,
                        "card_id": card["id"],
                        "grid": card["grid"]
                    })

        # አሸናፊ ከተገኘ ጨዋታውን ማቆም
        if winners:
            game_state["status"] = "ENDED"
            prize_per_winner = game_state["derash"] / len(winners) if winners else 0
            
            socketio.emit("game_over", {
                "winners": winners,
                "prize": round(prize_per_winner, 2),
                "derash": game_state["derash"]
            })
            print(f"🏆 አሸናፊ ተገኝቷል! ደራሽ፦ {game_state['derash']} ETB")
            break

        eventlet.sleep(3) # በየ 3 ሰከንዱ አዲስ ጥሪ ማድረግ

    # 3. ከአሸናፊ ማስታወቂያ በኋላ (10 ሰከንድ ቆይቶ) አዲስ ዙር መጀመር
    eventlet.sleep(10)
    reset_game()
    socketio.emit("update_state", game_state)

@socketio.on('select_card')
def handle_select_card(data):
    """ተጫዋቹ ከ 1-88 ውስጥ ካርቴላ ሲመርጥ የሚሰራ"""
    global game_state
    
    pid = data.get("player_id")
    card_num = str(data.get("card_num"))

    # ጨዋታው ገና ከሆነ ወይም በቆጠራ ላይ ከሆነ ብቻ ነው መያዝ የሚቻለው
    if game_state["status"] in ["WAITING", "COUNTDOWN"]:
        # ካርቴላው ቀደም ብሎ ያልተያዘ ከሆነ
        if card_num not in game_state["selected_cards"]:
            game_state["selected_cards"][card_num] = pid
            
            card_data = {
                "id": card_num,
                "grid": cards_database[card_num]
            }

            if pid not in game_state["players_cards"]:
                game_state["players_cards"][pid] = []
            
            game_state["players_cards"][pid].append(card_data)
            game_state["total_cards_sold"] += 1

            # ደራሽ ስሌት (የካርቴላዎች ድምር ብር - 20% ኮሚሽን)
            total_collected = game_state["total_cards_sold"] * CARD_PRICE
            game_state["derash"] = round(total_collected * (1 - COMMISSION_RATE), 2)

            socketio.emit("update_state", game_state)

            # የመጀመሪያው ካርቴላ ሲያዝ ቆጠራውን ማስጀመር
            if game_state["status"] == "WAITING":
                socketio.start_background_task(game_loop)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)
