import os
import re
import random
import time
from threading import Thread
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
)

# =========================================================
# 1. SETUP & CONFIGURATION
# =========================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'bkbingo_secret_key_2026'
socketio = SocketIO(app, cors_allowed_origins="*")

# BOT TOKENS
MAIN_BOT_TOKEN = os.environ.get("BOT_TOKEN", "8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM")
SUPPORT_BOT_TOKEN = os.environ.get("SUPPORT_BOT_TOKEN", "8912812512:AAHL9OPDgGNa2QS9YHqY5c6KDKuB7OlF-3M")

bot = telebot.TeleBot(MAIN_BOT_TOKEN)
support_bot = telebot.TeleBot(SUPPORT_BOT_TOKEN)

RENDER_WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://bingo-bot-c90r.onrender.com")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "855985673"))

CARD_PRICE = 10.0
COMMISSION_RATE = 0.10  # 10% የቦት ኮሚሽን
MAX_CARDS_PER_PLAYER = 2 
MIN_WITHDRAWAL = 50.0   

# DATABASE & USER STATES
users_db = {}            
user_states = {}         
deposit_data = {}        
withdraw_data = {}       
admin_reply_state = {}   
used_txn_ids = set()     

# =========================================================
# 2. BINGO CARDS DATABASE (1-104 CARDS)
# =========================================================
cards_database = {}

def generate_official_bingo_card(card_id):
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
    "status": "WAITING",
    "time_left": 15,
    "drawn_numbers": [],
    "selected_cards": {},  # card_id -> user_id
    "player_cards": {},    # user_id -> [card_ids]
    "derash": 0.0
}

def check_bingo_winner(matrix, drawn_set):
    def is_hit(val):
        return val == 'FREE' or val in drawn_set

    # 1. Horizontal Rows
    for row in matrix:
        if all(is_hit(v) for v in row): return True
    # 2. Vertical Columns
    for col in range(5):
        if all(is_hit(matrix[row][col]) for row in range(5)): return True
    # 3. Diagonals
    d1 = [matrix[i][i] for i in range(5)]
    d2 = [matrix[i][4-i] for i in range(5)]
    if all(is_hit(v) for v in d1) or all(is_hit(v) for v in d2): return True

    return False

