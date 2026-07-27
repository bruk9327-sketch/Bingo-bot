import os
import time
import random
import eventlet

# Render ላይ WebSocket በትክክል እንዲሰራ Eventlet Monkey Patch ይደረጋል
eventlet.monkey_patch()

from flask import Flask, render_template
from flask_socketio import SocketIO, emit

app = Flask(__name__, template_folder='.')
app.config['SECRET_KEY'] = 'bingo_secret_key_12345'

# Render ላይ ከየትኛውም ዶሜይን (Telegram WebApp ጨምሮ) ግንኙነት እንዲቀበል CORS የተፈቀደ ነው
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# =========================================================
# GAME CONFIGURATION & STATE
# =========================================================
STAKE_AMOUNT = 10        # የመግቢያ ክፍያ (10 ብር)
BOT_COMMISSION = 2       # ከእያንዳንዱ ተጫዋች የሚወሰድ ኮሚሽን (2 ብር)
NET_PER_PLAYER = STAKE_AMOUNT - BOT_COMMISSION  # 8 ብር

called_numbers_history = []
is_game_active = False

@app.route('/')
def index():
    # index.html ፋይልን ከ Render ለማቅረብ
    return render_template('index.html')

# =========================================================
# BINGO ENGINE (AUTOMATIC NUMBER CALLER)
# =========================================================
def start_calling_numbers():
    global called_numbers_history, is_game_active
    
    called_numbers_history = []
    is_game_active = True
    
    # 1 እስከ 75 ያሉ የቢንጎ ቁጥሮች
    all_numbers = list(range(1, 76))
    random.shuffle(all_numbers)

    print("🎲 ጨዋታው ተጀምሯል! ቁጥሮች መጠራት ጀምረዋል...")

    for num in all_numbers:
        if not is_game_active:
            print("🛑 ጨዋታው በአሸናፊነት ወይም በስህተት ተቋርጧል።")
            break
        
        called_numbers_history.append(num)
        
        # ለሁሉም የተገናኙ ተጫዋቾች የተጠራውን ቁጥር በWebSocket መላክ
        socketio.emit('number_called', {'number': num})
        print(f"📢 የተጠራ ቁጥር: {num}")
        
        # በየ 3 ሰከንዱ አዲስ ቁጥር ይጠራል (እንደ ፍላጎትህ የሰከንዱን መጠን መቀየር ትችላለህ)
        eventlet.sleep(3)

# =========================================================
# WEBSOCKET EVENT HANDLERS
# =========================================================
@socketio.on('connect')
def handle_connect():
    print("🔌 አዲስ ተጫዋች ከሰርቨሩ ጋር ተገናኝቷል (Connected)")

@socketio.on('disconnect')
def handle_disconnect():
    print("❌ ተጫዋች ከሰርቨሩ ተቋርጧል (Disconnected)")

@socketio.on('start_game_session')
def trigger_game():
    global is_game_active
    if not is_game_active:
        # ቁጥር መጥራቱን በጀርባ (Background Task) ማስጀመር
        socketio.start_background_task(start_calling_numbers)

@socketio.on('claim_bingo')
def handle_bingo_claim(data):
    global is_game_active
    
    user_id = data.get('userId', 'Unknown')
    user_selected = data.get('selectedNumbers', [])

    print(f"📩 ተጠቃሚ {user_id} BINGO ብሏል! የመረጣቸው ቁጥሮች: {user_selected}")

    # 1. ተጫዋቹ የመረጣቸው ቁጥሮች በሙሉ በሰርቨሩ ከተጠሩት መሆናቸውን ማረጋገጥ
    is_valid_calls = all(num in called_numbers_history for num in user_selected)

    # 2. ቢያንስ 4 ወይም 5 ቁጥሮች መመረጣቸውን ማረጋገጥ
    has_enough_numbers = len(user_selected) >= 4

    if is_valid_calls and has_enough_numbers and is_game_active:
        is_game_active = False  # ጨዋታውን ማቆም
        
        # የ 10 ተጫዋች ፖል ስሌት፦ 10 * 8 = 80 ብር አሸናፊው ያገኛል (20 ብር የቦቱ ኮሚሽን)
        total_players = 10
        winner_payout = total_players * NET_PER_PLAYER # 80 ብር
        
        # ለአሸናፊው እና ለሌሎች ተጫዋቾች ማስታወቂያ መላክ
        emit('bingo_response', {
            'success': True, 
            'message': 'አሸንፈዋል!', 
            'winnerId': user_id,
            'payout': winner_payout
        }, broadcast=True)
        
        print(f"🏆 ተጫዋች {user_id} የ {winner_payout} ብር አሸናፊ ሆኗል!")
    else:
        # የተሳሳተ ቢንጎ ከሆነ ለጠየቀው ተጫዋች ብቻ ስህተቱን መላክ
        emit('bingo_response', {
            'success': False, 
            'message': 'የተሳሳተ ቢንጎ! ያልተጠራ ቁጥር መርጠዋል ወይም ገና አልሞሉም።'
        })

# =========================================================
# RENDER DEPLOYMENT SERVER LAUNCHER
# =========================================================
if __name__ == '__main__':
    # Render በራሱ የሚመድበውን PORT መጠቀም (ከሌለ በዳግም 5000)
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 የቢንጎ ሰርቨር በ PORT {port} ላይ እየሰራ ነው...")
    socketio.run(app, host='0.0.0.0', port=port)
