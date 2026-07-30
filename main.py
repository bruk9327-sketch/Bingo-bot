import os
import re
import random
import time
from threading import Thread
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
)

# =========================================================
# 1. SETUP & CONFIGURATION
# =========================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'bingo_secret_key_123'
socketio = SocketIO(app, cors_allowed_origins="*")

API_TOKEN = os.environ.get("BOT_TOKEN", "8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM")
bot = telebot.TeleBot(API_TOKEN)

RENDER_WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://bingo-bot-c90r.onrender.com")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "855985673"))

CARD_PRICE = 10.0
COMMISSION_RATE = 0.10  # 10% የቦት ኮሚሽን

user_balances = {}       
user_states = {}         
used_txn_ids = set()     

# =========================================================
# 2. BINGO CARDS DATABASE (1-104 CARDS)
# =========================================================
cards_database = {}

def generate_official_bingo_card(card_id):
    """ለእያንዳንዱ ካርቴላ ቋሚና ትክክለኛ Standard 75-Ball Bingo Grid ያመነጫል"""
    seed = int(card_id) * 997
    def get_col(min_v, max_v, count):
        nums = list(range(min_v, max_v + 1))
        nums.sort(key=lambda x: (abs(hash(str(seed + x)))))
        return sorted(nums[:count])

    b = get_col(1, 15, 5)
    i = get_col(16, 30, 5)
    n = get_col(31, 45, 4) 
    g = get_col(46, 60, 5)
    o = get_col(61, 75, 5)

    matrix = []
    for r in range(5):
        row = [
            b[r],
            i[r],
            'FREE' if r == 2 else (n[r] if r < 2 else n[r-1]),
            g[r],
            o[r]
        ]
        matrix.append(row)
    return matrix

# 104ቱን ካርቴላዎች አስቀድሞ ማዘጋጀት
for c_num in range(1, 105):
    cards_database[c_num] = generate_official_bingo_card(c_num)

# =========================================================
# 3. GAME STATE & BINGO WINNER CHECKER
# =========================================================
game_state = {
    "status": "WAITING",  # WAITING, COUNTDOWN, PLAYING, FINISHED
    "time_left": 15,
    "drawn_numbers": [],
    "selected_cards": {}, # card_id -> user_id
    "player_cards": {},   # user_id -> list of card_ids
    "derash": 0.0
}

def check_bingo_winner(matrix, drawn_set):
    """የ 5x5 መስመር (አግድም፣ ဒေါንግ ወይም ዲያጎናል) መሙላቱን ያረጋግጣል"""
    def is_hit(val):
        return val == 'FREE' or val in drawn_set

    # Rows (አግድም)
    for row in matrix:
        if all(is_hit(v) for v in row): return True
    # Cols (ዶንግ)
    for col in range(5):
        if all(is_hit(matrix[row][col]) for row in range(5)): return True
    # Diagonals (ዲያጎናል)
    d1 = [matrix[i][i] for i in range(5)]
    d2 = [matrix[i][4-i] for i in range(5)]
    if all(is_hit(v) for v in d1) or all(is_hit(v) for v in d2): return True

    return False