# =========================================================
# 4. FRONTEND HTML TEMPLATE (BKBINGO PRO UI + REALTIME BALANCE)
# =========================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="am">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>BKBINGO Pro</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Poppins:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        body { 
            font-family: 'Poppins', sans-serif; 
            background: linear-gradient(135deg, #0f172a 0%, #020617 100%);
            color: #fff; 
            min-height: 100vh; 
        }
        .font-orbitron { font-family: 'Orbitron', sans-serif; }
        .glass-panel { 
            background: rgba(30, 41, 59, 0.7); 
            backdrop-filter: blur(16px); 
            border: 1px solid rgba(255, 255, 255, 0.1); 
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }
        .gold-gradient-text { 
            background: linear-gradient(135deg, #fef08a 0%, #facc15 50%, #ca8a04 100%); 
            -webkit-background-clip: text; 
            -webkit-text-fill-color: transparent; 
        }
        .ball-glow { 
            background: radial-gradient(circle at 30% 30%, #a855f7 0%, #6b21a8 60%, #3b0764 100%);
            box-shadow: 0 0 25px rgba(168, 85, 247, 0.6);
        }
        .card-btn-selected { 
            background: linear-gradient(135deg, #10b981 0%, #047857 100%) !important; 
            color: #ffffff !important; 
            border-color: #34d399 !important;
            box-shadow: 0 0 12px rgba(16, 185, 129, 0.5);
        }
        .bingo-hit { 
            background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important; 
            color: #ffffff !important; 
            font-weight: 800 !important;
            box-shadow: inset 0 0 6px rgba(255, 255, 255, 0.6);
        }
        .bingo-header-b { background: #ef4444; color: #fff; }
        .bingo-header-i { background: #3b82f6; color: #fff; }
        .bingo-header-n { background: #eab308; color: #000; }
        .bingo-header-g { background: #10b981; color: #fff; }
        .bingo-header-o { background: #a855f7; color: #fff; }
    </style>
</head>
<body class="select-none pb-10 px-3">
    <!-- HEADER -->
    <div class="relative overflow-hidden rounded-2xl mt-2 mb-3 border border-purple-500/30 glass-panel">
        <div class="p-3.5 flex justify-between items-center">
            <div class="flex items-center gap-2">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-purple-600 to-amber-400 flex items-center justify-center font-black text-xl shadow-lg">🎯</div>
                <div>
                    <h1 class="font-orbitron text-lg font-black gold-gradient-text tracking-wider">BKBINGO PRO</h1>
                    <p class="text-[10px] text-purple-300/80">LIVE CASINO BINGO</p>
                </div>
            </div>
            <div class="bg-emerald-500/20 border border-emerald-500/40 px-3 py-1 rounded-xl text-right">
                <div class="text-[9px] text-emerald-300 font-bold">ሒሳብ (BAL)</div>
                <div id="user-balance-disp" class="text-xs font-black text-emerald-400">0.00 ETB</div>
            </div>
        </div>
    </div>

    <!-- STATS BAR -->
    <div class="grid grid-cols-3 gap-2 mb-3 text-center text-xs font-bold">
        <div class="glass-panel rounded-xl p-2 border-l-4 border-amber-400">
            <span class="text-[9px] text-slate-400 block mb-0.5">የተሸጡ ካርቴላዎች</span>
            <span id="sold-count" class="text-amber-400 text-sm font-black">0</span>
        </div>
        <div class="glass-panel rounded-xl p-2 border-l-4 border-rose-500">
            <span class="text-[9px] text-slate-400 block mb-0.5">የቀረ ጊዜ</span>
            <span id="timer" class="text-rose-400 text-sm font-black">15s</span>
        </div>
        <div class="glass-panel rounded-xl p-2 border-l-4 border-purple-500">
            <span class="text-[9px] text-slate-400 block mb-0.5">የወጡ ኳሶች</span>
            <span id="balls-count" class="text-purple-300 text-sm font-black">0/75</span>
        </div>
    </div>

    <!-- CARD SELECTION SCREEN -->
    <div id="selection-screen">
        <div class="flex justify-between items-center mb-2 px-1">
            <span class="text-xs font-bold text-slate-300">ካርቴላ ይምረጡ (1-104)</span>
            <span class="text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full border border-amber-500/20">ዋጋ: 10 ETB</span>
        </div>

        <div id="cartela-grid" class="grid grid-cols-8 gap-1.5 glass-panel p-3 rounded-2xl max-h-[38vh] overflow-y-auto border border-slate-800"></div>
        <p class="text-center text-[10px] text-slate-400 my-2">⚠️ በአንድ ዙር መግዛት የሚችሉት ቢበዛ 2 ካርቴላዎች ብቻ ነው።</p>
        
        <div id="preview-cards-container" class="grid grid-cols-2 gap-2 mt-2"></div>
    </div>

    <!-- MAIN GAMEPLAY SCREEN -->
    <div id="game-screen" class="hidden mt-2">
        <div class="glass-panel p-3 rounded-2xl mb-3 flex justify-between items-center border border-emerald-500/30">
            <div>
                <span class="text-[10px] text-slate-400 block">የአሸናፊው ደራሽ (PRIZE)</span>
                <span class="text-lg font-black text-emerald-400" id="derash-amount">0 ETB</span>
            </div>
            <div class="text-right">
                <span class="text-[10px] text-slate-400 block">የተጠራው ኳስ</span>
                <span id="game-balls-count" class="text-xs font-bold text-purple-300">0/75</span>
            </div>
        </div>

        <div class="flex gap-2">
            <!-- 1-75 BOARD -->
            <div class="w-1/3 glass-panel rounded-2xl p-2 border border-slate-800">
                <div class="text-[9px] font-bold text-center text-slate-400 mb-1">የወጡ ቁጥሮች</div>
                <div id="bingo-75-grid" class="grid grid-cols-5 gap-1 text-center text-[9px]"></div>
            </div>

            <!-- BALL DISPLAY & PLAYER CARDS -->
            <div class="w-2/3 flex flex-col items-center">
                <div id="current-ball" class="w-20 h-20 rounded-full ball-glow flex items-center justify-center text-2xl font-black mb-3 border-2 border-purple-300/50 transform transition-all duration-300">
                    READY
                </div>
                <div id="my-cards-container" class="w-full space-y-3"></div>
            </div>
        </div>
    </div>

    <!-- WINNER MODAL -->
    <div id="winner-modal" class="fixed inset-0 bg-slate-950/90 backdrop-blur-md flex items-center justify-center p-4 hidden z-50">
        <div class="glass-panel text-white rounded-3xl p-5 w-full max-w-sm text-center border-2 border-amber-400 shadow-2xl">
            <div class="text-4xl mb-1">🎉</div>
            <div class="text-lg font-black gold-gradient-text" id="winner-name">Winner</div>
            <div id="winner-prize" class="text-3xl font-black text-emerald-400 my-2">0 ETB</div>
            
            <div class="text-[11px] font-bold text-slate-300 mt-3 mb-1">የአሸናፊው ካርቴላ</div>
            <div id="winner-card-matrix" class="glass-panel p-2 rounded-2xl my-2 border border-slate-700"></div>
            <div class="text-[10px] text-slate-400 mt-3">አዲስ ዙር በቅርቡ ይጀምራል...</div>
        </div>
    </div>

    <script>
        const socket = io();
        let userId = null;

        // FETCH TELEGRAM USER ID ACCURATELY
        if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initDataUnsafe && window.Telegram.WebApp.initDataUnsafe.user) {
            userId = parseInt(window.Telegram.WebApp.initDataUnsafe.user.id);
        } else {
            const urlParams = new URLSearchParams(window.location.search);
            userId = parseInt(urlParams.get('user_id')) || 12345;
        }

        let mySelectedCards = [];
        let drawnNumbersSet = new Set();
        let cardsDatabase = {};

        socket.on('connect', () => {
            if (userId) {
                socket.emit('get_user_balance', { user_id: userId });
            }
        });

        socket.on('balance_update', (data) => {
            if(parseInt(data.user_id) === userId) {
                document.getElementById('user-balance-disp').innerText = `${parseFloat(data.balance).toFixed(2)} ETB`;
            }
        });

        socket.on('error_msg', (data) => {
            alert("⚠️ " + data.msg);
        });

        function init75Grid() {
            const grid = document.getElementById('bingo-75-grid');
            grid.innerHTML = '';
            for(let i=1; i<=75; i++) {
                const cell = document.createElement('div');
                cell.id = `ball-cell-${i}`;
                cell.className = 'p-1 bg-slate-800/80 rounded text-slate-400 font-bold';
                cell.innerText = i;
                grid.appendChild(cell);
            }
        }

        function initCartelaGrid() {
            const gridContainer = document.getElementById('cartela-grid');
            gridContainer.innerHTML = '';
            for (let i = 1; i <= 104; i++) {
                const btn = document.createElement('button');
                const isSelected = mySelectedCards.includes(i);
                btn.className = `p-2 text-xs font-black rounded-xl border transition-all ${isSelected ? 'card-btn-selected' : 'bg-slate-800/80 text-slate-200 border-slate-700/60 active:scale-95'}`;
                btn.innerText = i;
                btn.onclick = () => {
                    if (mySelectedCards.length >= 2 && !isSelected) return alert("⚠️ በአንድ ዙር ቢበዛ 2 ካርቴላ ብቻ መግዛት ይቻላል!");
                    socket.emit('select_card', { user_id: userId, card_id: i });
                };
                gridContainer.appendChild(btn);
            }
        }

        socket.on('card_confirmed', (data) => {
            if(!mySelectedCards.includes(data.card_id)) mySelectedCards.push(data.card_id);
            cardsDatabase[data.card_id] = data.matrix;
            initCartelaGrid();
            renderPreviewCards();
            document.getElementById('user-balance-disp').innerText = `${parseFloat(data.new_balance).toFixed(2)} ETB`;
        });

        function createCardHTML(cid, matrix, isPlayMode = false) {
            const cardDiv = document.createElement('div');
            cardDiv.className = 'glass-panel p-2 rounded-2xl w-full border border-slate-700/80';
            cardDiv.innerHTML = `<div class="text-[11px] font-black text-amber-400 mb-1.5 text-center">ካርቴላ #${cid}</div>`;

            const mGrid = document.createElement('div');
            mGrid.className = 'grid grid-cols-5 gap-1 text-center font-bold text-xs bg-slate-950/80 p-1.5 rounded-xl';

            const headers = [
                { title: 'B', class: 'bingo-header-b' },
                { title: 'I', class: 'bingo-header-i' },
                { title: 'N', class: 'bingo-header-n' },
                { title: 'G', class: 'bingo-header-g' },
                { title: 'O', class: 'bingo-header-o' }
            ];

            headers.forEach(h => {
                const hCell = document.createElement('div');
                hCell.className = `p-1 rounded-lg font-black text-[10px] ${h.class}`;
                hCell.innerText = h.title;
                mGrid.appendChild(hCell);
            });

            matrix.forEach(row => {
                row.forEach(val => {
                    const cell = document.createElement('div');
                    if(isPlayMode) cell.id = `card-${cid}-val-${val}`;
                    
                    const isHit = val === 'FREE' || drawnNumbersSet.has(val);
                    const isFree = val === 'FREE';

                    cell.className = `p-1.5 rounded-lg text-[10px] font-bold ${
                        isFree 
                        ? 'bg-amber-500 text-slate-950 font-black' 
                        : (isHit ? 'bingo-hit' : 'bg-slate-800/90 text-slate-200')
                    }`;
                    cell.innerText = val;
                    mGrid.appendChild(cell);
                });
            });

            cardDiv.appendChild(mGrid);
            return cardDiv;
        }

        function renderPreviewCards() {
            const container = document.getElementById('preview-cards-container');
            container.innerHTML = '';
            mySelectedCards.forEach(cid => {
                const matrix = cardsDatabase[cid];
                if(!matrix) return;
                container.appendChild(createCardHTML(cid, matrix, false));
            });
        }

        socket.on('timer_update', (data) => {
            document.getElementById('timer').innerText = `${data.time_left}s`;
            document.getElementById('sold-count').innerText = data.sold_count;
        });

        socket.on('game_started', (data) => {
            drawnNumbersSet.clear();
            init75Grid();
            document.getElementById('selection-screen').classList.add('hidden');
            document.getElementById('game-screen').classList.remove('hidden');
            document.getElementById('derash-amount').innerText = `${parseFloat(data.derash).toFixed(2)} ETB`;
            renderMyGameCards();
        });

        function renderMyGameCards() {
            const container = document.getElementById('my-cards-container');
            container.innerHTML = '';
            mySelectedCards.forEach(cid => {
                const matrix = cardsDatabase[cid];
                if(!matrix) return;
                container.appendChild(createCardHTML(cid, matrix, true));
            });
        }

        socket.on('new_number', (data) => {
            const ball = data.ball;
            drawnNumbersSet.add(ball);
            
            const ballEl = document.getElementById('current-ball');
            ballEl.innerText = ball;
            ballEl.classList.add('scale-110');
            setTimeout(() => ballEl.classList.remove('scale-110'), 200);

            document.getElementById('game-balls-count').innerText = `${drawnNumbersSet.size}/75`;
            
            const cell75 = document.getElementById(`ball-cell-${ball}`);
            if(cell75) {
                cell75.className = 'p-1 bg-amber-400 text-slate-950 font-black rounded shadow-lg scale-105 transition-all';
            }

            mySelectedCards.forEach(cid => {
                const hitCell = document.getElementById(`card-${cid}-val-${ball}`);
                if(hitCell) {
                    hitCell.className = 'p-1.5 rounded-lg text-[10px] font-bold bingo-hit scale-105 transition-all';
                }
            });
        });

        socket.on('winner_announced', (data) => {
            document.getElementById('winner-name').innerText = `${data.winner_name} አሸንፏል!`;
            document.getElementById('winner-prize').innerText = `${parseFloat(data.prize).toFixed(2)} ETB`;
            
            if(parseInt(data.winner_id) === userId) {
                socket.emit('get_user_balance', { user_id: userId });
            }

            const wGrid = document.getElementById('winner-card-matrix');
            wGrid.innerHTML = '';
            if(data.card_matrix) {
                wGrid.appendChild(createCardHTML(data.card_id, data.card_matrix, false));
            }
            document.getElementById('winner-modal').classList.remove('hidden');
        });

        socket.on('reset_game', () => {
            mySelectedCards = [];
            drawnNumbersSet.clear();
            document.getElementById('winner-modal').classList.add('hidden');
            document.getElementById('game-screen').classList.add('hidden');
            document.getElementById('selection-screen').classList.remove('hidden');
            document.getElementById('preview-cards-container').innerHTML = '';
            initCartelaGrid();
            if(userId) socket.emit('get_user_balance', { user_id: userId });
        });

        initCartelaGrid();
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

# =========================================================
# 5. TELEGRAM MAIN BOT & USER REGISTRATION
# =========================================================
def main_menu_keyboard(user_id):
    markup = InlineKeyboardMarkup(row_width=2)
    app_url = f"{RENDER_WEBAPP_URL}?user_id={user_id}"
    
    user_bal = users_db.get(int(user_id), {}).get("balance", 0.0)
    support_deep_link = f"https://t.me/BkbingosupportBot?start=USER_{user_id}_BAL_{int(user_bal)}"

    markup.add(InlineKeyboardButton(text="🎲 ጨዋታ ጀምር (Open App)", web_app=WebAppInfo(url=app_url)))
    markup.add(
        InlineKeyboardButton(text="👤 ፕሮፋይል / ባላንስ", callback_data="btn_profile"),
        InlineKeyboardButton(text="📥 ዲፖዚት (Deposit)", callback_data="btn_deposit")
    )
    markup.add(
        InlineKeyboardButton(text="📤 ዊዝድሮው (Withdraw)", callback_data="btn_withdraw"),
        InlineKeyboardButton(text="👥 ሪፈራል / ግብዣ", callback_data="btn_referral")
    )
    markup.add(
        InlineKeyboardButton(text="ℹ️ እርዳታ እና ህጎች", callback_data="btn_help"),
        InlineKeyboardButton(text="🎧 የደንበኞች አገልግሎት", url=support_deep_link)
    )
    return markup

@bot.message_handler(commands=['start', 'menu'])
def start_cmd(message):
    uid = int(message.from_user.id)
    first_name = message.from_user.first_name
    username = message.from_user.username or "የለውም"

    if uid not in users_db:
        users_db[uid] = {
            "id": uid,
            "name": first_name,
            "username": username,
            "balance": 0.0
        }

    welcome_txt = (
        f"👋 ሰላም **{first_name}**!\n\n"
        f"ወደ **BKBINGO Pro** እንኳን ደህና መጡ! 🎲\n"
        f"💰 ባላንስዎ፦ **{users_db[uid]['balance']:.2f} ETB**\n\n"
        "ለመጫወት ከታች ያለውን **'🎲 ጨዋታ ጀምር'** የሚለውን ይጫኑ።"
    )
    bot.send_message(message.chat.id, welcome_txt, reply_markup=main_menu_keyboard(uid), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('btn_'))
def handle_main_menu_callbacks(call):
    uid = int(call.from_user.id)
    action = call.data
    bot.answer_callback_query(call.id)

    if uid not in users_db:
        users_db[uid] = {"id": uid, "name": call.from_user.first_name, "username": call.from_user.username or "የለውም", "balance": 0.0}

    bal = users_db[uid]["balance"]

    if action == "btn_profile":
        msg = f"👤 **የተጫዋች ፕሮፋይል**\n🆔 ID: `{uid}`\n💰 ባላንስ: **{bal:.2f} ETB**"
        bot.send_message(call.message.chat.id, msg, reply_markup=main_menu_keyboard(uid), parse_mode="Markdown")

    elif action == "btn_deposit":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📱 Telebirr", callback_data="depmeth_Telebirr"),
            InlineKeyboardButton("🏦 CBE Birr", callback_data="depmeth_CBE_Birr")
        )
        bot.send_message(call.message.chat.id, "📥 **የክፍያ አማራጭ ይምረጡ፦**", reply_markup=markup, parse_mode="Markdown")

    elif action == "btn_withdraw":
        if bal < MIN_WITHDRAWAL:
            bot.send_message(call.message.chat.id, f"❌ **ዝቅተኛው የዊዝድሮው መጠን {MIN_WITHDRAWAL:.2f} ETB ነው።**\nየእርስዎ ባላንስ፦ **{bal:.2f} ETB**", parse_mode="Markdown")
            return
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("📱 Telebirr", callback_data="wdmeth_Telebirr"))
        bot.send_message(call.message.chat.id, "📤 **ገንዘብ መቀበያ ይምረጡ፦**", reply_markup=markup, parse_mode="Markdown")

    elif action == "btn_referral":
        ref_link = f"https://t.me/BkbingosupportBot?start=ref_{uid}"
        bot.send_message(call.message.chat.id, f"👥 **የእርስዎ የሪፈራል ሊንክ፦**\n{ref_link}\n\nጓደኞችዎን በመጋበዝ የኮሚሽን ቦነስ ያግኙ!", parse_mode="Markdown")

    elif action == "btn_help":
        bot.send_message(call.message.chat.id, "ℹ️ **የ BKBINGO Pro ህጎች**\n1. የካርቴላ ዋጋ 10 ETB ነው።\n2. በአንድ ዙር ቢበዛ 2 ካርቴላ መግዛት ይቻላል።\n3. አሸናፊው ደራሹን በሙሉ ይወስዳል።", parse_mode="Markdown")

# DEPOSIT HANDLERS & APPROVAL
@bot.callback_query_handler(func=lambda call: call.data.startswith('depmeth_'))
def handle_dep_method(call):
    uid = int(call.from_user.id)
    method = call.data.split('_', 1)[1]
    deposit_data[uid] = {'method': method}
    user_states[uid] = "WAITING_DEPOSIT"
    bot.edit_message_text(f"✅ የተመረጠው፦ **{method}**\n📌 የክፍያ ቁጥር፦ `0991983522`\n\nገንዘቡን ገቢ ካደረጉ በኋላ የትራንዛክሽን ቁጥሩን ወይም ደረሰኙን (Screenshot) እዚህ ይላኩ።", call.message.chat.id, call.message.message_id, parse_mode="Markdown")

@bot.message_handler(func=lambda m: user_states.get(int(m.from_user.id)) == "WAITING_DEPOSIT", content_types=['text', 'photo'])
def handle_deposit_sub(message):
    uid = int(message.from_user.id)
    user_states[uid] = None
    
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("✅ Approve 50 ETB", callback_data=f"app_50_{uid}"),
        InlineKeyboardButton("✅ Approve 100 ETB", callback_data=f"app_100_{uid}")
    )
    bot.send_message(ADMIN_ID, f"🚨 **አዲስ የዲፖዚት ጥያቄ ከ ተጫዋች `{uid}`**\nየተላከው መረጃ፦ {message.text if message.text else 'Image Attachment'}", reply_markup=markup, parse_mode="Markdown")
    bot.send_message(message.chat.id, "✅ **የዲፖዚት መረጃዎ ለአድሚን ተልኳል!** አድሚኑ አጣርቶ በቅርቡ ባላንስዎን ይጨምራል።")

@bot.callback_query_handler(func=lambda call: call.data.startswith('app_'))
def handle_deposit_approve(call):
    parts = call.data.split('_')
    amt = float(parts[1])
    target_uid = int(parts[2])

    if target_uid not in users_db:
        users_db[target_uid] = {"id": target_uid, "name": f"User {target_uid}", "balance": 0.0}

    users_db[target_uid]["balance"] += amt
    
    # Broadcast Balance Update via SocketIO
    socketio.emit('balance_update', {'user_id': target_uid, 'balance': users_db[target_uid]["balance"]})

    bot.edit_message_text(f"✅ **ዲፖዚት ፀድቋል!** +{amt} ETB ለተጫዋች `{target_uid}` ተጨምሯል።", call.message.chat.id, call.message.message_id)
    bot.send_message(target_uid, f"🎉 **ዲፖዚትዎ ፀድቋል!**\n💰 አዲሱ ባላንስዎ፦ **{users_db[target_uid]['balance']:.2f} ETB**", parse_mode="Markdown")

# =========================================================
# 6. SUPPORT BOT HANDLERS
# =========================================================
@support_bot.message_handler(commands=['start'])
def start_support_bot(message):
    text = message.text
    user_info = ""
    
    if "USER_" in text and "_BAL_" in text:
        try:
            parts = text.split("USER_")[1].split("_BAL_")
            u_id = parts[0]
            bal = parts[1]
            user_info = f"\n\n👤 **የተጫዋች መረጃ፦**\n🆔 ID: `{u_id}`\n💰 ባላንስ: **{bal} ETB**"
        except Exception:
            pass

    welcome_msg = (
        f"👋 ሰላም **{message.from_user.first_name}**!\n"
        f"ወደ **BKBINGO Pro** የደንበኞች አገልግሎት እንኳን ደህና መጡ! 🎧{user_info}\n\n"
        f"ያጋጠመዎትን ችግር ወይም ጥያቄ በአንድ መልእክት ጽፈው ይላኩልን።"
    )
    support_bot.send_message(message.chat.id, welcome_msg, parse_mode="Markdown")

@support_bot.message_handler(func=lambda m: int(m.from_user.id) != ADMIN_ID, content_types=['text', 'photo'])
def handle_support_inquiry(message):
    uid = int(message.from_user.id)
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✍️ መልስ ስጥ (Reply)", callback_data=f"suppreply_{uid}"))

    admin_msg = (
        f"📩 **አዲስ የደንበኞች ጥያቄ!**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 ከ: {message.from_user.first_name} (`{uid}`)\n"
        f"💬 መልእክት፦ {message.text if message.text else 'Photo Sent'}"
    )

    if message.photo:
        support_bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=admin_msg, reply_markup=markup, parse_mode="Markdown")
    else:
        support_bot.send_message(ADMIN_ID, admin_msg, reply_markup=markup, parse_mode="Markdown")

    support_bot.send_message(message.chat.id, "✅ **መልእክትዎ ለደንበኞች አገልግሎት ደርሷል!** አድሚኑ አጣርቶ በቅርቡ ምላሽ ይሰጥዎታል።")

@support_bot.callback_query_handler(func=lambda call: call.data.startswith('suppreply_'))
def prepare_support_reply(call):
    target_uid = int(call.data.split('_')[1])
    admin_reply_state[ADMIN_ID] = target_uid
    support_bot.answer_callback_query(call.id)
    support_bot.send_message(ADMIN_ID, f"✍️ ለ ተጫዋች `{target_uid}` የሚላከውን መልስ አሁን ይጻፉ፦", parse_mode="Markdown")

@support_bot.message_handler(func=lambda m: int(m.from_user.id) == ADMIN_ID and ADMIN_ID in admin_reply_state)
def send_support_reply(message):
    target_uid = admin_reply_state.pop(ADMIN_ID, None)
    if target_uid:
        try:
            support_bot.send_message(
                target_uid,
                f"🎧 **ከደንበኞች አገልግሎት የተሰጠ መልስ፦**\n━━━━━━━━━━━━━━━\n{message.text}"
            )
            support_bot.send_message(ADMIN_ID, f"✅ መልሱ ለተጫዋች `{target_uid}` ተልኳል!")
        except Exception as e:
            support_bot.send_message(ADMIN_ID, f"❌ መልእክቱን መላክ አልተቻለም፦ {e}")

# =========================================================
# 7. REAL-TIME BINGO GAME LOOP & WINNER LOGIC
# =========================================================
@socketio.on('get_user_balance')
def handle_get_balance(data):
    if not data or 'user_id' not in data:
        return
    uid = int(data.get('user_id'))
    if uid not in users_db:
        users_db[uid] = {"id": uid, "name": f"User {uid}", "balance": 0.0}
    
    bal = users_db[uid]["balance"]
    emit('balance_update', {'user_id': uid, 'balance': bal})

@socketio.on('select_card')
def handle_card_selection(data):
    uid = int(data.get('user_id'))
    card_id = int(data.get('card_id'))

    if uid not in users_db:
        users_db[uid] = {"id": uid, "name": f"User {uid}", "balance": 0.0}

    bal = users_db[uid]["balance"]
    if bal < CARD_PRICE:
        emit('error_msg', {'msg': 'በቂ ባላንስ የሎትም። እባክዎን አስቀድመው ዲፖዚት ያድርጉ።'})
        return

    if card_id in game_state['selected_cards']:
        return

    # Deduct Card Price & Update Realtime Balance
    users_db[uid]["balance"] -= CARD_PRICE
    game_state['selected_cards'][card_id] = uid
    if uid not in game_state['player_cards']:
        game_state['player_cards'][uid] = []
    game_state['player_cards'][uid].append(card_id)

    matrix = cards_database.get(card_id)
    emit('card_confirmed', {'card_id': card_id, 'matrix': matrix, 'new_balance': users_db[uid]["balance"]}, broadcast=False)
    emit('balance_update', {'user_id': uid, 'balance': users_db[uid]["balance"]}, broadcast=False)

def game_loop():
    global game_state
    while True:
        game_state["status"] = "WAITING"
        game_state["selected_cards"] = {}
        game_state["player_cards"] = {}
        game_state["drawn_numbers"] = []
        socketio.emit('reset_game')

        while len(game_state["selected_cards"]) == 0:
            socketio.sleep(1)

        game_state["status"] = "COUNTDOWN"
        for t in range(15, 0, -1):
            socketio.emit('timer_update', {
                'time_left': t,
                'sold_count': len(game_state["selected_cards"])
            })
            socketio.sleep(1)

        game_state["status"] = "PLAYING"
        total_pool = len(game_state["selected_cards"]) * CARD_PRICE
        derash = total_pool * (1 - COMMISSION_RATE)
        game_state["derash"] = derash

        socketio.emit('game_started', {'status': 'PLAYING', 'derash': derash})

        available_balls = list(range(1, 76))
        random.shuffle(available_balls)
        drawn_set = set()
        winner_found = False

        for ball in available_balls:
            if winner_found:
                break

            drawn_set.add(ball)
            game_state["drawn_numbers"].append(ball)
            socketio.emit('new_number', {'ball': ball})
            socketio.sleep(2.5)

            for card_id, owner_id in game_state["selected_cards"].items():
                matrix = cards_database[card_id]
                if check_bingo_winner(matrix, drawn_set):
                    winner_found = True
                    
                    if owner_id in users_db:
                        users_db[owner_id]["balance"] += derash
                        w_name = users_db[owner_id].get("name", f"Player {owner_id}")
                        socketio.emit('balance_update', {'user_id': owner_id, 'balance': users_db[owner_id]["balance"]})
                    else:
                        w_name = f"Player {owner_id}"

                    socketio.emit('winner_announced', {
                        'winner_id': owner_id,
                        'winner_name': w_name,
                        'prize': derash,
                        'card_id': card_id,
                        'card_matrix': matrix
                    })
                    break

        socketio.sleep(8)

# =========================================================
# 8. THREAD RUNNERS & MAIN EXECUTION
# =========================================================
def run_main_bot():
    while True:
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.infinity_polling(skip_pending=True)
        except Exception:
            time.sleep(3)

def run_support_bot():
    while True:
        try:
            support_bot.remove_webhook()
            time.sleep(1)
            support_bot.infinity_polling(skip_pending=True)
        except Exception:
            time.sleep(3)

if __name__ == "__main__":
    Thread(target=run_main_bot, daemon=True).start()
    Thread(target=run_support_bot, daemon=True).start()
    socketio.start_background_task(game_loop)
    
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
