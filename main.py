import os
import random
import time
from threading import Thread
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

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

# የ Render URLህ
RENDER_WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://bingo-bot-c90r.onrender.com")

# =========================================================
# HTML TEMPLATE (INLINE TO PREVENT TEMPLATE NOT FOUND ERROR)
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
        .card-bg { background-color: #242f42; }
        .accent-green { background-color: #10b981; }
        .accent-purple { background-color: #8b5cf6; }
    </style>
</head>
<body class="bingo-bg text-white font-sans select-none pb-10">

    <!-- TOP HEADER -->
    <div class="grid grid-cols-4 gap-2 p-3 text-center text-xs font-bold">
        <div class="bg-amber-500 text-slate-900 rounded-xl p-2 flex flex-col justify-center shadow">
            <span class="text-[10px] opacity-80">ROOM</span>
            <span>VIP 💰</span>
        </div>
        <div class="bg-slate-700 rounded-xl p-2 flex flex-col justify-center">
            <span class="text-[10px] text-gray-400">SOLD</span>
            <span class="text-sm">228</span>
        </div>
        <div class="bg-slate-700 rounded-xl p-2 flex flex-col justify-center">
            <span class="text-[10px] text-red-400">TIME</span>
            <span id="timer" class="text-sm text-red-400">15s</span>
        </div>
        <div class="bg-emerald-600 rounded-xl p-2 flex flex-col justify-center">
            <span class="text-[10px] opacity-80">BALANCE</span>
            <span class="text-sm">20.00 ETB</span>
        </div>
    </div>

    <!-- CARTELA SELECTION DASHBOARD (1-104) -->
    <div id="selection-screen" class="px-3">
        <div class="text-center text-xs text-gray-300 mb-2">እባክዎን የሚጫወቱበትን የካርቴላ ቁጥር ይምረጡ፦</div>
        <div id="cartela-grid" class="grid grid-cols-8 gap-1.5 bg-slate-800/60 p-2 rounded-2xl max-h-[60vh] overflow-y-auto">
        </div>
    </div>

    <!-- LIVE GAME SCREEN -->
    <div id="game-screen" class="hidden px-2">
        <div class="flex justify-between items-center text-xs mb-2 px-2 text-gray-300">
            <div>DERASH: <span class="text-emerald-400 font-bold">1824 ETB</span></div>
            <div>BALLS: <span id="balls-count" class="font-bold text-white">0/75</span></div>
            <div>PLAYERS: <span class="font-bold text-white">228</span></div>
        </div>

        <div class="flex gap-2">
            <!-- LEFT 1-75 BOARD -->
            <div class="w-1/3 bg-slate-800 rounded-xl p-1 text-[10px] font-bold">
                <div class="grid grid-cols-5 text-center text-purple-400 font-black mb-1">
                    <div>B</div><div>I</div><div>N</div><div>G</div><div>O</div>
                </div>
                <div id="bingo-75-grid" class="grid grid-cols-5 gap-1 text-center">
                </div>
            </div>

            <!-- RIGHT BALL & CARDS -->
            <div class="w-2/3 flex flex-col items-center">
                <div id="current-ball" class="w-20 h-20 rounded-full accent-purple flex items-center justify-center text-2xl font-black shadow-lg border-4 border-purple-300 mb-3 animate-pulse">
                    READY
                </div>
                <div id="my-cards-container" class="w-full space-y-3">
                </div>
            </div>
        </div>
    </div>

    <!-- WINNER MODAL -->
    <div id="winner-modal" class="fixed inset-0 bg-black/80 flex items-center justify-center p-4 hidden z-50">
        <div class="bg-white text-slate-900 rounded-3xl p-5 w-full max-w-sm text-center shadow-2xl relative border-4 border-amber-400">
            <h2 class="text-3xl font-black text-red-600 mb-1">1 <span class="text-lg text-gray-700">አሸናፊ</span></h2>
            <div id="winner-name" class="text-2xl font-black text-emerald-600 italic mb-2">Abrshi has won!</div>
            
            <div class="bg-gray-100 rounded-2xl p-3 mb-4">
                <div class="text-xs text-gray-500 font-bold">TOTAL PRIZE POOL</div>
                <div id="winner-prize" class="text-2xl font-black text-emerald-600">1824 ETB</div>
            </div>

            <div class="text-left font-bold text-blue-600 text-sm mb-2" id="winner-card-title">CARD #62</div>
            <div id="winner-card-matrix" class="grid grid-cols-5 gap-1 bg-gray-200 p-2 rounded-2xl text-center text-xs font-bold mb-4">
            </div>

            <div class="w-full bg-amber-400 h-2 rounded-full overflow-hidden">
                <div class="bg-amber-600 h-full w-full animate-ping"></div>
            </div>
            <div class="text-[10px] text-gray-500 mt-2 font-bold">NEXT ROUND: 12S</div>
        </div>
    </div>

    <script>
        const socket = io();
        const tg = window.Telegram ? window.Telegram.WebApp : null;
        if(tg) tg.expand();

        let mySelectedCards = [64, 80];
        let drawnNumbersSet = new Set();

        const gridContainer = document.getElementById('cartela-grid');
        for (let i = 1; i <= 104; i++) {
            const btn = document.createElement('button');
            btn.className = `p-2 text-xs font-bold rounded-lg border transition ${mySelectedCards.includes(i) ? 'bg-emerald-500 text-white border-emerald-400' : 'bg-slate-700/80 text-gray-300 border-slate-600'}`;
            btn.innerText = i;
            btn.onclick = () => selectCard(i, btn);
            gridContainer.appendChild(btn);
        }

        const board75 = document.getElementById('bingo-75-grid');
        for (let i = 1; i <= 75; i++) {
            const cell = document.createElement('div');
            cell.id = `ball-cell-${i}`;
            cell.className = 'p-1 rounded bg-slate-700 text-gray-300';
            cell.innerText = i;
            board75.appendChild(cell);
        }

        function selectCard(num, btn) {
            btn.className = 'p-2 text-xs font-bold rounded-lg bg-emerald-500 text-white border border-emerald-400';
            socket.emit('select_card', { card_num: num });
        }

        socket.on('timer_update', (data) => {
            document.getElementById('timer').innerText = `${data.time_left}s`;
        });

        socket.on('game_started', () => {
            document.getElementById('selection-screen').classList.add('hidden');
            document.getElementById('game-screen').classList.remove('hidden');
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

            highlightUserCards();
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
                    div.className = `p-1.5 rounded-lg ${isHit ? 'bg-emerald-500 text-white font-bold' : 'bg-white text-slate-800'}`;
                    div.innerText = val === 'FREE' ? '★' : val;
                    matrixContainer.appendChild(div);
                });
            });

            document.getElementById('winner-modal').classList.remove('hidden');
        });

        function renderMyCards() {
            const container = document.getElementById('my-cards-container');
            container.innerHTML = '';
            
            const sampleCards = [
                { id: 80, matrix: [[3,21,45,52,68],[10,30,37,48,66],[13,26,'★',56,70],[14,24,35,46,73],[7,25,34,55,62]] },
                { id: 64, matrix: [[6,29,38,60,64],[10,23,42,59,73],[14,28,'★',48,72],[9,27,32,53,61],[1,26,31,56,63]] }
            ];

            sampleCards.forEach(card => {
                const cardDiv = document.createElement('div');
                cardDiv.className = 'bg-white text-slate-900 rounded-2xl p-2 shadow-lg';
                let html = `<div class="flex justify-between items-center text-xs font-bold text-blue-600 mb-1"><span>#${card.id}</span><span class="text-[10px] bg-blue-100 px-1 rounded">LIVE</span></div>`;
                html += `<div class="grid grid-cols-5 gap-1 text-center font-bold text-xs">`;
                
                card.matrix.forEach(row => {
                    row.forEach(val => {
                        const isHit = val === '★' || drawnNumbersSet.has(val);
                        html += `<div class="p-1 rounded ${isHit ? 'bg-emerald-500 text-white font-black' : 'bg-gray-100 text-slate-800'}" id="card-${card.id}-${val}">${val}</div>`;
                    });
                });
                
                html += `</div><button class="w-full mt-2 py-1 bg-blue-600 text-white text-xs font-black rounded-xl">BINGO!</button>`;
                cardDiv.innerHTML = html;
                container.appendChild(cardDiv);
            });
        }

        function highlightUserCards() {
            drawnNumbersSet.forEach(num => {
                const elements = document.querySelectorAll(`[id$='-${num}']`);
                elements.forEach(el => {
                    el.className = 'p-1 rounded bg-emerald-500 text-white font-black';
                });
            });
        }
    </script>
</body>
</html>
"""

# =========================================================
# GAME STATE
# =========================================================
game_state = {
    "status": "WAITING",
    "time_left": 15,
    "drawn_numbers": [],
    "current_ball": None
}

# =========================================================
# FLASK ROUTES
# =========================================================
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

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
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        print(f"Bot Error: {e}")

# =========================================================
# SOCKET.IO & GAME LOOP
# =========================================================
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
