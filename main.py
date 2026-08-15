import os
import random
import threading
from threading import Thread
import telebot
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy

# =========================================================
# 1. CONFIGURATION & INITIALIZATION
# =========================================================
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"          # የእርስዎን ዋና የቦት ቶከን ያስገቡ
SUPPORT_TOKEN = "YOUR_SUPPORT_BOT_TOKEN"     # የድጋፍ ቦት ቶከን ያስገቡ (@BkbingosupportBot)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'bkbingo_secret_key_2026'

# የ Render PostgreSQL Database URL (Render ላይ 'postgres://' የሚለውን ቃል በ 'postgresql://' መቀየር ስለሚያስፈልግ ራሱ ያስተካክለዋል)
db_url = "postgresql://bkbingo_user:Ll2Eje6ty0BnpkIJ4nmPZgSBBlugYbfT@dpg-da07aae1egvs7382q0l0-a/bkbingo"
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

bot = telebot.TeleBot(TOKEN)
support_bot = telebot.TeleBot(SUPPORT_TOKEN)

# ውድድር እና ጨዋታ መቆጣጠሪያ ተለዋዋጮች
CARD_PRICE = 10.0
MAX_CARDS_PER_PLAYER = 4
COMMISSION_RATE = 0.10  # 10% የቤት ድርሻ (Commission)

game_state = {
    "status": "WAITING",  # WAITING, PLAYING, FINISHED
    "time_left": 20,
    "drawn_numbers": [],
    "selected_cards": {}, # {user_id: [card_ids]}
    "derash": 0.0
}

db_lock = threading.Lock()

# =========================================================
# 2. DATABASE MODELS (SQLAlchemy)
# =========================================================
class User(db.Model):
    __tablename__ = 'users'
    
    id = db.BigInteger(primary_key=True)  # የቴሌግራም User ID
    balance = db.Float(default=0.0)       # የአካውንት ሂሳብ
    name = db.String(100), nullable=True
    created_at = db.DateTime(server_default=db.func.now())
    
    histories = db.relationship('History', backref='user', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.id} - Balance: {self.balance}>"


class History(db.Model):
    __tablename__ = 'histories'
    
    id = db.Integer(primary_key=True, autoincrement=True)
    user_id = db.BigInteger(db.ForeignKey('users.id'), nullable=False)
    action_type = db.String(50), nullable=False  # ምሳሌ፦ 'ካርቴላ ግዢ', 'ዲፖዚት', 'ቢንጎ አሸናፊ'
    description = db.String(255), nullable=True
    timestamp = db.DateTime(server_default=db.func.now())

    def __repr__(self):
        return f"<History {self.action_type} for User {self.user_id}>"


# ሰንጠረዦቹን በ ትግበራ መጀመሪያ መፍጠር
with app.app_context():
    db.create_all()
    print("PostgreSQL ዳታቤዝ ሰንጠረዦች (Users & Histories) በተሳካ ሁኔታ ተፈጥረዋል!")


# ዳታቤዝ ረዳት ተግባራት (Helper Functions)
def get_or_create_user(uid, name=None):
    user = User.query.get(uid)
    if not user:
        user = User(id=uid, balance=0.0, name=name or f"User {uid}")
        db.session.add(user)
        db.session.commit()
    elif name and user.name != name:
        user.name = name
        db.session.commit()
    return user

def add_user_history(uid, action_type, description):
    hist = History(user_id=uid, action_type=action_type, description=description)
    db.session.add(hist)
    db.session.commit()


# =========================================================
# 3. BINGO CARD GENERATOR & LOGIC
# =========================================================
def generate_bingo_card():
    card = {}
    cols = {
        'B': range(1, 16),
        'I': range(16, 31),
        'N': range(31, 46),
        'G': range(46, 61),
        'O': range(61, 76)
    }
    for letter, rng in cols.items():
        card[letter] = random.sample(list(rng), 5)
    card['N'][2] = 'FREE'
    
    matrix = []
    letters = ['B', 'I', 'N', 'G', 'O']
    for row_idx in range(5):
        row = []
        for col_idx in range(5):
            letter = letters[col_idx]
            row.append(card[letter][row_idx])
        matrix.append(row)
    return matrix

# ናሙና ካርቴላዎች ዳታቤዝ (በ RAM ውስጥ የሚቀመጡ የማይንቀሳቀሱ ካርቴላዎች)
cards_database = {i: generate_bingo_card() for i in range(1, 101)}

def get_letter_and_display(number):
    if 1 <= number <= 15: letter = 'B'
    elif 16 <= number <= 30: letter = 'I'
    elif 31 <= number <= 45: letter = 'N'
    elif 46 <= number <= 60: letter = 'G'
    elif 61 <= number <= 75: letter = 'O'
    else: letter = ''
    return {'letter': letter, 'display': f"{letter}-{number}"}

