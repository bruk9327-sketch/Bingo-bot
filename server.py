import os
import time
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

# የጨዋታው መረጃዎች
called_numbers = []
is_game_active = False
STAKE_AMOUNT = 10
BOT_COMMISSION = 2
WINNER_PAYOUT = (STAKE_AMOUNT - BOT_COMMISSION) * 10  # 80 ETB

# የተጫዋቾች ካርቴላዎች መረጃ (ቁጥሮቹ ከ 1 እስከ 80 ባለው range የተዋቀሩ ናቸው)
players_cards = {
    "Player_1": {
        "cartela_id": "65",
        "grid": [
            [1, 20, 35, 50, 68],
            [6, 24, 38, 55, 72],
            [12, 26, 0,  58, 75],  # 0 ማለት FREE ቦታ ነው
            [14, 29, 44, 60, 78],
            [16, 32, 48, 64, 80]
        ]
    }
}

# አውቶማቲክ አሸናፊነትን የሚያረጋግጥ Function
def check_auto_bingo(grid, called_list):
    def is_marked(num):
        return num == 0 or num in called_list

    # 1. አግድም መስመሮችን (Rows) መፈተሽ
    for row in grid:
        if all(is_marked(num) for num in row):
            return True

    # 2. 垂直/ደေါንግሊ መስመሮችን (Columns) መፈተሽ
    for col in range(5):
        if all(is_marked(grid[row][col]) for row in range(5)):
            return True

    # 3. ሰያፍ መስመሮችን (Diagonals) መፈተሽ
    diagonal1 = [grid[i][i] for i in range(5)]
    diagonal2 = [grid[i][4 - i] for i in range(5)]
    
    if all(is_marked(num) for num in diagonal1) or all(is_marked(num) for num in diagonal2):
        return True

    return False

# ከ 1 እስከ 80 ያሉ ቁጥሮችን አውቶማቲክ የሚጠራ እና አሸናፊ የሚያስብል Loop
def start_calling_numbers():
    global called_numbers, is_game_active
    called_numbers = []
    is_game_active = True
    
    # ★ ከ1 እስከ 80 ያሉ ቁጥሮች ★
    all_numbers = list(range(1, 81))
    random.shuffle(all_numbers)

    print("🎲 የቢንጎ ጨዋታ ተጀመረ (ቁጥሮች፡ 1-80)...")

    for num in all_numbers:
        if not is_game_active:
            break
        
        called_numbers.append(num)
        
        # የተጠራውን ቁጥር ለሁሉ ተጫዋች መላክ
        socketio.emit('number_called', {'number': str(num)})
        print(f"📢 የተጠራ ቁጥር: {num}")

        # አውቶማቲክ አሸናፊ መኖሩን መፈተሽ
        for player_id, card_info in players_cards.items():
            if check_auto_bingo(card_info["grid"], called_numbers):
                is_game_active = False
                
                socketio.emit('auto_bingo_winner', {
                    'winnerId': player_id,
                    'cartelaId': card_info["cartela_id"],
                    'winningNumber': num,
                    'payout': WINNER_PAYOUT,
                    'message': f"🎉 BINGO! ተጫዋች {player_id} በካርቴላ #{card_info['cartela_id']} አሸንፏል!"
                })
                print(f"🏆 አውቶማቲክ አሸናፊ ተገኝቷል፦ {player_id}")
                break

        eventlet.sleep(3) # በየ 3 ሰከንዱ አዲስ ቁጥር ይጠራል

@socketio.on('connect')
def handle_connect():
    global is_game_active
    print("🔌 አዲስ ተጫዋች ተቀላቅሏል")
    if not is_game_active:
        socketio.start_background_task(start_calling_numbers)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)
