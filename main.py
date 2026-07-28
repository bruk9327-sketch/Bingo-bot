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
# 1. FLASK & SOCKETIO SETUP
# =========================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'bingo_secret_key_123'
socketio = SocketIO(app, cors_allowed_origins="*")

# =========================================================
# 2. TELEGRAM BOT SETUP
# =========================================================
API_TOKEN = os.environ.get("BOT_TOKEN", "8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM")
bot = telebot.TeleBot(API_TOKEN)

RENDER_WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://bingo-bot-c90r.onrender.com")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "855985673")) 

# Data Storage & Validation Database
user_balances = {}       # {user_id: balance}
user_states = {}         # {user_id: state}
used_txn_ids = set()     # 🛡️ ድጋሚ የገቡ የትራንዛክሽን ቁጥሮችን መያዣ (Duplicate Check)

# =========================================================
# 3. HTML TEMPLATE (MINI APP)
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
        .bingo-bg { background-color: #1a2232; }
        .accent-purple { background-color: #8b5cf6; }
    </style>
</head>
<body class="bingo-bg text-white font-sans select-none pb-10">

    <div class="grid grid-cols-4 gap-2 p-3 text-center text-xs font-bold">
        <div class="bg-amber-500 text-slate-900 rounded-xl p-2 flex flex-col justify-center shadow">
            <span class="text-[10px] opacity-80">ROOM</span>
            <span>VIP 💰</span>
        </div>
        <div class="bg-slate-700 rounded-xl p-2 flex flex-col justify-center">
            <span class="text-[10px] text-gray-400">PLAYERS</span>
            <span class="text-sm" id="players-count">10</span>
        </div>
        <div class="bg-slate-700 rounded-xl p-2 flex flex-col justify-center">
            <span class="text-[10px] text-red-400">TIME</span>
            <span id="timer" class="text-sm text-red-400">15s</span>
        </div>
        <div class="bg-emerald-600 rounded-xl p-2 flex flex-col justify-center">
            <span class="text-[10px] opacity-80">BET</span>
            <span class="text-sm">10 ETB</span>
        </div>
    </div>

    <div id="selection-screen" class="px-3">
        <div class="text-center text-xs text-gray-300 mb-2">እባክዎን የሚጫወቱባቸውን 2 የካርቴላ ቁጥሮች ይምረጡ፦</div>
        <div id="cartela-grid" class="grid grid-cols-8 gap-1.5 bg-slate-800/60 p-2 rounded-2xl max-h-[55vh] overflow-y-auto">
        </div>
        <div class="text-center mt-3">
            <span class="text-xs text-amber-400 font-bold" id="selected-info">የተመረጡት ካርቴላዎች፦ #64, #80</span>
        </div>
    </div>

    <div id="game-screen" class="hidden px-2">
        <div class="flex justify-between items-center text-xs mb-2 px-2 text-gray-300">
            <div>DERASH (ደራሽ): <span class="text-emerald-400 font-bold" id="derash-amount">90 ETB</span></div>
            <div>BALLS: <span id="balls-count" class="font-bold text-white">0/75</span></div>
        </div>

        <div class="flex gap-2">
            <div class="w-1/3 bg-slate-800 rounded-xl p-1 text-[10px] font-bold">
                <div class="grid grid-cols-5 text-center text-purple-400 font-black mb-1">
                    <div>B</div><div>I</div><div>N</div><div>G</div><div>O</div>
                </div>
                <div id="bingo-75-grid" class="grid grid-cols-5 gap-1 text-center">
                </div>
            </div>

            <div class="w-2/3 flex flex-col items-center">
                <div id="current-ball" class="w-20 h-20 rounded-full accent-purple flex items-center justify-center text-2xl font-black shadow-lg border-4 border-purple-300 mb-3 animate-pulse">
                    READY
                </div>
                <div id="my-cards-container" class="w-full space-y-3">
                </div>
            </div>
        </div>
    </div>

    <div id="winner-modal" class="fixed inset-0 bg-black/80 flex items-center justify-center p-4 hidden z-50">
        <div class="bg-white text-slate-900 rounded-3xl p-5 w-full max-w-sm text-center shadow-2xl relative border-4 border-amber-400">
            <h2 class="text-3xl font-black text-red-600 mb-1">1 <span class="text-lg text-gray-700">አሸናፊ</span></h2>
            <div id="winner-name" class="text-2xl font-black text-emerald-600 italic mb-2">Abrshi has won!</div>
            
            <div class="bg-gray-100 rounded-2xl p-3 mb-4">
                <div class="text-xs text-gray-500 font-bold">TOTAL DERASH (ደራሽ)</div>
                <div id="winner-prize" class="text-2xl font-black text-emerald-600">90 ETB</div>
            </div>

            <div class="text-left font-bold text-blue-600 text-sm mb-2" id="winner-card-title">CARD #62</div>
            <div id="winner-card-matrix" class="grid grid-cols-5 gap-1 bg-gray-200 p-2 rounded-2xl text-center text-xs font-bold mb-4">
            </div>

            <div class="w-full bg-amber-400 h-2 rounded-full overflow-hidden">
                <div class="bg-amber-600 h-full w-full animate-ping"></div>
            </div>
            <div class="text-[10px] text-gray-500 mt-2 font-bold">አዲስ ዙር በመጀመር ላይ...</div>
        </div>
    </div>

    <script>
        const socket = io();
        const tg = window.Telegram ? window.Telegram.WebApp : null;
        if(tg) tg.expand();

        let mySelectedCards = [64, 80];
        let drawnNumbersSet = new Set();

        function initCartelaGrid() {
            const gridContainer = document.getElementById('cartela-grid');
            gridContainer.innerHTML = '';
            for (let i = 1; i <= 104; i++) {
                const btn = document.createElement('button');
                const isSelected = mySelectedCards.includes(i);
                
                btn.className = `p-2 text-xs font-bold rounded-lg border transition ${isSelected ? 'bg-slate-900 text-amber-400 border-amber-400 font-black shadow-lg scale-105' : 'bg-slate-700/80 text-gray-300 border-slate-600'}`;
                btn.innerText = i;
                btn.onclick = () => toggleCardSelection(i);
                gridContainer.appendChild(btn);
            }
            updateSelectedInfo();
        }

        function toggleCardSelection(num) {
            if (mySelectedCards.includes(num)) {
                if (mySelectedCards.length > 1) {
                    mySelectedCards = mySelectedCards.filter(c => c !== num);
                }
            } else {
                if (mySelectedCards.length >= 2) {
                    mySelectedCards.shift();
                }
                mySelectedCards.push(num);
            }
            initCartelaGrid();
        }

        function updateSelectedInfo() {
            document.getElementById('selected-info').innerText = `የተመረጡት ካርቴላዎች፦ #${mySelectedCards.join(', #')}`;
        }

        function init75Board() {
            const board75 = document.getElementById('bingo-75-grid');
            board75.innerHTML = '';
            for (let i = 1; i <= 75; i++) {
                const cell = document.createElement('div');
                cell.id = `ball-cell-${i}`;
                cell.className = 'p-1 rounded bg-slate-700 text-gray-300';
                cell.innerText = i;
                board75.appendChild(cell);
            }
        }

        initCartelaGrid();
        init75Board();

        socket.on('timer_update', (data) => {
            document.getElementById('timer').innerText = `${data.time_left}s`;
            if (data.status === 'WAITING') {
                document.getElementById('winner-modal').classList.add('hidden');
                document.getElementById('game-screen').classList.add('hidden');
                document.getElementById('selection-screen').classList.remove('hidden');
                drawnNumbersSet.clear();
                init75Board();
            }
        });

        socket.on('game_started', () => {
            document.getElementById('selection-screen').classList.add('hidden');
            document.getElementById('game-screen').classList.remove('hidden');
            document.getElementById('winner-modal').classList.add('hidden');
            renderMyCards();
        });

        socket.on('new_number', (data) => {
            drawnNumbersSet.add(data.number);
            document.getElementById('current-ball').innerText = data.ball;
            document.getElementById('balls-count').innerText = `${data.drawn_list.length}/75`;
            
            const cell = document.getElementById(`ball-cell-${data.number}`);
            if(cell) {
                cell.className = 'p-1 rounded bg-emerald-500 text-white font-black animate-bounce';
            }
        });

        socket.on('winner_announced', (data) => {
            document.getElementById('winner-name').innerText = `${data.winner_name} has won!`;
            document.getElementById('winner-prize').innerText = `${data.prize} ETB`;
            document.getElementById('winner-card-title').innerText = `CARD #${data.card_num}`;
            
            const matrixContainer = document.getElementById('winner-card-matrix');
            matrixContainer.innerHTML = '';
            
            data.card_matrix.forEach(row => {
                row.forEach(val => {
                    const div = document.createElement('div');
                    const isHit = val === 'FREE' || drawnNumbersSet.has(val);
                    div.className = `p-1.5 rounded-lg ${isHit ? 'bg-emerald-500 text-white font-bold' : 'bg-gray-100 text-slate-800'}`;
                    div.innerText = val === 'FREE' ? '★' : val;
                    matrixContainer.appendChild(div);
                });
            });

            document.getElementById('winner-modal').classList.remove('hidden');
        });

        function renderMyCards() {
            const container = document.getElementById('my-cards-container');
            container.innerHTML = '';
            
            mySelectedCards.forEach(cardId => {
                const cardDiv = document.createElement('div');
                cardDiv.className = 'bg-white text-slate-900 rounded-2xl p-2 shadow-lg';
                let html = `<div class="flex justify-between items-center text-xs font-bold text-blue-600 mb-1"><span>CARD #${cardId}</span><span class="text-[10px] bg-blue-100 px-1 rounded">LIVE</span></div>`;
                html += `<div class="grid grid-cols-5 gap-1 text-center font-bold text-xs">`;
                
                const sampleMatrix = [
                    [3 + (cardId % 5), 21, 45, 52, 68],
                    [10, 30, 37, 48, 66],
                    [13, 26, '★', 56, 70],
                    [14, 24, 35, 46, 73],
                    [7, 25, 34, 55, 62 + (cardId % 3)]
                ];

                sampleMatrix.forEach(row => {
                    row.forEach(val => {
                        const isHit = val === '★' || drawnNumbersSet.has(val);
                        html += `<div class="p-1 rounded ${isHit ? 'bg-emerald-500 text-white font-black' : 'bg-gray-100 text-slate-800'}">${val}</div>`;
                    });
                });
                
                html += `</div><button class="w-full mt-2 py-1 bg-blue-600 text-white text-xs font-black rounded-xl">BINGO!</button>`;
                cardDiv.innerHTML = html;
                container.appendChild(cardDiv);
            });
        }
    </script>
</body>
</html>
"""

# =========================================================
# 4. FLASK ROUTES
# =========================================================
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

# =========================================================
# 5. TELEGRAM BOT HANDLERS & VALIDATION LOGIC
# =========================================================
def main_menu_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    web_app = WebAppInfo(url=RENDER_WEBAPP_URL)
    
    btn_play = KeyboardButton(text="🎲 ጨዋታ ጀምር (Open App)", web_app=web_app)
    btn_profile = KeyboardButton(text="👤 ፕሮፋይል / ባላንስ")
    btn_deposit = KeyboardButton(text="📥 ዲፖዚት (Deposit)")
    btn_withdraw = KeyboardButton(text="📤 ዊዝድሮው (Withdraw)")
    btn_referral = KeyboardButton(text="👥 ሪፈራል / ግብዣ")
    btn_help = KeyboardButton(text="ℹ️ እርዳታ እና ህጎች")

    markup.add(btn_play)
    markup.add(btn_profile, btn_deposit)
    markup.add(btn_withdraw, btn_referral)
    markup.add(btn_help)
    return markup

@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = message.from_user.id
    if uid not in user_balances:
        user_balances[uid] = 0.00

    welcome_txt = (
        f"👋 ሰላም **{message.from_user.first_name}**!\n\n"
        "ወደ **GoodBingo** ኦፊሴላዊ የጨዋታ ቦት እንኳን ደህና መጡ! 🎲\n\n"
        "⚠️ **ህግ:** ጨዋታ ለመጫወት ቢያንስ **20 ETB** ዲፖዚት ማድረግ ይኖርብዎታል!"
    )
    bot.send_message(message.chat.id, welcome_txt, reply_markup=main_menu_keyboard(), parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and "ፕሮፋይል" in m.text)
def profile_cmd(message):
    uid = message.from_user.id
    bal = user_balances.get(uid, 0.0)
    msg = (
        f"👤 **የተጫዋች ፕሮፋይል**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 User ID: `{uid}`\n"
        f"💰 ወቅታዊ ባላንስ: **{bal:.2f} ETB**\n\n"
        f"{'✅ ጨዋታ መጫወት ይችላሉ!' if bal >= 20 else '⚠️ ጨዋታ ለመክፈት ቢያንስ 20 ETB ዲፖዚት ያድርጉ!'}"
    )
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

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
        "ያስገቡትን የብር መጠን እና የትራንዛክሽን ቁጥር በግልጽ ይጻፉ።\n\n"
        "📌 **ምሳሌ፦** `50 ETB - TXN98765432` ወይም `100 ብር - 7891234`\n\n"
        "🔴 **ማሳሰቢያ:** አነስተኛ የዲፖዚት መጠን **20 ETB** ሲሆን፣ ድጋሚ የተላከ የደረሰኝ ቁጥር አይቀበልም!"
    )
    bot.send_message(message.chat.id, dep_text, parse_mode="Markdown")

# 🛠️ የተሻሻለ የዲፖዚት ቫሊዴሽን (Deposit Validation Handler)
@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "WAITING_DEPOSIT_INFO", content_types=['text', 'photo'])
def handle_deposit_submission(message):
    uid = message.from_user.id
    text_content = message.text if message.text else message.caption

    if not text_content and not message.photo:
        bot.send_message(message.chat.id, "❌ **እባክዎን ትክክለኛ የትራንዛክሽን መረጃ ወይም ስክሪንሾት (Screenshot) ይላኩ!**")
        return

    extracted_txn = None
    extracted_amount = 0

    if text_content:
        # 1. የትራንዛክሽን ቁጥር ማወቂያ (Extract Txn ID e.g. TXN12345, 10293847, etc.)
        txn_match = re.search(r'([A-Za-z0-9]{6,20})', text_content)
        if txn_match:
            extracted_txn = txn_match.group(1).upper()

        # 2. የብር መጠን ማወቂያ (Extract Amount)
        numbers = re.findall(r'\d+', text_content)
        for num in numbers:
            val = int(num)
            if val >= 20: # አነስተኛው 20 ETB
                extracted_amount = val
                break

    # 🛡️ VALIDATION 1: ድጋሚ የገባ የትራንዛክሽን ቁጥር መከላከል (Duplicate Txn Check)
    if extracted_txn and extracted_txn in used_txn_ids:
        bot.send_message(
            message.chat.id, 
            f"❌ **ይህ የትራንዛክሽን ቁጥር (`{extracted_txn}`) ከዚህ ቀደም አገልግሎት ላይ ውሏል!**\n\n"
            "እባክዎን አዲስ እና ትክክለኛ የደረሰኝ ቁጥር ይላኩ።",
            parse_mode="Markdown"
        )
        return

    # 🛡️ VALIDATION 2: አነስተኛ የብር መጠን ማረጋገጫ (Minimum Amount Check)
    if text_content and extracted_amount < 20 and not message.photo:
        bot.send_message(
            message.chat.id,
            "⚠️ **አነስተኛው የዲፖዚት መጠን 20 ETB ነው።**\nእባክዎን ከ20 ETB በላይ አስገብተው እንደገና ይላኩ።"
        )
        return

    # የትራንዛክሽን ቁጥር ከተገኘ ወደ Used List እንጨምረዋለን
    if extracted_txn:
        used_txn_ids.add(extracted_txn)

    # ቫሊዴሽኑን ካለፈ ወደ አድሚን ይላካል
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
        InlineKeyboardButton("❌ Reject", callback_data=f"rej_{uid}_{dep_id}")
    )

    admin_msg = (
        f"🚨 **አዲስ የተረጋገጠ የዲፖዚት ጥያቄ!**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 ተጫዋች: {message.from_user.first_name} (`{uid}`)\n"
        f"🔍 የተለየ Txn ID: `{extracted_txn if extracted_txn else 'መረጃ አልተገኘም'}`\n"
        f"💵 የታሰበው መጠን: **{suggested_amt} ETB**\n"
        f"📝 ሙሉ መልእክት: {text_content if text_content else 'Photo Sent'}\n\n"
        "ማረጋገጫ ይስጡ፦"
    )
    
    try:
        if message.photo:
            bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=admin_msg, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(ADMIN_ID, admin_msg, reply_markup=markup, parse_mode="Markdown")
            
        bot.send_message(message.chat.id, "✅ **የዲፖዚት መረጃዎ በስኬት ተላክቷል!**\nአድሚኑ መረጃውን አጣርቶ በቅርቡ ባላንስዎን ያዘምነዋል።")
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
        bot.send_message(target_uid, "❌ **የዲፖዚት ጥያቄዎ አልተቀበለም!**\nእባክዎን ትክክለኛውን የትራንዛክሽን መረጃ እንደገና ይላኩ።")
    
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
            f"💰 አጠቃላይ ባላንስ: **{new_bal:.2f} ETB**\n\n"
            f"{'🎮 አሁን ጨዋታ መጫወት ይችላሉ!' if new_bal >= 20 else '⚠️ ጨዋታ ለመክፈት ባላንስዎ 20 ETB መሙላት አለበት።'}",
            parse_mode="Markdown"
        )

@bot.message_handler(func=lambda m: m.text and "ዊዝድሮው" in m.text)
def withdraw_cmd(message):
    uid = message.from_user.id
    bal = user_balances.get(uid, 0.0)
    
    if bal < 50:
        bot.send_message(message.chat.id, f"❌ **ዝቅተኛው የዊዝድሮው መጠን 50 ETB ነው።**\nየእርስዎ ባላንስ: **{bal:.2f} ETB**")
        return

    w_text = (
        "📤 **ገንዘብ ማውጫ (Withdrawal)**\n"
        "━━━━━━━━━━━━━━━\n"
        f"💰 የእርስዎ ባላንስ: **{bal:.2f} ETB**\n\n"
        "እባክዎን የሚያወጡትን መጠን እና የቴሌብር/ባንክ ሂሳብ ቁጥር ይላኩ።"
    )
    bot.send_message(message.chat.id, w_text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and "ሪፈራል" in m.text)
def referral_cmd(message):
    uid = message.from_user.id
    bot_name = bot.get_me().username
    ref_link = f"https://t.me/{bot_name}?start={uid}"
    
    msg = (
        "👥 **የሪፈራል ፕሮግራም**\n"
        "━━━━━━━━━━━━━━━\n"
        "ጓደኞችዎን በመጋበዝ የእያንዳንዱን ሰው የመጀመሪያ ዲፖዚት 10% ያግኙ!\n\n"
        f"🔗 የእርስዎ የግብዣ ሊንክ፦\n`{ref_link}`"
    )
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and "እርዳታ" in m.text)
def help_cmd(message):
    help_txt = (
        "ℹ️ **የጨዋታ ህጎች እና መመሪያዎች**\n"
        "━━━━━━━━━━━━━━━\n"
        "1. **አነስተኛ ባላንስ:** ጨዋታ ለመጫወት ባላንስዎ ቢያንስ **20 ETB** መሆን አለበት።\n"
        "2. **የጨዋታ ክፍያ:** እያንዳንዱ ዙር **10 ETB** ያስከፍላል።\n"
        "3. **ደራሽ (Derash) ስሌት:** (10 ተጫዋች × 10 ETB) - 10% የቦት ኮሚሽን = **90 ETB ለአሸናፊው**።\n"
        "4. **ማሸነፍ:** BINGO የሞላ ተጫዋች አሸናፊ ሆኖ ደራሹ በራስ-ሰር ባላንሱ ላይ ይጨመራል።"
    )
    bot.send_message(message.chat.id, help_txt, parse_mode="Markdown")

# 🛠️ 100% አስተማማኝ የ Bot Polling Loop
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
# 6. SOCKET.IO & GAME LOOP
# =========================================================
game_state = {
    "status": "WAITING",
    "time_left": 15,
    "drawn_numbers": []
}

@socketio.on('connect')
def handle_connect():
    emit('init_game', game_state)

def game_loop():
    global game_state
    while True:
        game_state["status"] = "WAITING"
        game_state["drawn_numbers"] = []
        
        for t in range(15, 0, -1):
            game_state["time_left"] = t
            socketio.emit('timer_update', {'time_left': t, 'status': 'WAITING'})
            socketio.sleep(1)

        game_state["status"] = "PLAYING"
        socketio.emit('game_started', {'status': 'PLAYING'})

        all_numbers = list(range(1, 76))
        random.shuffle(all_numbers)

        for num in all_numbers:
            if game_state["status"] != "PLAYING":
                break
                
            game_state["drawn_numbers"].append(num)
            letter = 'B' if num <= 15 else 'I' if num <= 30 else 'N' if num <= 45 else 'G' if num <= 60 else 'O'
            ball_str = f"{letter}-{num}"

            socketio.emit('new_number', {
                'number': num,
                'ball': ball_str,
                'drawn_list': game_state["drawn_numbers"]
            })

            if len(game_state["drawn_numbers"]) == 10:
                winner_data = {
                    "winner_name": "Abrshi",
                    "prize": 90,
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
                socketio.sleep(6)
                break

            socketio.sleep(3)

# =========================================================
# 7. MAIN EXECUTION
# =========================================================
if __name__ == "__main__":
    Thread(target=run_bot, daemon=True).start()
    socketio.start_background_task(game_loop)
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
