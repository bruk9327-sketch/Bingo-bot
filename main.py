import os
import random
import time
from threading import Thread
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# =========================================================
# 1. FLASK & SOCKETIO SETUP
# =========================================================
app = Flask(__name__, template_folder='templates')
app.config['SECRET_KEY'] = 'bingo_secret_key_123'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# =========================================================
# 2. TELEGRAM BOT SETUP
# =========================================================
API_TOKEN = os.environ.get("BOT_TOKEN", "8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM")
bot = telebot.TeleBot(API_TOKEN)

# የ Render ዌብሳይትህ URL (ለምሳሌ፦ https://bingo-bot-c90r.onrender.com)
RENDER_WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://bingo-bot-c90r.onrender.com")

# =========================================================
# GAME STATE & IN-MEMORY DATABASE
# =========================================================
game_state = {
    "status": "WAITING",  # WAITING, PLAYING, FINISHED
    "time_left": 15,
    "drawn_numbers": [],
    "current_ball": None,
    "players_count": 228,
    "total_pool": 1824,
    "sold_cards": {}
}

# =========================================================
# FLASK ROUTES
# =========================================================
@app.route('/')
def index():
    return render_template('index.html')

# =========================================================
# TELEGRAM BOT HANDLERS
# =========================================================
@bot.message_handler(commands=['start', 'play'])
def send_webapp_button(message):
    markup = InlineKeyboardMarkup()
    web_app = WebAppInfo(url=RENDER_WEBAPP_URL)
    btn = InlineKeyboardButton(text="🎮 GoodBingo ተጫወት (Open App)", web_app=web_app)
    markup.add(btn)

    welcome_msg = (
        f"👋 ሰላም {message.from_user.first_name}!\n\n"
        "ወደ **GoodBingo Mini App** እንኳን ደህና መጡ! 🎲\n\n"
        "ከታች ያለውን አዝራር በመጫን የካርቴላ መምረጫ ዳሽቦርዱን ይክፈቱ።"
    )
    bot.send_message(message.chat.id, welcome_msg, reply_markup=markup, parse_mode="Markdown")

def run_bot():
    bot.infinity_polling()

# =========================================================
# REALTIME SOCKET.IO EVENTS & GAME ENGINE
# =========================================================
@socketio.on('connect')
def handle_connect():
    emit('init_game', game_state)

@socketio.on('select_card')
def handle_select_card(data):
    card_num = data.get('card_num')
    emit('card_selected_broadcast', {'card_num': card_num}, broadcast=True)

def game_loop():
    """የ 15 ሰከንድ ቆጠራ እና በየሰከንዱ ቁጥር የሚያወጣው የጌም ኢንጂን"""
    global game_state
    while True:
        # 1. ቆጠራ (WAITING PHASE)
        game_state["status"] = "WAITING"
        game_state["drawn_numbers"] = []
        game_state["current_ball"] = None
        
        for t in range(15, 0, -1):
            game_state["time_left"] = t
            socketio.emit('timer_update', {'time_left': t, 'status': 'WAITING'})
            socketio.sleep(1)

        # 2. ጨዋታው ተጀመረ (PLAYING PHASE)
        game_state["status"] = "PLAYING"
        socketio.emit('game_started', {'status': 'PLAYING'})

        all_numbers = list(range(1, 76))
        random.shuffle(all_numbers)

        for num in all_numbers:
            if game_state["status"] != "PLAYING":
                break
                
            game_state["drawn_numbers"].append(num)
            
            # የ B-I-N-G-O ፊደል መወሰን
            letter = 'B' if num <= 15 else 'I' if num <= 30 else 'N' if num <= 45 else 'G' if num <= 60 else 'O'
            ball_str = f"{letter}-{num}"
            game_state["current_ball"] = ball_str

            socketio.emit('new_number', {
                'number': num,
                'ball': ball_str,
                'drawn_list': game_state["drawn_numbers"]
            })

            # 10ኛው ቁጥር ሲወጣ የአሸናፊነት ማስታወቂያ (Demo)
            if len(game_state["drawn_numbers"]) == 10:
                winner_data = {
                    "winner_name": "Abrshi",
                    "prize": 1824,
                    "card_num": 62,
                    "card_matrix": [
                        [14, 26, 36, 58, 61],
                        [5,  28, 40, 57, 68],
                        [15, 17, "FREE", 56, 71],
                        [2,  27, 38, 59, 72],
                        [11, 16, 43, 54, 73]
                    ]
                }
                socketio.emit('winner_announced', winner_data)
                game_state["status"] = "FINISHED"
                socketio.sleep(8)
                break

            socketio.sleep(3)

# =========================================================
# MAIN EXECUTION
# =========================================================
if __name__ == "__main__":
    Thread(target=run_bot, daemon=True).start()
    socketio.start_background_task(game_loop)
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port)
