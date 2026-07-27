import os
import time
import random
import eventlet

eventlet.monkey_patch()

from flask import Flask, render_template
from flask_socketio import SocketIO, emit

app = Flask(__name__, template_folder='.')
app.config['SECRET_KEY'] = 'bingo_auto_win_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# የጨዋታው መረጃዎች
STAKE_AMOUNT = 10
BOT_COMMISSION = 2
WINNER_PAYOUT = (STAKE_AMOUNT - BOT_COMMISSION) * 10  # 80 ብር

called_numbers = []
is_game_active = False

# የተጫዋቾች ካርቴላዎች መረጃ (በእውነተኛ ጨዋታ ከ Database የሚመጣ)
players_cards = {
    "Player_1": {
        "cartela_id": "65",
        "grid": [
            [1, 19, 31, 46, 62],
            [5, 22, 32, 53, 63],
            [9, 23, 0,  55, 69],  # 0 ማለት FREE ቦታ ነው
            [11, 28, 42, 57, 70],
            [15, 29, 44, 58, 65]
        ]
    },
    "Player_2": {
        "cartela_id": "80",
        "grid": [
            [4, 17, 32, 49, 61],
            [5, 18, 33, 52, 64],
            [10, 19, 0,  54, 80],
            [11, 21, 42, 56, 71],
            [12, 23, 45, 60, 75]
        ]
    }
}

# ---------------------------------------------------------
# አውቶማቲክ አሸናፊነትን የሚያረጋግጥ Function (Auto Win Validator)
# ---------------------------------------------------------
def check_auto_bingo(grid, called_list):
    # 0 (FREE ቦታ) አውቶማቲክ እንደተጠራ ይቆጠራል
    def is_marked(num):
        return num == 0 or num in called_list

    # 1. አግድም መስመሮችን (Rows) መፈተሽ
    for row in grid:
        if all(is_marked(num) for num in row):
            return True

    # 2. ဒေါንግሊ መስመሮችን (Columns) መፈተሽ
    for col in range(5):
        if all(is_marked(grid[row][col]) for row in range(5)):
            return True

    # 3. ሰያፍ መስመሮችን (Diagonals) መፈተሽ
    diagonal1 = [grid[i][i] for i in range(5)]
    diagonal2 = [grid[i][4 - i] for i in range(5)]
    
    if all(is_marked(num) for num in diagonal1) or all(is_marked(num) for num in diagonal2):
        return True

    return False

# ---------------------------------------------------------
# ቁጥሮችን አውቶማቲክ የሚጠራ እና አሸናፊ የሚያስብል Loop
# ---------------------------------------------------------
def start_calling_numbers():
    global called_numbers, is_game_active
    
    called_numbers = []
    is_game_active = True
    
    all_numbers = list(range(1, 76))
    random.shuffle(all_numbers)

    print("🎲 አውቶማቲክ የቢንጎ ጨዋታ ተጀመረ...")

    for num in all_numbers:
        if not is_game_active:
            break
        
        called_numbers.append(num)
        
        # 1. የተጠራውን ቁጥር ለሁሉም ተጫዋች መላክ
        socketio.emit('number_called', {'number': num})
        print(f"📢 የተጠራ ቁጥር: {num}")

        # 2. አውቶማቲክ አሸናፊ መኖሩን እያንዳንዱ ቁጥር በተጠራ ቁጥር መፈተሽ
        winner_found = False
        for player_id, card_info in players_cards.items():
            if check_auto_bingo(card_info["grid"], called_numbers):
                is_game_active = False
                winner_found = True
                
                # አውቶማቲክ የአሸናፊነት ማስታወቂያ ለሁሉም ተጫዋቾች ማሰራጨት
                socketio.emit('auto_bingo_winner', {
                    'winnerId': player_id,
                    'cartelaId': card_info["cartela_id"],
                    'winningNumber': num,
                    'payout': WINNER_PAYOUT,
                    'message': f"🎉 አውቶማቲክ BINGO! ተጫዋች {player_id} በካርቴላ #{card_info['cartela_id']} በቁጥር {num} አሸንፏል!"
                })
                print(f"🏆 አውቶማቲክ አሸናፊ ተገኝቷል፦ {player_id} (ካርቴላ #{card_info['cartela_id']})")
                break
        
        if winner_found:
            break

        eventlet.sleep(3) # በየ 3 ሰከንዱ አዲስ ቁጥር ይጠራል

@socketio.on('start_game')
def handle_start_game():
    global is_game_active
    if not is_game_active:
        socketio.start_background_task(start_calling_numbers)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)
