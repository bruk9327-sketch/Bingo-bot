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
MAX_CARDS_PER_PLAYER = 2 # በአንድ ዙር የሚፈቀደው ከፍተኛ የካርቴላ ብዛት
MIN_WITHDRAWAL = 50.0   # ዝቅተኛው የወጪ ብር መጠን

user_balances = {}       
user_states = {}         
withdraw_data = {}       # የዊዝድሮው ጊዜያዊ መረጃ መያዣ {user_id: {'method': '', 'account': ''}}
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
    """የ 5x5 መስመር መሙላቱን ያረጋግጣል"""
    def is_hit(val):
        return val == 'FREE' or val in drawn_set

    for row in matrix:
        if all(is_hit(v) for v in row): return True
    for col in range(5):
        if all(is_hit(matrix[row][col]) for row in range(5)): return True
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
    <title>BKBingo House Bot</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700;900&display=swap');
        body { font-family: 'Poppins', sans-serif; background: #0f172a; color: #fff; min-height: 100vh; }
        .glass-panel { background: #1e293b; border: 1px solid rgba(255, 255, 255, 0.1); }
        .ball-gradient { background: linear-gradient(135deg, #a855f7 0%, #6366f1 100%); }
    </style>
</head>
<body class="select-none pb-12 px-3">

    <!-- Top Status Bar -->
    <div class="grid grid-cols-5 gap-1.5 py-3 text-center text-xs font-bold">
        <div class="glass-panel rounded-xl p-2 flex flex-col justify-center border border-amber-500/50">
            <span class="text-[8px] text-amber-400">ROOM VIP 💰</span>
        </div>
        <div class="glass-panel rounded-xl p-2 flex flex-col justify-center">
            <span class="text-[8px] text-gray-400">SOLD</span>
            <span class="text-xs font-black text-white" id="sold-count">0</span>
        </div>
        <div class="glass-panel rounded-xl p-2 flex flex-col justify-center">
            <span class="text-[8px] text-gray-400">TIME</span>
            <span id="timer" class="text-xs font-black text-red-400">15s</span>
        </div>
        <div class="glass-panel rounded-xl p-2 flex flex-col justify-center">
            <span class="text-[8px] text-gray-400">CALL</span>
            <span id="balls-count" class="text-xs font-black text-purple-400">0</span>
        </div>
        <div class="bg-emerald-600 rounded-xl p-2 flex flex-col justify-center text-white">
            <span class="text-[8px] opacity-80">BALANCE</span>
            <span class="text-xs font-black" id="user-balance-disp">0.00 ETB</span>
        </div>
    </div>

    <!-- Selection Screen -->
    <div id="selection-screen" class="mt-1">
        <div id="cartela-grid" class="grid grid-cols-8 gap-1 bg-white p-2 rounded-2xl max-h-[38vh] overflow-y-auto">
        </div>
        
        <div class="text-center text-xs text-amber-400 font-bold my-2">
            ⚠️ በአንድ ዙር መያዝ የሚቻለው ቢበዛ 2 ካርቴላ ብቻ ነው!
        </div>

        <div id="preview-cards-container" class="grid grid-cols-2 gap-2 mt-2">
        </div>
    </div>

    <!-- Active Game Screen -->
    <div id="game-screen" class="hidden mt-2">
        <div class="flex justify-between items-center text-xs mb-3 px-2 glass-panel py-2 rounded-xl">
            <div>ደራሽ (POT): <span class="text-emerald-400 font-black text-sm" id="derash-amount">0 ETB</span></div>
            <div>የወጡ ኳሶች: <span id="game-balls-count" class="font-black text-purple-400">0/75</span></div>
        </div>

        <div class="flex gap-2">
            <div class="w-1/3 glass-panel rounded-2xl p-2">
                <div class="grid grid-cols-5 text-center text-[10px] text-purple-400 font-black mb-1">
                    <div>B</div><div>I</div><div>N</div><div>G</div><div>O</div>
                </div>
                <div id="bingo-75-grid" class="grid grid-cols-5 gap-1 text-center text-[9px]">
                </div>
            </div>

            <div class="w-2/3 flex flex-col items-center">
                <div id="current-ball" class="w-20 h-20 rounded-full ball-gradient flex items-center justify-center text-xl font-black shadow-2xl border-4 border-purple-300/60 mb-3 animate-bounce">
                    READY
                </div>
                <div id="my-cards-container" class="w-full space-y-3">
                </div>
            </div>
        </div>
    </div>

    <!-- Winner Modal Popup -->
    <div id="winner-modal" class="fixed inset-0 bg-black/85 backdrop-blur-md flex items-center justify-center p-4 hidden z-50">
        <div class="glass-panel text-white rounded-3xl p-5 w-full max-w-sm text-center shadow-2xl relative border-2 border-amber-400">
            <div class="absolute -top-6 left-1/2 transform -translate-x-1/2 bg-amber-500 text-slate-900 font-black px-4 py-1 rounded-full text-xs shadow-lg">
                🏆 አሸናፊ ወጣ!
            </div>
            <div id="winner-name" class="text-2xl font-black text-amber-400 italic mt-3 mb-1">Winner</div>
            
            <div class="bg-slate-900/80 rounded-2xl p-3 mb-3 border border-amber-500/30">
                <div class="text-[10px] text-gray-400 font-bold">የተወሰደው ደራሽ (PRIZE)</div>
                <div id="winner-prize" class="text-2xl font-black text-emerald-400">0 ETB</div>
            </div>

            <div class="text-left font-bold text-purple-300 text-xs mb-1" id="winner-card-title">CARD #--</div>
            
            <div class="grid grid-cols-5 text-center text-amber-400 font-black text-xs mb-1">
                <div>B</div><div>I</div><div>N</div><div>G</div><div>O</div>
            </div>
            <div id="winner-card-matrix" class="grid grid-cols-5 gap-1 bg-slate-900/90 p-2 rounded-2xl text-center text-xs font-bold mb-4">
            </div>

            <div class="text-[10px] text-gray-400 mt-2 font-bold">አዲስ ዙር በሰከንዶች ውስጥ ይጀምራል...</div>
        </div>
    </div>

    <script>
        const socket = io();
        let userId = null;

        if (window.Telegram && window.Telegram.WebApp) {
            window.Telegram.WebApp.ready();
            window.Telegram.WebApp.expand();
            if (window.Telegram.WebApp.initDataUnsafe && window.Telegram.WebApp.initDataUnsafe.user) {
                userId = window.Telegram.WebApp.initDataUnsafe.user.id;
            }
        }

        if (!userId) {
            const urlParams = new URLSearchParams(window.location.search);
            userId = parseInt(urlParams.get('user_id')) || 12345;
        }

        let mySelectedCards = [];
        let drawnNumbersSet = new Set();

        socket.emit('get_user_balance', { user_id: userId });

        socket.on('balance_update', (data) => {
            if(data.user_id === userId) {
                document.getElementById('user-balance-disp').innerText = `${data.balance.toFixed(2)} ETB`;
            }
        });

        function initCartelaGrid() {
            const gridContainer = document.getElementById('cartela-grid');
            gridContainer.innerHTML = '';
            for (let i = 1; i <= 104; i++) {
                const btn = document.createElement('button');
                const isSelected = mySelectedCards.includes(i);
                
                btn.className = `p-1.5 text-xs font-bold rounded-lg border text-center ${isSelected ? 'bg-emerald-500 text-white border-emerald-600 font-black' : 'bg-slate-50 text-slate-800 border-slate-200'}`;
                btn.innerText = i;
                btn.onclick = () => selectCard(i);
                gridContainer.appendChild(btn);
            }
        }

        function selectCard(cardId) {
            if (mySelectedCards.includes(cardId)) return;
            if (mySelectedCards.length >= 2) {
                alert("⚠️ በአንድ ዙር ከ 2 ካርቴላ በላይ መያዝ አይቻልም!");
                return;
            }
            socket.emit('select_card', { user_id: userId, card_id: cardId });
        }

        socket.on('card_confirmed', (data) => {
            if(!mySelectedCards.includes(data.card_id)) {
                mySelectedCards.push(data.card_id);
            }
            initCartelaGrid();
            renderSelectionPreviews();
            document.getElementById('user-balance-disp').innerText = `${data.new_balance.toFixed(2)} ETB`;
        });

        function renderSelectionPreviews() {
            const container = document.getElementById('preview-cards-container');
            container.innerHTML = '';
            mySelectedCards.forEach(cardId => {
                socket.emit('get_preview_matrix', { card_id: cardId });
            });
        }

        socket.on('receive_preview_matrix', (data) => {
            const container = document.getElementById('preview-cards-container');
            const cardBox = document.createElement('div');
            cardBox.className = 'bg-white rounded-xl p-2 text-slate-900 border-2 border-blue-500 shadow';

            let html = `<div class="text-xs font-black text-blue-600 mb-1">#${data.card_id}</div>`;
            
            html += `<div class="grid grid-cols-5 text-center text-[10px] font-black text-white mb-1">
                        <div class="bg-blue-600 rounded-s">B</div>
                        <div class="bg-red-600">I</div>
                        <div class="bg-amber-500">N</div>
                        <div class="bg-emerald-600">G</div>
                        <div class="bg-purple-600 rounded-e">O</div>
                     </div>`;
            
            html += `<div class="grid grid-cols-5 gap-0.5 text-center text-[10px] font-bold">`;
            data.matrix.forEach(row => {
                row.forEach(val => {
                    html += `<div class="p-1 border border-slate-100 rounded ${val === 'FREE' ? 'bg-emerald-500 text-white' : 'bg-slate-50 text-slate-800'}">${val === 'FREE' ? '★' : val}</div>`;
                });
            });
            html += `</div>`;
            
            html += `<button class="w-full mt-2 bg-blue-600 text-white font-black text-[10px] py-1 rounded-lg">BINGO!</button>`;

            cardBox.innerHTML = html;
            container.appendChild(cardBox);
        });

        socket.on('error_msg', (data) => {
            alert(data.msg);
        });

        function init75Board() {
            const board75 = document.getElementById('bingo-75-grid');
            board75.innerHTML = '';
            
            for (let row = 0; row < 15; row++) {
                for (let col = 0; col < 5; col++) {
                    const num = (col * 15) + row + 1;
                    const cell = document.createElement('div');
                    cell.id = `ball-cell-${num}`;
                    cell.className = 'p-1 rounded bg-slate-800 text-gray-400 font-semibold';
                    cell.innerText = num;
                    board75.appendChild(cell);
                }
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
            document.getElementById('balls-count').innerText = data.drawn_list.length;
            document.getElementById('game-balls-count').innerText = `${data.drawn_list.length}/75`;
            
            const cell = document.getElementById(`ball-cell-${data.number}`);
            if(cell) {
                cell.className = 'p-1 rounded bg-emerald-500 text-white font-black animate-pulse shadow';
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
                    div.className = `p-1.5 rounded-lg ${isHit ? 'bg-emerald-500 text-white font-bold' : 'bg-slate-800 text-gray-300'}`;
                    div.innerText = val === 'FREE' ? '★' : val;
                    matrixContainer.appendChild(div);
                });
            });

            document.getElementById('winner-modal').classList.remove('hidden');
            socket.emit('get_user_balance', { user_id: userId });
        });

        socket.on('reset_game', () => {
            mySelectedCards = [];
            drawnNumbersSet.clear();
            document.getElementById('winner-modal').classList.add('hidden');
            document.getElementById('game-screen').classList.add('hidden');
            document.getElementById('selection-screen').classList.remove('hidden');
            document.getElementById('sold-count').innerText = '0';
            document.getElementById('preview-cards-container').innerHTML = '';
            initCartelaGrid();
            socket.emit('get_user_balance', { user_id: userId });
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
            cardDiv.className = 'bg-white rounded-2xl p-2.5 shadow-xl text-slate-900 border-2 border-blue-500';
            
            let html = `<div class="flex justify-between items-center text-xs font-bold text-blue-600 mb-2"><span>CARD #${data.card_id}</span><span class="text-[9px] bg-blue-100 text-blue-800 px-1.5 py-0.5 rounded-full">LIVE</span></div>`;
            
            html += `<div class="grid grid-cols-5 text-center text-white font-black text-xs mb-1">
                        <div class="bg-blue-600 rounded-s">B</div>
                        <div class="bg-red-600">I</div>
                        <div class="bg-amber-500">N</div>
                        <div class="bg-emerald-600">G</div>
                        <div class="bg-purple-600 rounded-e">O</div>
                     </div>`;
            
            html += `<div class="grid grid-cols-5 gap-1 text-center font-bold text-xs">`;
            
            data.matrix.forEach(row => {
                row.forEach(val => {
                    const isHit = val === 'FREE' || drawnNumbersSet.has(val);
                    html += `<div class="p-1.5 rounded-lg border border-slate-100 transition-colors ${isHit ? 'bg-emerald-500 text-white font-black shadow-md' : 'bg-slate-50 text-slate-800'}">${val === 'FREE' ? '★' : val}</div>`;
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
        "⚠️ **ህግ:** ጨዋታ ለመጫወት ቢያንስ **10 ETB** ዲፖዚት ማድረግ ይኖርብዎታል!"
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

# ---------------------------------------------------------
# 📤 ADVANCED WITHDRAWAL SYSTEM (ደረጃ በደረጃ የሚሰራ ዊዝድሮው)
# ---------------------------------------------------------
@bot.message_handler(func=lambda m: m.text and "ዊዝድሮው" in m.text)
def withdraw_cmd(message):
    uid = message.from_user.id
    bal = user_balances.get(uid, 0.0)

    if bal < MIN_WITHDRAWAL:
        bot.send_message(
            message.chat.id, 
            f"❌ **ዝቅተኛው የዊዝድሮው መጠን {MIN_WITHDRAWAL:.2f} ETB ነው።**\n\n"
            f"💳 የእርስዎ ወቅታዊ ባላንስ: **{bal:.2f} ETB**",
            parse_mode="Markdown"
        )
        return

    # ደረጃ 1፦ የክፍያ አማራጭ ማስመረጥ (Buttons)
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📱 Telebirr", callback_data="wdmeth_Telebirr"),
        InlineKeyboardButton("🏦 CBE Birr", callback_data="wdmeth_CBE_Birr")
    )

    bot.send_message(
        message.chat.id,
        f"📤 **ገንዘብ ማውጫ (Withdrawal)**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 የእርስዎ ወቅታዊ ባላንስ: **{bal:.2f} ETB**\n\n"
        f"እባክዎን ገንዘብ መቀበል የሚፈልጉበትን **የክፍያ አማራጭ** ይምረጡ፦",
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('wdmeth_'))
def handle_withdraw_method_selection(call):
    uid = call.from_user.id
    method = call.data.split('_', 1)[1].replace('_', ' ')
    
    withdraw_data[uid] = {'method': method}
    user_states[uid] = "WAITING_WITHDRAW_ACCOUNT"

    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        f"✅ የተመረጠው አማራጭ፦ **{method}**\n\n"
        f"📌 እባክዎን ገንዘቡ የሚላክበትን **የስልክ ቁጥር** ወይም **የአካውንት ቁጥር** ያስገቡ፦",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "WAITING_WITHDRAW_ACCOUNT")
def handle_withdraw_account(message):
    uid = message.from_user.id
    account_num = message.text.strip()

    withdraw_data[uid]['account'] = account_num
    user_states[uid] = "WAITING_WITHDRAW_AMOUNT"

    bal = user_balances.get(uid, 0.0)
    
    bot.send_message(
        message.chat.id,
        f"✅ አድራሻ አካውንት: `{account_num}`\n\n"
        f"💵 እባክዎን ማውጣት የሚፈልጉትን **የብር መጠን** ያስገቡ፦\n"
        f"(ዝቅተኛው: **{MIN_WITHDRAWAL:.2f} ETB** | ባላንስዎ: **{bal:.2f} ETB**)",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "WAITING_WITHDRAW_AMOUNT")
def handle_withdraw_amount(message):
    uid = message.from_user.id
    bal = user_balances.get(uid, 0.0)
    
    try:
        req_amount = float(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "⚠️ **እባክዎን ትክክለኛ የቁጥር መጠን ብቻ ያስገቡ!** (ምሳሌ፦ 100)")
        return

    if req_amount < MIN_WITHDRAWAL:
        bot.send_message(message.chat.id, f"❌ **ዝቅተኛው ማውጣት የሚችሉት የብር መጠን {MIN_WITHDRAWAL:.2f} ETB ነው።**")
        return

    if req_amount > bal:
        bot.send_message(message.chat.id, f"❌ **የጠየቁት የብር መጠን ከባላንስዎ ይበልጣል!**\nየእርስዎ ባላንስ: **{bal:.2f} ETB**", parse_mode="Markdown")
        return

    method = withdraw_data[uid].get('method', 'Telebirr')
    account = withdraw_data[uid].get('account', 'Unknown')

    user_states[uid] = None
    wd_id = f"WD_{int(time.time())}_{uid}"

    # ለአድሚን የሚላክ Button
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton(f"✅ Approve {req_amount:.2f} ETB", callback_data=f"wdapp_{req_amount}_{uid}_{wd_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"wdrej_{uid}_{wd_id}")
    )

    admin_msg = (
        f"📤 **አዲስ የዊዝድሮው ጥያቄ!**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 ተጫዋች: {message.from_user.first_name} (`{uid}`)\n"
        f"🏦 አማራጭ: **{method}**\n"
        f"💳 አድራሻ አካውንት: `{account}`\n"
        f"💵 የተጠየቀው መጠን: **{req_amount:.2f} ETB**\n"
        f"💰 ወቅታዊ ባላንስ: **{bal:.2f} ETB**"
    )

    try:
        bot.send_message(ADMIN_ID, admin_msg, reply_markup=markup, parse_mode="Markdown")
        
        # ለተጫዋቹ የሚላክ የትግስቱ መልእክት
        bot.send_message(
            message.chat.id, 
            f"⏳ **የዊዝድሮው ጥያቄዎ በተሳካ ሁኔታ ተልኳል!**\n\n"
            f"🏦 አማራጭ፦ **{method}**\n"
            f"💳 አድራሻ አካውንት፦ `{account}`\n"
            f"💵 የተጠየቀው መጠን፦ **{req_amount:.2f} ETB**\n\n"
            f"ℹ️ *እስኪረጋገጥ ድረስ ጥቂት ደቂቃዎችን በትዕግስት ይጠብቁ...*",
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.send_message(message.chat.id, "❌ ጥያቄውን ማስተናገድ አልተቻለም። እባክዎን በኋላ ደግመው ይሞክሩ።")

# ---------------------------------------------------------
# 🎛 ADMIN CALLBACK HANDLERS (DEPOSIT & WITHDRAW APPROVALS)
# ---------------------------------------------------------
@bot.callback_query_handler(func=lambda call: call.data.startswith(('app_', 'rej_', 'wdapp_', 'wdrej_')))
def handle_admin_approval(call):
    parts = call.data.split('_')
    action = parts[0]
    
    # 1. DEPOSIT REJECT
    if action == "rej":
        target_uid = int(parts[1])
        bot.answer_callback_query(call.id, "ዲፖዚቱ ተሰርዟል!")
        bot.edit_message_text(f"❌ **Deposit Rejected** for User `{target_uid}`", call.message.chat.id, call.message.message_id)
        bot.send_message(target_uid, "❌ **የዲፖዚት ጥያቄዎ አልተቀበለም!**")
    
    # 2. DEPOSIT APPROVE
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

    # 3. WITHDRAW REJECT
    elif action == "wdrej":
        target_uid = int(parts[1])
        bot.answer_callback_query(call.id, "ዊዝድሮው ተሰርዟል!")
        bot.edit_message_text(f"❌ **Withdrawal Rejected** for User `{target_uid}`", call.message.chat.id, call.message.message_id)
        bot.send_message(target_uid, "❌ **የዊዝድሮው ጥያቄዎ አልተቀበለም!** ተጨማሪ መረጃ ካስፈለገ አድሚኑን ያናግሩ።")

    # 4. WITHDRAW APPROVE
    elif action == "wdapp":
        amount_val = float(parts[1])
        target_uid = int(parts[2])
        current_bal = user_balances.get(target_uid, 0.0)

        if current_bal < amount_val:
            bot.answer_callback_query(call.id, "⚠️ ተጫዋቹ በቂ ባላንስ የለውም!", show_alert=True)
            return

        user_balances[target_uid] -= amount_val
        new_bal = user_balances[target_uid]

        bot.answer_callback_query(call.id, f"{amount_val} ETB ዊዝድሮው ፀድቋል!")
        bot.edit_message_text(
            f"✅ **Withdrawal Approved & Paid!**\n"
            f"User: `{target_uid}`\n"
            f"Amount Paid: **-{amount_val:.2f} ETB**\n"
            f"Remaining Balance: **{new_bal:.2f} ETB**", 
            call.message.chat.id, 
            call.message.message_id
        )
        
        # ለአሸናፊው/ተጫዋቹ የሚላከው የመጨረሻ የማረጋገጫ መልእክት
        bot.send_message(
            target_uid, 
            f"🎉 **ዊዝድሮው በተሳካ ሁኔታ ተቀባይነት አግኝቷል!**\n\n"
            f"💸 የተከፈለዎት መጠን: **{amount_val:.2f} ETB**\n"
            f"💰 የቀረው ባላንስዎ: **{new_bal:.2f} ETB**\n\n"
            f"ገንዘቡ በተላከበት የክፍያ አካውንት ገቢ ተደርጎልዎታል። እናመሰግናለን! 🙏",
            reply_markup=main_menu_keyboard(target_uid),
            parse_mode="Markdown"
        )

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
        "2. በአንድ ዙር ቢበዛ **2 ካርቴላ** ብቻ መያዝ ይቻላል።\n"
        "3. አሸናፊው ከጠቅላላው የካርቴላ ሽያጭ 10% የቦት ኮሚሽን ተቀንሶ **ደራሹን በሙሉ** ይወስዳል።\n"
        "4. ዝቅተኛው የወጪ (Withdrawal) መጠን **50 ETB** ነው።"
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
@socketio.on('get_user_balance')
def handle_get_balance(data):
    uid = int(data.get('user_id'))
    bal = user_balances.get(uid, 0.0)
    emit('balance_update', {'user_id': uid, 'balance': bal})

@socketio.on('select_card')
def handle_card_selection(data):
    uid = int(data.get('user_id'))
    card_id = int(data.get('card_id'))

    if game_state['status'] not in ['WAITING', 'COUNTDOWN']:
        emit('error_msg', {'msg': 'ጨዋታ ተጀምሯል! እባክዎን አዲስ ዙር ይበቁ።'})
        return

    current_player_cards = game_state['player_cards'].get(uid, [])
    if len(current_player_cards) >= MAX_CARDS_PER_PLAYER:
        emit('error_msg', {'msg': '⚠️ በአንድ ዙር ከ 2 ካርቴላ በላይ መያዝ አይቻልም!'})
        return

    bal = user_balances.get(uid, 0.0)
    if bal < CARD_PRICE:
        emit('error_msg', {'msg': f'በቂ ባላንስ የሎትም። እባክዎን በቦቱ ዲፖዚት ያድርጉ! (ባላንስዎ: {bal:.2f} ETB)'})
        return

    if card_id in game_state['selected_cards']:
        emit('error_msg', {'msg': 'ይህ ካርቴላ በተခြား ተጫዋች ተይዟል!'})
        return

    user_balances[uid] -= CARD_PRICE
    new_bal = user_balances[uid]

    game_state['selected_cards'][card_id] = uid
    if uid not in game_state['player_cards']:
        game_state['player_cards'][uid] = []
    game_state['player_cards'][uid].append(card_id)

    total_pool = len(game_state['selected_cards']) * CARD_PRICE
    game_state['derash'] = round(total_pool * (1 - COMMISSION_RATE), 2)

    emit('card_confirmed', {'card_id': card_id, 'new_balance': new_bal}, broadcast=False)
    socketio.emit('game_update', game_state)

@socketio.on('get_preview_matrix')
def handle_preview_matrix(data):
    c_id = int(data.get('card_id'))
    if c_id in cards_database:
        emit('receive_preview_matrix', {'card_id': c_id, 'matrix': cards_database[c_id]})

@socketio.on('get_card_matrix')
def handle_get_matrix(data):
    c_id = int(data.get('card_id'))
    if c_id in cards_database:
        emit('receive_card_matrix', {'card_id': c_id, 'matrix': cards_database[c_id]})

def game_loop():
    global game_state
    while True:
        game_state["status"] = "WAITING"
        game_state["drawn_numbers"] = []
        game_state["selected_cards"] = {}
        game_state["player_cards"] = {}
        game_state["derash"] = 0.0

        socketio.emit('reset_game')

        while len(game_state["selected_cards"]) == 0:
            socketio.sleep(1)

        game_state["status"] = "COUNTDOWN"
        for t in range(15, 0, -1):
            game_state["time_left"] = t
            socketio.emit('timer_update', {'time_left': t, 'status': 'COUNTDOWN'})
            socketio.sleep(1)

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

            for uid, cards in game_state["player_cards"].items():
                for card_id in cards:
                    matrix = cards_database[card_id]
                    if check_bingo_winner(matrix, drawn_set):
                        winner_found = True
                        prize = game_state["derash"]

                        user_balances[uid] = user_balances.get(uid, 0.0) + prize
                        
                        socketio.emit('winner_announced', {
                            "winner_name": f"User_{uid}",
                            "prize": prize,
                            "card_num": card_id,
                            "card_matrix": matrix
                        })

                        try:
                            bot.send_message(
                                uid,
                                f"🎉 **እንኳን ደስ አለዎት! ሎተሪው ደርሶዎታል!** 🏆\n\n"
                                f"🃏 ያሸነፉበት ካርቴላ: **#{card_id}**\n"
                                f"💰 ያሸነፉት ደራሽ: **+{prize:.2f} ETB**\n"
                                f"💳 አዲሱ ባላንስዎ: **{user_balances[uid]:.2f} ETB**",
                                parse_mode="Markdown"
                            )
                        except Exception as e:
                            print(f"Winner Bot Message Failed: {e}")

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