def validate_bingo_board(board):
    if not board or len(board) != 5:
        return False
    # መስመሮችን (Rows) ማረጋገጥ
    for row in board:
        if all(cell == 'MARKED' or cell == 'FREE' for cell in row):
            return True
    # አምዶችን (Columns) ማረጋገጥ
    for col in range(5):
        if all(board[row][col] == 'MARKED' or board[row][col] == 'FREE' for row in range(5)):
            return True
    # ሰያፍ መስመሮችን (Diagonals) ማረጋገጥ
    if all(board[i][i] == 'MARKED' or board[i][i] == 'FREE' for i in range(5)):
        return True
    if all(board[i][4 - i] == 'MARKED' or board[i][4 - i] == 'FREE' for i in range(5)):
        return True
    return False


# =========================================================
# 4. TELEGRAM BOTS ROUTINES
# =========================================================
def set_bot_commands():
    try:
        bot.set_my_commands([
            telebot.types.BotCommand("start", "ቦቱን ያስጀምሩ"),
            telebot.types.BotCommand("help", "እርዳታ ማግኛ")
        ])
    except Exception as e:
        print(f"Command set error: {e}")

@bot.message_handler(commands=['start'])
def send_welcome(message):
    uid = message.from_user.id
    name = message.from_user.first_name
    
    with app.app_context():
        get_or_create_user(uid, name)

    markup = telebot.types.InlineKeyboardMarkup()
    web_app = telebot.types.WebAppInfo(url="https://your-render-app-url.onrender.com") # የRender ሊንክዎን ያስገቡ
    markup.add(telebot.types.InlineKeyboardButton("🎮 Play BKBINGO Pro", web_app=web_app))
    markup.add(telebot.types.InlineKeyboardButton("💬 የደንበኛ አገልግሎት (Support)", url="https://t.me/BkbingosupportBot"))
    
    bot.reply_to(message, f"ሰላም {name}! እንኳን ወደ **bkbingo pro** በደህና መጡ። ጨዋታውን ለመጀመር ከታች ያለውን ቁልፍ ይጫኑ።", reply_markup=markup, parse_mode="Markdown")

@support_bot.message_handler(commands=['start'])
def support_welcome(message):
    support_bot.reply_to(message, "ሰላም! ወደ bkbingo pro የድጋፍ ማዕከል በሰላም መጡ። ጥያቄዎን ወይም ያጋጠመዎትን ችግር እዚህጋ ይጻፉልን።")


# =========================================================
# 5. FLASK WEB ROUTES
# =========================================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/user/balance/<int:user_id>', methods=['GET'])
def api_get_balance(user_id):
    with app.app_context():
        user = User.query.get(user_id)
        bal = user.balance if user else 0.0
    return jsonify({'user_id': user_id, 'balance': bal})


# =========================================================
# 6. WEBSOCKET GAME ENGINE & EVENTS
# =========================================================
@socketio.on('get_user_balance')
def handle_get_user_balance(data):
    uid = int(data.get('user_id'))
    with app.app_context():
        user = User.query.get(uid)
        bal = user.balance if user else 0.0
    emit('balance_update', {'user_id': uid, 'balance': bal})

@socketio.on('select_card')
def handle_select_card(data):
    uid = int(data.get('user_id'))
    card_id = int(data.get('card_id'))

    with app.app_context():
        if game_state["status"] != "WAITING":
            emit('error_msg', {'msg': 'ጨዋታው ተጀምሯል! አሁን ካርቴላ መምረጥ አይቻልም።'}, room=request.sid)
            return

        user_selected = game_state["selected_cards"].get(uid, [])
        
        if card_id in [c for cards in game_state["selected_cards"].values() for c in cards]:
            emit('error_msg', {'msg': 'ይህ ካርቴላ በሌላ ተጫዋች ተይዟል!'}, room=request.sid)
            return

        user = get_or_create_user(uid)

        if card_id in user_selected:
            user_selected.remove(card_id)
            game_state["selected_cards"][uid] = user_selected
            
            user.balance += CARD_PRICE
            db.session.commit()
            new_bal = user.balance
            
            emit('balance_update', {'user_id': uid, 'balance': new_bal})
            add_user_history(uid, "ካርቴላ መልቀቅ", f"ካርቴላ #{card_id} ተለቋል (+{CARD_PRICE:.2f} ETB ተመላሽ)")
        else:
            if len(user_selected) >= MAX_CARDS_PER_PLAYER:
                emit('error_msg', {'msg': f'በአንድ ዙር ቢበዛ {MAX_CARDS_PER_PLAYER} ካርቴላ ብቻ መግዛት ይቻላል!'}, room=request.sid)
                return

            if user.balance < CARD_PRICE:
                emit('error_msg', {'msg': 'በቂ ባላንስ የለዎትም! እባክዎን አካውንትዎን ይሙሉ (Deposit)'}, room=request.sid)
                return

            user.balance -= CARD_PRICE
            db.session.commit()
            new_bal = user.balance
            
            user_selected.append(card_id)
            game_state["selected_cards"][uid] = user_selected

            emit('balance_update', {'user_id': uid, 'balance': new_bal})
            add_user_history(uid, "ካርቴላ ግዢ", f"ካርቴላ #{card_id} ተገዝቷል (-{CARD_PRICE:.2f} ETB)")

        matrix = cards_database.get(card_id)
        emit('card_confirmed', {'card_id': card_id, 'matrix': matrix, 'new_balance': new_bal})

    all_taken = [c for cards in game_state["selected_cards"].values() for c in cards]
    socketio.emit('update_selected_cards', {'taken_cards': all_taken})