# =========================================================
# 4. FRONTEND HTML TEMPLATE
# =========================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="am">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>GoodBingo Mini App</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700;900&display=swap');
        body { font-family: 'Poppins', sans-serif; background: radial-gradient(circle at center, #1e1b4b 0%, #0f172a 100%); color: #fff; min-height: 100vh; }
        .glass-panel { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.1); }
        .gold-glow { box-shadow: 0 0 15px rgba(245, 158, 11, 0.6); }
        .ball-gradient { background: linear-gradient(135deg, #a855f7 0%, #6366f1 100%); }
    </style>
</head>
<body class="select-none pb-12 px-3">

    <!-- Top Status Bar -->
    <div class="grid grid-cols-4 gap-2 py-3 text-center text-xs font-bold">
        <div class="glass-panel rounded-2xl p-2.5 flex flex-col justify-center border-amber-500/50 gold-glow">
            <span class="text-[9px] text-amber-400 tracking-wider">ROOM</span>
            <span class="text-sm font-black text-amber-300">VIP 👑</span>
        </div>
        <div class="glass-panel rounded-2xl p-2.5 flex flex-col justify-center">
            <span class="text-[9px] text-gray-400 tracking-wider">SOLD</span>
            <span class="text-sm font-black text-white" id="sold-count">0</span>
        </div>
        <div class="glass-panel rounded-2xl p-2.5 flex flex-col justify-center border-red-500/40">
            <span class="text-[9px] text-red-400 tracking-wider">NEXT GAME</span>
            <span id="timer" class="text-sm font-black text-red-400 animate-pulse">15s</span>
        </div>
        <div class="glass-panel rounded-2xl p-2.5 flex flex-col justify-center border-emerald-500/40">
            <span class="text-[9px] text-emerald-400 tracking-wider">BET</span>
            <span class="text-sm font-black text-emerald-300">10 Br</span>
        </div>
    </div>

    <!-- Selection Screen -->
    <div id="selection-screen" class="mt-2">
        <div class="glass-panel p-3 rounded-2xl mb-3 text-center">
            <div class="text-xs font-semibold text-purple-300">🎲 የሚጫወቱባቸውን ካርቴላዎች ይምረጡ</div>
        </div>
        <div id="cartela-grid" class="grid grid-cols-8 gap-1.5 glass-panel p-3 rounded-3xl max-h-[52vh] overflow-y-auto">
        </div>
    </div>

    <!-- Active Game Screen -->
    <div id="game-screen" class="hidden mt-2">
        <div class="flex justify-between items-center text-xs mb-3 px-2 glass-panel py-2 rounded-xl">
            <div>ደራሽ (POT): <span class="text-emerald-400 font-black text-sm" id="derash-amount">0 ETB</span></div>
            <div>የወጡ ኳሶች: <span id="balls-count" class="font-black text-purple-400">0/75</span></div>
        </div>

        <div class="flex gap-2">
            <!-- 75 Board View -->
            <div class="w-1/3 glass-panel rounded-2xl p-2">
                <div class="grid grid-cols-5 text-center text-[10px] text-purple-400 font-black mb-1">
                    <div>B</div><div>I</div><div>N</div><div>G</div><div>O</div>
                </div>
                <div id="bingo-75-grid" class="grid grid-cols-5 gap-1 text-center text-[9px]">
                </div>
            </div>

            <!-- Current Drawn Ball & Cards -->
            <div class="w-2/3 flex flex-col items-center">
                <div id="current-ball" class="w-24 h-24 rounded-full ball-gradient flex items-center justify-center text-2xl font-black shadow-2xl border-4 border-purple-300/60 mb-3 animate-bounce">
                    READY
                </div>
                <div id="my-cards-container" class="w-full space-y-3">
                </div>
            </div>
        </div>
    </div>

    <!-- Winner Modal Popup -->
    <div id="winner-modal" class="fixed inset-0 bg-black/85 backdrop-blur-md flex items-center justify-center p-4 hidden z-50">
        <div class="glass-panel text-white rounded-3xl p-5 w-full max-w-sm text-center shadow-2xl relative border-2 border-amber-400 gold-glow">
            <div class="absolute -top-6 left-1/2 transform -translate-x-1/2 bg-amber-500 text-slate-900 font-black px-4 py-1 rounded-full text-xs shadow-lg">
                🏆 አሸናፊ ወጣ!
            </div>
            <div id="winner-name" class="text-2xl font-black text-amber-400 italic mt-3 mb-1">Winner</div>
            
            <div class="bg-slate-900/80 rounded-2xl p-3 mb-3 border border-amber-500/30">
                <div class="text-[10px] text-gray-400 font-bold">የተወሰደው ደራሽ (PRIZE)</div>
                <div id="winner-prize" class="text-2xl font-black text-emerald-400">0 ETB</div>
            </div>

            <div class="text-left font-bold text-purple-300 text-xs mb-1" id="winner-card-title">CARD #--</div>
            <div id="winner-card-matrix" class="grid grid-cols-5 gap-1 bg-slate-900/90 p-2 rounded-2xl text-center text-xs font-bold mb-4">
            </div>

            <div class="text-[10px] text-gray-400 mt-2 font-bold">አዲስ ዙር በሰከንዶች ውስጥ ይጀምራል...</div>
        </div>
    </div>

    <script>
        const socket = io();
        let userId = null;

        // የ Telegram User ID ን በትክክል ማምጣት
        if (window.Telegram && window.Telegram.WebApp) {
            window.Telegram.WebApp.ready();
            window.Telegram.WebApp.expand();
            if (window.Telegram.WebApp.initDataUnsafe && window.Telegram.WebApp.initDataUnsafe.user) {
                userId = window.Telegram.WebApp.initDataUnsafe.user.id;
            }
        }

        // ከቴሌግራም ውጭ ከተከፈተ ወይም ከURL parameter መውሰድ
        if (!userId) {
            const urlParams = new URLSearchParams(window.location.search);
            userId = parseInt(urlParams.get('user_id')) || 12345;
        }

        let mySelectedCards = [];
        let drawnNumbersSet = new Set();

        function initCartelaGrid() {
            const gridContainer = document.getElementById('cartela-grid');
            gridContainer.innerHTML = '';
            for (let i = 1; i <= 104; i++) {
                const btn = document.createElement('button');
                const isSelected = mySelectedCards.includes(i);
                
                btn.className = `p-2 text-xs font-bold rounded-xl transition-all duration-200 border ${isSelected ? 'bg-amber-500 text-slate-900 border-amber-300 font-black scale-105 shadow-lg' : 'bg-slate-800/80 text-gray-300 border-slate-700'}`;
                btn.innerText = i;
                btn.onclick = () => selectCard(i);
                gridContainer.appendChild(btn);
            }
        }

        function selectCard(cardId) {
            socket.emit('select_card', { user_id: userId, card_id: cardId });
        }

        socket.on('card_confirmed', (data) => {
            if(!mySelectedCards.includes(data.card_id)) {
                mySelectedCards.push(data.card_id);
            }
            initCartelaGrid();
        });

        socket.on('error_msg', (data) => {
            alert(data.msg);
        });

        function init75Board() {
            const board75 = document.getElementById('bingo-75-grid');
            board75.innerHTML = '';
            for (let i = 1; i <= 75; i++) {
                const cell = document.createElement('div');
                cell.id = `ball-cell-${i}`;
                cell.className = 'p-1 rounded bg-slate-800 text-gray-400 font-semibold';
                cell.innerText = i;
                board75.appendChild(cell);
            }
        }

        initCartelaGrid();
        init75Board();

        socket.on('timer_update', (data) => {
            document.getElementById('timer').innerText = `${data.time_left}s`;
            if (data.status === 'WAITING' || data.status === 'COUNTDOWN') {
                document.getElementById('winner-modal').classList.add('hidden');
                document.getElementById('game-screen').classList.add('hidden');
                document.getElementById('selection-screen').classList.remove('hidden');
            }
        });

        socket.on('game_update', (data) => {
            document.getElementById('sold-count').innerText = Object.keys(data.selected_cards).length;
        });

        socket.on('game_started', (data) => {
            document.getElementById('selection-screen').classList.add('hidden');
            document.getElementById('game-screen').classList.remove('hidden');
            document.getElementById('winner-modal').classList.add('hidden');
            document.getElementById('derash-amount').innerText = `${data.derash} ETB`;
            drawnNumbersSet.clear();
            init75Board();
            renderMyCards();
        });

        socket.on('new_number', (data) => {
            drawnNumbersSet.add(data.number);
            document.getElementById('current-ball').innerText = data.ball;
            document.getElementById('balls-count').innerText = `${data.drawn_list.length}/75`;
            
            const cell = document.getElementById(`ball-cell-${data.number}`);
            if(cell) {
                cell.className = 'p-1 rounded bg-emerald-500 text-slate-900 font-black animate-pulse shadow';
            }
            renderMyCards();
        });

        socket.on('winner_announced', (data) => {
            document.getElementById('winner-name').innerText = `${data.winner_name} አሸንፏል!`;
            document.getElementById('winner-prize').innerText = `${data.prize} ETB`;
            document.getElementById('winner-card-title').innerText = `CARD #${data.card_num}`;
            
            const matrixContainer = document.getElementById('winner-card-matrix');
            matrixContainer.innerHTML = '';
            
            data.card_matrix.forEach(row => {
                row.forEach(val => {
                    const div = document.createElement('div');
                    const isHit = val === 'FREE' || drawnNumbersSet.has(val);
                    div.className = `p-1.5 rounded-lg ${isHit ? 'bg-emerald-500 text-slate-900 font-bold' : 'bg-slate-800 text-gray-300'}`;
                    div.innerText = val === 'FREE' ? '★' : val;
                    matrixContainer.appendChild(div);
                });
            });

            document.getElementById('winner-modal').classList.remove('hidden');
            mySelectedCards = [];
        });

        function renderMyCards() {
            const container = document.getElementById('my-cards-container');
            container.innerHTML = '';
            
            mySelectedCards.forEach(cardId => {
                socket.emit('get_card_matrix', { card_id: cardId });
            });
        }

        socket.on('receive_card_matrix', (data) => {
            const container = document.getElementById('my-cards-container');
            const cardDiv = document.createElement('div');
            cardDiv.className = 'glass-panel rounded-2xl p-2.5 shadow-xl border-purple-500/30';
            
            let html = `<div class="flex justify-between items-center text-xs font-bold text-purple-300 mb-2"><span>CARD #${data.card_id}</span><span class="text-[9px] bg-purple-500/20 text-purple-300 px-1.5 py-0.5 rounded-full border border-purple-500/40">LIVE</span></div>`;
            html += `<div class="grid grid-cols-5 gap-1 text-center font-bold text-xs">`;
            
            data.matrix.forEach(row => {
                row.forEach(val => {
                    const isHit = val === 'FREE' || drawnNumbersSet.has(val);
                    html += `<div class="p-1.5 rounded-lg transition-colors ${isHit ? 'bg-emerald-500 text-slate-900 font-black shadow-md' : 'bg-slate-800/80 text-gray-200'}">${val === 'FREE' ? '★' : val}</div>`;
                });
            });
            
            html += `</div>`;
            cardDiv.innerHTML = html;
            container.appendChild(cardDiv);
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

# =========================================================
# 5. TELEGRAM BOT HANDLERS & DEPOSIT/WITHDRAW SYSTEM
# =========================================================
def main_menu_keyboard(user_id=None):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    # URL ላይ user_id ን አብሮ ማስተላለፍ
    app_url = f"{RENDER_WEBAPP_URL}?user_id={user_id}" if user_id else RENDER_WEBAPP_URL
    web_app = WebAppInfo(url=app_url)
    
    markup.add(
        KeyboardButton(text="🎲 ጨዋታ ጀምር (Open App)", web_app=web_app),
        KeyboardButton(text="👤 ፕሮፋይል / ባላንስ"),
        KeyboardButton(text="📥 ዲፖዚት (Deposit)"),
        KeyboardButton(text="📤 ዊዝድሮው (Withdraw)"),
        KeyboardButton(text="👥 ሪፈራል / ግብዣ"),
        KeyboardButton(text="ℹ️ እርዳታ እና ህጎች")
    )
    return markup

@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = message.from_user.id
    if uid not in user_balances:
        user_balances[uid] = 0.0

    welcome_txt = (
        f"👋 ሰላም **{message.from_user.first_name}**!\n\n"
        "ወደ **GoodBingo Pro** ኦፊሴላዊ የጨዋታ ቦት እንኳን ደህና መጡ! 🎲\n\n"
        "⚠️ **ህግ:** ጨዋታ ለመጫወት ቢያንስ **20 ETB** ዲፖዚት ማድረግ ይኖርብዎታል!"
    )
    bot.send_message(message.chat.id, welcome_txt, reply_markup=main_menu_keyboard(uid), parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and "ፕሮፋይል" in m.text)
def profile_cmd(message):
    uid = message.from_user.id
    bal = user_balances.get(uid, 0.0)
    msg = (
        f"👤 **የተጫዋች ፕሮፋይል**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 User ID: `{uid}`\n"
        f"💰 ወቅታዊ ባላንስ: **{bal:.2f} ETB**\n\n"
        f"{'✅ ጨዋታ መጫወት ይችላሉ!' if bal >= 10 else '⚠️ ጨዋታ ለመክፈት ቢያንስ 10 ETB ዲፖዚት ያድርጉ!'}"
    )
    bot.send_message(message.chat.id, msg, reply_markup=main_menu_keyboard(uid), parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and "ዲፖዚት" in m.text)
def deposit_cmd(message):
    uid = message.from_user.id
    user_states[uid] = "WAITING_DEPOSIT_INFO"
    
    dep_text = (
        "📥 **ገንዘብ ማስገቢያ (Deposit)**\n"
        "━━━━━━━━━━━━━━━\n"
        "እባክዎን ከታች ባሉት የክፍያ አማራጮች ገንዘብ ያስገቡ፦\n\n"
        "📱 **Telebirr:** `0991983522`\n"
        "🏦 **CBE Birr:** `0991983522`\n\n"
        "⚠️ **ከክፍያ በኋላ መላክ ያለበት ፎርማት፦**\n"
        "ያስገቡትን የብር መጠን እና የትራንዛክሽን ቁጥር በግልጽ ይጻፉ ወይም ስክሪንሾት ይላኩ።\n\n"
        "📌 **ምሳሌ፦** `50 ETB - TXN98765432`"
    )
    bot.send_message(message.chat.id, dep_text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "WAITING_DEPOSIT_INFO", content_types=['text', 'photo'])
def handle_deposit_submission(message):
    uid = message.from_user.id
    text_content = message.text if message.text else message.caption

    extracted_txn = None
    extracted_amount = 0

    if text_content:
        txn_match = re.search(r'([A-Za-z0-9]{6,20})', text_content)
        if txn_match:
            extracted_txn = txn_match.group(1).upper()

        numbers = re.findall(r'\d+', text_content)
        for num in numbers:
            val = int(num)
            if val >= 20:
                extracted_amount = val
                break

    if extracted_txn and extracted_txn in used_txn_ids:
        bot.send_message(message.chat.id, f"❌ **ይህ የትራንዛክሽን ቁጥር (`{extracted_txn}`) ከዚህ ቀደም አገልግሎት ላይ ውሏል!**", parse_mode="Markdown")
        return

    if extracted_txn:
        used_txn_ids.add(extracted_txn)

    user_states[uid] = None
    dep_id = f"DEP_{int(time.time())}_{uid}"
    
    markup = InlineKeyboardMarkup()
    suggested_amt = extracted_amount if extracted_amount >= 20 else 20
    markup.row(
        InlineKeyboardButton(f"✅ Approve {suggested_amt} ETB", callback_data=f"app_{suggested_amt}_{uid}_{dep_id}"),
        InlineKeyboardButton("✅ Approve 50 ETB", callback_data=f"app_50_{uid}_{dep_id}")
    )
    markup.row(
        InlineKeyboardButton("✅ Approve 100 ETB", callback_data=f"app_100_{uid}_{dep_id}"),
        InlineKeyboardButton("✅ Approve 150 ETB", callback_data=f"app_150_{uid}_{dep_id}")
    )
    markup.row(InlineKeyboardButton("❌ Reject", callback_data=f"rej_{uid}_{dep_id}"))

    admin_msg = (
        f"🚨 **አዲስ የተረጋገጠ የዲፖዚት ጥያቄ!**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 ተጫዋች: {message.from_user.first_name} (`{uid}`)\n"
        f"🔍 Txn ID: `{extracted_txn if extracted_txn else 'አልተገኘም'}`\n"
        f"💵 የታሰበው መጠን: **{suggested_amt} ETB**\n"
        f"📝 መልእክት: {text_content if text_content else 'Photo Sent'}"
    )
    
    try:
        if message.photo:
            bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=admin_msg, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(ADMIN_ID, admin_msg, reply_markup=markup, parse_mode="Markdown")
            
        bot.send_message(message.chat.id, "✅ **የዲፖዚት መረጃዎ ተላክቷል!** አድሚኑ አጣርቶ በቅርቡ ባላንስዎን ያዘምነዋል።")
    except Exception as e:
        bot.send_message(message.chat.id, "✅ ጥያቄዎ ተመዝግቧል! አድሚኑ አጣርቶ ያጸድቅሎታል።")

@bot.callback_query_handler(func=lambda call: call.data.startswith(('app_', 'rej_')))
def handle_admin_approval(call):
    parts = call.data.split('_')
    action = parts[0]
    
    if action == "rej":
        target_uid = int(parts[1])
        bot.answer_callback_query(call.id, "ዲፖዚቱ ተሰርዟል!")
        bot.edit_message_text(f"❌ **Deposit Rejected** for User `{target_uid}`", call.message.chat.id, call.message.message_id)
        bot.send_message(target_uid, "❌ **የዲፖዚት ጥያቄዎ አልተቀበለም!**")
    
    elif action == "app":
        amount_val = float(parts[1])
        target_uid = int(parts[2])

        user_balances[target_uid] = user_balances.get(target_uid, 0.0) + amount_val
        new_bal = user_balances[target_uid]

        bot.answer_callback_query(call.id, f"{amount_val} ETB ፀድቋል!")
        bot.edit_message_text(f"✅ **Deposit Approved!**\nUser: `{target_uid}`\nAmount: **+{amount_val} ETB**\nNew Balance: **{new_bal} ETB**", call.message.chat.id, call.message.message_id)
        
        bot.send_message(
            target_uid, 
            f"🎉 **ዲፖዚትዎ ፀድቋል!**\n\n"
            f"📥 የተጨመረ: **+{amount_val:.2f} ETB**\n"
            f"💰 አጠቃላይ ባላንስ: **{new_bal:.2f} ETB**",
            reply_markup=main_menu_keyboard(target_uid),
            parse_mode="Markdown"
        )

@bot.message_handler(func=lambda m: m.text and "ዊዝድሮው" in m.text)
def withdraw_cmd(message):
    uid = message.from_user.id
    bal = user_balances.get(uid, 0.0)
    if bal < 50:
        bot.send_message(message.chat.id, f"❌ **ዝቅተኛው የዊዝድሮው መጠን 50 ETB ነው።**\nየእርስዎ ባላንስ: **{bal:.2f} ETB**")
        return
    bot.send_message(message.chat.id, f"📤 **ገንዘብ ማውጫ**\nየእርስዎ ባላንስ: **{bal:.2f} ETB**\nእባክዎን የሚያወጡትን መጠን እና የቴሌብር/ባንክ ቁጥር ይላኩ።", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and "ሪፈራል" in m.text)
def referral_cmd(message):
    uid = message.from_user.id
    bot_name = bot.get_me().username
    ref_link = f"https://t.me/{bot_name}?start={uid}"
    bot.send_message(message.chat.id, f"👥 **የሪፈራል ፕሮግራም**\n🔗 የእርስዎ የግብዣ ሊንክ፦\n`{ref_link}`", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and "እርዳታ" in m.text)
def help_cmd(message):
    help_txt = (
        "ℹ️ **የጨዋታ ህጎች**\n"
        "1. እያንዳንዱ ካርቴላ **10 ETB** ያወጣል።\n"
        "2. አሸናፊው ከጠቅላላው የካርቴላ ሽያጭ 10% የቦት ኮሚሽን ተቀንሶ **ደራሹን በሙሉ** ይወስዳል።"
    )
    bot.send_message(message.chat.id, help_txt, parse_mode="Markdown")

def run_bot():
    while True:
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.polling(none_stop=True)
        except Exception as e:
            print(f"Bot Polling Error: {e}")
            time.sleep(3)

# =========================================================
# 6. SOCKET.IO EVENTS & REAL GAME LOOP
# =========================================================
@socketio.on('select_card')
def handle_card_selection(data):
    uid = int(data.get('user_id'))
    card_id = int(data.get('card_id'))

    if game_state['status'] not in ['WAITING', 'COUNTDOWN']:
        emit('error_msg', {'msg': 'ጨዋታ ተጀምሯል! እባክዎን አዲስ ዙር ይበቁ።'})
        return

    bal = user_balances.get(uid, 0.0)
    if bal < CARD_PRICE:
        emit('error_msg', {'msg': f'በቂ ባላንስ የሎትም። እባክዎን ዲፖዚት ያድርጉ! (የእርስዎ ባላንስ: {bal:.2f} ETB)'})
        return

    if card_id in game_state['selected_cards']:
        emit('error_msg', {'msg': 'ይህ ካርቴላ በተခြား ተጫዋች ተይዟል!'})
        return

    # ክፍያ መቀነስ እና ካርቴላ መመዝገብ
    user_balances[uid] -= CARD_PRICE
    game_state['selected_cards'][card_id] = uid
    if uid not in game_state['player_cards']:
        game_state['player_cards'][uid] = []
    game_state['player_cards'][uid].append(card_id)

    # ደራሽ ማዘመን (10% ኮሚሽን)
    total_pool = len(game_state['selected_cards']) * CARD_PRICE
    game_state['derash'] = round(total_pool * (1 - COMMISSION_RATE), 2)

    emit('card_confirmed', {'card_id': card_id}, broadcast=False)
    socketio.emit('game_update', game_state)

@socketio.on('get_card_matrix')
def handle_get_matrix(data):
    c_id = int(data.get('card_id'))
    if c_id in cards_database:
        emit('receive_card_matrix', {'card_id': c_id, 'matrix': cards_database[c_id]})

def game_loop():
    global game_state
    while True:
        # 1. ማቆም/መጠበቅ
        game_state["status"] = "WAITING"
        game_state["drawn_numbers"] = []
        game_state["selected_cards"] = {}
        game_state["player_cards"] = {}
        game_state["derash"] = 0.0

        while len(game_state["selected_cards"]) == 0:
            socketio.sleep(1)

        # 2. ቆጠራ (Countdown)
        game_state["status"] = "COUNTDOWN"
        for t in range(15, 0, -1):
            game_state["time_left"] = t
            socketio.emit('timer_update', {'time_left': t, 'status': 'COUNTDOWN'})
            socketio.sleep(1)

        # 3. ጨዋታ መጀመር
        game_state["status"] = "PLAYING"
        socketio.emit('game_started', {'status': 'PLAYING', 'derash': game_state['derash']})

        all_numbers = list(range(1, 76))
        random.shuffle(all_numbers)

        drawn_set = set()
        winner_found = False

        for num in all_numbers:
            if winner_found:
                break

            drawn_set.add(num)
            game_state["drawn_numbers"].append(num)

            letter = 'B' if num <= 15 else 'I' if num <= 30 else 'N' if num <= 45 else 'G' if num <= 60 else 'O'
            ball_str = f"{letter}-{num}"

            socketio.emit('new_number', {
                'number': num,
                'ball': ball_str,
                'drawn_list': game_state["drawn_numbers"]
            })

            # እውነተኛ አሸናፊ መኖሩን መፈተሽ
            for uid, cards in game_state["player_cards"].items():
                for card_id in cards:
                    matrix = cards_database[card_id]
                    if check_bingo_winner(matrix, drawn_set):
                        winner_found = True
                        # አሸናፊውን ማበሰር እና ደራሹን በባላንሱ ላይ መጨመር
                        user_balances[uid] = user_balances.get(uid, 0.0) + game_state["derash"]
                        
                        socketio.emit('winner_announced', {
                            "winner_name": f"User_{uid}",
                            "prize": game_state["derash"],
                            "card_num": card_id,
                            "card_matrix": matrix
                        })
                        break
                if winner_found:
                    break

            socketio.sleep(3)

        game_state["status"] = "FINISHED"
        socketio.sleep(8)

# =========================================================
# 7. MAIN EXECUTION
# =========================================================
if __name__ == "__main__":
    Thread(target=run_bot, daemon=True).start()
    socketio.start_background_task(game_loop)
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