@socketio.on('player_mark_number')
def handle_player_mark_number(data):
    pass

@socketio.on('claim_bingo')
def handle_claim_bingo(data):
    uid = int(data.get('user_id'))
    card_id = int(data.get('card_id'))
    board_matrix = data.get('board')

    with app.app_context():
        if game_state["status"] != "PLAYING":
            emit('bingo_response', {'status': 'error', 'message': '❌ ጨዋታው በመካሄድ ላይ አይደለም!'}, room=request.sid)
            return

        user_cards = game_state["selected_cards"].get(uid, [])
        if card_id not in user_cards:
            emit('bingo_response', {'status': 'error', 'message': '❌ ይህ ካርቴላ የእርስዎ አይደለም!'}, room=request.sid)
            return

        if not validate_bingo_board(board_matrix):
            emit('bingo_response', {'status': 'error', 'message': '❌ የተደረገው ቢንጎ ትክክለኛ አይደለም!'}, room=request.sid)
            return

        game_state["status"] = "FINISHED"
        total_pool = game_state["derash"]
        commission = total_pool * COMMISSION_RATE
        winner_prize = total_pool - commission

        user = get_or_create_user(uid)
        user.balance += winner_prize
        db.session.commit()
        
        winner_bal = user.balance
        winner_name = user.name

        add_user_history(uid, "ቢንጎ አሸናፊ (Bingo Win)", f"+{winner_prize:.2f} ETB ከካርቴላ #{card_id} አሸንፈዋል")

        socketio.emit('balance_update', {'user_id': uid, 'balance': winner_bal})
        socketio.emit('winner_announced', {
            'winner_names': winner_name,
            'winner_name': winner_name,
            'winner_ids': [uid],
            'prize': winner_prize,
            'card_id': card_id,
            'card_matrix': cards_database.get(card_id)
        })

def game_loop_background_worker():
    global game_state
    while True:
        try:
            with app.app_context():
                game_state["status"] = "WAITING"
                game_state["time_left"] = 20
                game_state["drawn_numbers"] = []
                game_state["selected_cards"] = {}
                game_state["derash"] = 0.0

            socketio.emit('reset_game', {})

            for t in range(20, 0, -1):
                with app.app_context():
                    game_state["time_left"] = t
                    sold_count = sum(len(cards) for cards in game_state["selected_cards"].values())
                socketio.emit('timer_update', {'time_left': t, 'sold_count': sold_count})
                socketio.sleep(1)

            with app.app_context():
                sold_count = sum(len(cards) for cards in game_state["selected_cards"].values())
                if sold_count == 0:
                    continue

                game_state["status"] = "PLAYING"
                total_collected = sold_count * CARD_PRICE
                game_state["derash"] = total_collected

            socketio.emit('game_started', {'derash': game_state["derash"]})

            all_75_balls = list(range(1, 76))
            random.shuffle(all_75_balls)

            for ball in all_75_balls:
                with app.app_context():
                    if game_state["status"] != "PLAYING":
                        break
                    game_state["drawn_numbers"].append(ball)
                
                info = get_letter_and_display(ball)
                socketio.emit('new_number', {'ball': ball, 'display': info['display'], 'letter': info['letter']})
                socketio.sleep(4.5)

                with app.app_context():
                    if game_state["status"] != "PLAYING":
                        break
            
            socketio.sleep(5)
        except Exception as e:
            print(f"Game loop error: {e}")
            socketio.sleep(2)


# =========================================================
# 7. INITIALIZATION & EXECUTION
# =========================================================
if __name__ == '__main__':
    set_bot_commands()
    
    t_main = Thread(target=bot.infinity_polling, kwargs={"skip_pending": True})
    t_main.daemon = True
    t_main.start()

    t_support = Thread(target=support_bot.infinity_polling, kwargs={"skip_prior_updates": True})
    t_support.daemon = True
    t_support.start()

    socketio.start_background_task(game_loop_background_worker)

    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)
