import eventlet
eventlet.monkey_patch(all=True)

import os
import re
import random
import time
import uuid
import requests
import json
import hashlib
from threading import Thread, Lock
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
)

# =========================================================
# 1. SETUP & CONFIGURATION
# =========================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY", "bkbingo_secret_key_2026")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# BOT TOKENS
MAIN_BOT_TOKEN = os.environ.get("BOT_TOKEN", "8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM")
SUPPORT_BOT_TOKEN = os.environ.get("SUPPORT_BOT_TOKEN", "8912812512:AAHL9OPDgGNa2QS9YHqY5c6KDKuB7OlF-3M")

bot = telebot.TeleBot(MAIN_BOT_TOKEN)
support_bot = telebot.TeleBot(SUPPORT_BOT_TOKEN)

RENDER_WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://wollo.com.et")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "855985673"))

# PAYMENT ACCOUNTS (MANUAL DEPOSIT & SMS VERIFICATION)
CBE_ACCOUNT = "0991983522"
CBE_NAME = "BIRUK RETA"
TELEBIRR_ACCOUNT = "0991983522"
TELEBIRR_NAME = "BIRUK RETA"

CARD_PRICE = 10.0
COMMISSION_RATE = 0.10  # 10% የቦት ኮሚሽን
MAX_CARDS_PER_PLAYER = 2 
MIN_WITHDRAWAL = 50.0   # ዝቅተኛው ዊዝድሮው
MILESTONE_REFERRAL_TARGET = 100  # 100 ሰው ሲጋብዝ
MILESTONE_BONUS = 500.0          # 500 ብር ቦነስ

OPERATOR_IMAGE_URL = os.environ.get("OPERATOR_IMAGE_URL", "https://i.ibb.co/6y4GfJ2/customer-service-operator.jpg")

# DATABASE, LOCKS & USER STATES
db_lock = Lock()
users_db = {}            
user_states = {}         
deposit_data = {}        
withdraw_data = {}       
admin_reply_state = {}   
pending_deposits = {}    
pending_withdrawals = {} 
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

def get_letter_and_display(num):
    if num >= 1 and num <= 15: return {'letter': 'B', 'display': f'B-{num}'}
    if num >= 16 and num <= 30: return {'letter': 'I', 'display': f'I-{num}'}
    if num >= 31 and num <= 45: return {'letter': 'N', 'display': f'N-{num}'}
    if num >= 46 and num <= 60: return {'letter': 'G', 'display': f'G-{num}'}
    if num >= 61 and num <= 75: return {'letter': 'O', 'display': f'O-{num}'}
    return {'letter': '', 'display': str(num)}

# =========================================================
# 3. GAME STATE & BINGO WINNER CHECKER
# =========================================================
game_state = {
    "status": "WAITING",
    "time_left": 15,
    "drawn_numbers": [],
    "selected_cards": {},  
    "player_cards": {},    
    "derash": 0.0
}

def validate_bingo_board(board):
    if not board or len(board) != 5:
        return False
    for r in range(5):
        if all(board[r][c] for c in range(5)): return True
    for c in range(5):
        if all(board[r][c] for r in range(5)): return True
    if all(board[i][i] for i in range(5)): return True
    if all(board[i][4 - i] for i in range(5)): return True
    return False

# =========================================================
# 4. FRONTEND HTML TEMPLATE (DASHBOARD & GAME UI)
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
        }
        .card-btn-taken {
            background: #334155 !important;
            color: #64748b !important;
            cursor: not-allowed;
            opacity: 0.6;
        }
        .bingo-hit { 
            background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important; 
            color: #ffffff !important; 
            font-weight: 800 !important;
        }
        .bingo-header-b { background: #ef4444; color: #fff; }
        .bingo-header-i { background: #3b82f6; color: #fff; }
        .bingo-header-n { background: #eab308; color: #000; }
        .bingo-header-g { background: #10b981; color: #fff; }
        .bingo-header-o { background: #a855f7; color: #fff; }
    </style>
</head>
<body class="select-none pb-10 px-3">
    
    <!-- DASHBOARD VIEW (IMAGE 2 STYLE) -->
    <div id="dashboard-view" class="max-w-md mx-auto pt-2">
        <!-- HEADER LOGO CARD -->
        <div class="glass-panel rounded-3xl p-5 mb-3 border border-purple-500/30 text-center relative overflow-hidden">
            <div class="w-16 h-16 mx-auto rounded-2xl bg-gradient-to-tr from-purple-600 to-amber-400 flex items-center justify-center text-3xl shadow-lg mb-3">🎯</div>
            <h1 class="font-orbitron text-xl font-black gold-gradient-text tracking-wider">BKBINGO PRO</h1>
            <p class="text-[11px] text-purple-300/80 font-semibold mt-1">MAIN DASHBOARD • LIVE CASINO BINGO</p>
        </div>

        <!-- PROMO BANNER -->
        <div class="bg-gradient-to-r from-purple-900/80 via-slate-900 to-emerald-950 border border-purple-500/40 p-3.5 rounded-2xl mb-3 flex items-center gap-3 shadow-lg">
            <div class="text-2xl">✨</div>
            <div class="text-xs">
                <span class="font-bold text-amber-400 block">እንኳን ወደ BKBINGO PRO በሰላም መጡ!</span>
                <span class="text-slate-300 text-[10px]">ጨዋታውን ይጀምሩ! በመጀመሪያው መጀመሪያ <b class="text-emerald-400">50 ብር </b> ቦነስ ተሰጥቶዎታል።</span>
            </div>
        </div>

        <!-- MAIN ACTION BUTTONS -->
        <button onclick="startPlaying()" class="w-full py-3.5 mb-2.5 bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-700 hover:from-indigo-500 hover:to-purple-600 text-white font-black text-sm rounded-2xl shadow-xl shadow-purple-900/30 border border-purple-400/40 flex items-center justify-center gap-2">
            🎲 ጨዋታውን ጀምር (Play)
        </button>

        <button onclick="openAdminPanel()" id="admin-btn" class="hidden w-full py-3.5 mb-3 bg-gradient-to-r from-rose-600 to-orange-600 text-white font-black text-sm rounded-2xl shadow-xl shadow-rose-900/30 border border-rose-400/40 flex items-center justify-center gap-2">
            🔑 አድሚን ፓነል (Admin Panel)
        </button>

        <!-- GRID MENU OPTIONS -->
        <div class="grid grid-cols-2 gap-2.5">
            <div onclick="alert('ምናሌ: እባክዎ በቦቱ በኩል ይመዝገቡ')" class="glass-panel p-3.5 rounded-2xl border border-slate-700/60 cursor-pointer hover:border-purple-500/50 transition">
                <div class="text-xl mb-1">📄</div>
                <div class="font-bold text-xs text-slate-100">Register</div>
                <div class="text-[10px] text-slate-400">ይመዝገቡ</div>
            </div>
            <div onclick="alert('የእርስዎ ባላንስ በሂሳብ መግለጫ ይታያል')" class="glass-panel p-3.5 rounded-2xl border border-slate-700/60 cursor-pointer hover:border-purple-500/50 transition">
                <div class="text-xl mb-1">💰</div>
                <div class="font-bold text-xs text-emerald-400">Balance</div>
                <div class="text-[10px] text-slate-400">ሂሳብዎ ይመልከቱ</div>
            </div>
            <div onclick="alert('እባክዎ በቦቱ በኩል ዲፖዚት ያድርጉ')" class="glass-panel p-3.5 rounded-2xl border border-slate-700/60 cursor-pointer hover:border-purple-500/50 transition">
                <div class="text-xl mb-1">📥</div>
                <div class="font-bold text-xs text-blue-400">Deposit</div>
                <div class="text-[10px] text-slate-400">ብር ይሙቱ (Tele/CBE)</div>
            </div>
            <div onclick="alert('እባክዎ በቦቱ በኩል ዊዝድሮ ያድርጉ')" class="glass-panel p-3.5 rounded-2xl border border-slate-700/60 cursor-pointer hover:border-purple-500/50 transition">
                <div class="text-xl mb-1">📤</div>
                <div class="font-bold text-xs text-amber-400">Withdraw</div>
                <div class="text-[10px] text-slate-400">ገንዘብ ያውጡ (Tele/CBE)</div>
            </div>
        </div>

        <!-- FULL WIDTH LIST MENUS -->
        <div class="mt-2.5 space-y-2">
            <div onclick="alert('የግብይት እና ጨዋታ ታሪክዎ በቦቱ ውስጥ ይገኛል')" class="glass-panel p-3.5 rounded-2xl border border-slate-700/60 flex justify-between items-center cursor-pointer">
                <div>
                    <div class="font-bold text-xs text-slate-100">History</div>
                    <div class="text-[10px] text-slate-400">የግብይት እና ጨዋታ ታሪክ</div>
                </div>
                <span class="text-slate-400">›</span>
            </div>
            
            <div class="grid grid-cols-2 gap-2.5">
                <div onclick="alert('ህጎች: የካርቴላ ዋጋ 10 ብር ነው።')" class="glass-panel p-3 rounded-2xl border border-slate-700/60 cursor-pointer">
                    <div class="font-bold text-xs text-cyan-400">Instruction</div>
                    <div class="text-[10px] text-slate-400">ህጎች እና መመሪያ</div>
                </div>
                <div onclick="alert('የደንበኞች አገልግሎት: @BkbingosupportBot')" class="glass-panel p-3 rounded-2xl border border-slate-700/60 cursor-pointer">
                    <div class="font-bold text-xs text-purple-400">Support</div>
                    <div class="text-[10px] text-slate-400">የደንበኞች አገልግሎት</div>
                </div>
            </div>
        </div>
    </div>

    <!-- ACTUAL GAMEPLAY INTERFACE (HIDDEN INITIALLY) -->
    <div id="game-view" class="hidden">
        <!-- HEADER -->
        <div class="relative overflow-hidden rounded-2xl mt-2 mb-3 border border-purple-500/30 glass-panel">
            <div class="p-3.5 flex justify-between items-center">
                <div class="flex items-center gap-2 cursor-pointer" onclick="backToDashboard()">
                    <div class="w-9 h-9 rounded-xl bg-slate-800 flex items-center justify-center font-black">⬅️</div>
                    <div>
                        <h1 class="font-orbitron text-sm font-black gold-gradient-text">BKBINGO PRO</h1>
                        <p class="text-[9px] text-purple-300">ወደ ዋናው ገጽ ተመለስ</p>
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
                <div class="w-1/3 glass-panel rounded-2xl p-2 border border-slate-800">
                    <div class="text-[9px] font-bold text-center text-slate-400 mb-1">የወጡ ቁጥሮች</div>
                    <div id="bingo-75-grid" class="grid grid-cols-1 gap-1 text-center text-[9px] max-h-[35vh] overflow-y-auto"></div>
                </div>
                <div class="w-2/3 flex flex-col items-center">
                    <div id="current-ball" class="w-24 h-24 rounded-full ball-glow flex items-center justify-center text-xl font-black mb-3 border-2 border-purple-300/50 text-center px-1">
                        READY
                    </div>
                    <div id="my-cards-container" class="w-full space-y-4"></div>
                </div>
            </div>
        </div>
    </div>

    <!-- WINNER MODAL -->
    <div id="winner-modal" class="fixed inset-0 bg-slate-950/90 backdrop-blur-md flex items-center justify-center p-4 hidden z-50">
        <div class="glass-panel text-white rounded-3xl p-5 w-full max-w-sm text-center border-2 border-amber-400 shadow-2xl">
            <div class="text-4xl mb-1">🎉</div>
            <div class="text-lg font-black gold-gradient-text" id="winner-name">Winner</div>
            <div id="winner-prize" class="text-3xl font-black text-emerald-400 my-2">0 ETB</div>
            <div id="winner-card-matrix" class="glass-panel p-2 rounded-2xl my-2 border border-slate-700"></div>
            <div class="text-[10px] text-slate-400 mt-3">አዲስ ዙር በቅርቡ ይጀምራል...</div>
        </div>
    </div>

    <script>
        const socket = io();
        let userId = null;
        let takenCards = [];

        if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initDataUnsafe && window.Telegram.WebApp.initDataUnsafe.user) {
            userId = parseInt(window.Telegram.WebApp.initDataUnsafe.user.id);
            window.Telegram.WebApp.expand();
            if(userId === 855985673) {
                document.getElementById('admin-btn').classList.remove('hidden');
            }
        } else {
            const urlParams = new URLSearchParams(window.location.search);
            userId = parseInt(urlParams.get('user_id')) || 12345;
            if(userId === 855985673) {
                document.getElementById('admin-btn').classList.remove('hidden');
            }
        }

        let mySelectedCards = [];
        let drawnNumbersSet = new Set();
        let markedNumbersMap = {}; 
        let cardsDatabase = {};

        function startPlaying() {
            document.getElementById('dashboard-view').classList.add('hidden');
            document.getElementById('game-view').classList.remove('hidden');
            if (userId) socket.emit('get_user_balance', { user_id: userId });
        }

        function backToDashboard() {
            document.getElementById('game-view').classList.add('hidden');
            document.getElementById('dashboard-view').classList.remove('hidden');
        }

        function openAdminPanel() {
            alert("🔑 አድሚን ፓነል በቴሌግራም ቦት በኩል ይቆጣጠሩ!");
        }

        socket.on('connect', () => {
            if (userId) socket.emit('get_user_balance', { user_id: userId });
        });

        socket.on('balance_update', (data) => {
            if(parseInt(data.user_id) === userId) {
                document.getElementById('user-balance-disp').innerText = `${parseFloat(data.balance).toFixed(2)} ETB`;
            }
        });

        socket.on('error_msg', (data) => { alert("⚠️ " + data.msg); });
        socket.on('bingo_response', (data) => { alert(data.message); });

        function init75Grid() {
            const grid = document.getElementById('bingo-75-grid');
            grid.innerHTML = '';
            for(let i=1; i<=75; i++) {
                const cell = document.createElement('div');
                cell.id = `ball-cell-${i}`;
                cell.className = 'p-1 bg-slate-800/80 rounded text-slate-400 font-bold text-[9px]';
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
                const isTaken = takenCards.includes(i) && !isSelected;

                if (isTaken) {
                    btn.className = 'p-2 text-xs font-black rounded-xl border card-btn-taken';
                    btn.disabled = true;
                } else if (isSelected) {
                    btn.className = 'p-2 text-xs font-black rounded-xl border card-btn-selected';
                } else {
                    btn.className = 'p-2 text-xs font-black rounded-xl border bg-slate-800/80 text-slate-200 border-slate-700/60';
                    btn.onclick = () => {
                        if (mySelectedCards.length >= 2) return alert("⚠️ በአንድ ዙር ቢበዛ 2 ካርቴላ ብቻ መግዛት ይቻላል!");
                        socket.emit('select_card', { user_id: userId, card_id: i });
                    };
                }
                btn.innerText = i;
                gridContainer.appendChild(btn);
            }
        }

        socket.on('update_selected_cards', (data) => {
            takenCards = data.taken_cards || [];
            initCartelaGrid();
        });

        socket.on('card_confirmed', (data) => {
            if(!mySelectedCards.includes(data.card_id)) mySelectedCards.push(data.card_id);
            cardsDatabase[data.card_id] = data.matrix;
            if(!markedNumbersMap[data.card_id]) markedNumbersMap[data.card_id] = new Set();
            initCartelaGrid();
            renderPreviewCards();
            document.getElementById('user-balance-disp').innerText = `${parseFloat(data.new_balance).toFixed(2)} ETB`;
        });

        function createCardHTML(cid, matrix, isPlayMode = false) {
            const cardDiv = document.createElement('div');
            cardDiv.className = 'glass-panel p-2.5 rounded-2xl w-full border border-slate-700/80';
            cardDiv.innerHTML = `<div class="text-[11px] font-black text-amber-400 mb-1.5 text-center">ካርቴላ #${cid}</div>`;

            const mGrid = document.createElement('div');
            mGrid.className = 'grid grid-cols-5 gap-1 text-center font-bold text-xs bg-slate-950/80 p-1.5 rounded-xl mb-2';

            ['B','I','N','G','O'].forEach((h, idx) => {
                const cls = ['bingo-header-b','bingo-header-i','bingo-header-n','bingo-header-g','bingo-header-o'][idx];
                const hCell = document.createElement('div');
                hCell.className = `p-1 rounded-lg font-black text-[10px] ${cls}`;
                hCell.innerText = h;
                mGrid.appendChild(hCell);
            });

            matrix.forEach(row => {
                row.forEach(val => {
                    const cell = document.createElement('div');
                    const isFree = val === 'FREE';
                    const isMarked = isFree || (markedNumbersMap[cid] && markedNumbersMap[cid].has(val));

                    cell.className = `p-1.5 rounded-lg text-[10px] font-bold ${isFree ? 'bg-amber-500 text-slate-950 font-black' : (isMarked ? 'bingo-hit' : 'bg-slate-800/90 text-slate-200')}`;
                    cell.innerText = val;

                    if (isPlayMode && !isFree) {
                        cell.onclick = () => {
                            if (!drawnNumbersSet.has(val)) return alert("⚠️ ይህ ቁጥር ገና አልተጠራም!");
                            if (!markedNumbersMap[cid]) markedNumbersMap[cid] = new Set();
                            markedNumbersMap[cid].add(val);
                            cell.className = 'p-1.5 rounded-lg text-[10px] font-bold bingo-hit';
                            socket.emit('player_mark_number', { user_id: userId, card_id: cid, marked_numbers: Array.from(markedNumbersMap[cid]) });
                        };
                    }
                    mGrid.appendChild(cell);
                });
            });
            cardDiv.appendChild(mGrid);

            if (isPlayMode) {
                const claimBtn = document.createElement('button');
                claimBtn.className = 'w-full py-2 bg-gradient-to-r from-emerald-500 to-green-600 text-slate-950 font-black text-xs rounded-xl shadow-lg';
                claimBtn.innerHTML = `🎉 BINGO ለካርቴላ #${cid}`;
                claimBtn.onclick = () => {
                    const matrixData = cardsDatabase[cid];
                    const markedSet = markedNumbersMap[cid] || new Set();
                    let boardValidationMatrix = [];
                    for(let r=0; r<5; r++) {
                        let rowArr = [];
                        for(let c=0; c<5; c++) {
                            let val = matrixData[r][c];
                            rowArr.push(val === 'FREE' || markedSet.has(val));
                        }
                        boardValidationMatrix.push(rowArr);
                    }
                    socket.emit('claim_bingo', { user_id: userId, card_id: cid, board: boardValidationMatrix });
                };
                cardDiv.appendChild(claimBtn);
            }
            return cardDiv;
        }

        function renderPreviewCards() {
            const container = document.getElementById('preview-cards-container');
            container.innerHTML = '';
            mySelectedCards.forEach(cid => {
                if(cardsDatabase[cid]) container.appendChild(createCardHTML(cid, cardsDatabase[cid], false));
            });
        }

        socket.on('timer_update', (data) => {
            document.getElementById('timer').innerText = `${data.time_left}s`;
            document.getElementById('sold-count').innerText = data.sold_count;
        });

        socket.on('game_started', (data) => {
            drawnNumbersSet.clear();
            markedNumbersMap = {};
            mySelectedCards.forEach(cid => { markedNumbersMap[cid] = new Set(); });
            init75Grid();
            document.getElementById('selection-screen').classList.add('hidden');
            document.getElementById('game-screen').classList.remove('hidden');
            document.getElementById('derash-amount').innerText = `${parseFloat(data.derash).toFixed(2)} ETB`;
            
            const container = document.getElementById('my-cards-container');
            container.innerHTML = '';
            mySelectedCards.forEach(cid => {
                if(cardsDatabase[cid]) container.appendChild(createCardHTML(cid, cardsDatabase[cid], true));
            });
        });

        socket.on('new_number', (data) => {
            drawnNumbersSet.add(data.ball);
            document.getElementById('current-ball').innerText = data.display;
            document.getElementById('game-balls-count').innerText = `${drawnNumbersSet.size}/75`;
            const cell75 = document.getElementById(`ball-cell-${data.ball}`);
            if(cell75) cell75.className = 'p-1 bg-amber-400 text-slate-950 font-black rounded text-[9px]';
        });

        socket.on('winner_announced', (data) => {
            document.getElementById('winner-name').innerText = `${data.winner_name} አሸንፏል!`;
            document.getElementById('winner-prize').innerText = `${parseFloat(data.prize).toFixed(2)} ETB`;
            const wGrid = document.getElementById('winner-card-matrix');
            wGrid.innerHTML = '';
            if(data.card_matrix) wGrid.appendChild(createCardHTML(data.card_id, data.card_matrix, false));
            document.getElementById('winner-modal').classList.remove('hidden');
        });

        socket.on('reset_game', () => {
            mySelectedCards = [];
            takenCards = [];
            drawnNumbersSet.clear();
            markedNumbersMap = {};
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
# 5. TELEGRAM BOT & BACKEND HANDLERS
# =========================================================
def main_menu_keyboard(user_id):
    markup = InlineKeyboardMarkup(row_width=2)
    app_url = f"{RENDER_WEBAPP_URL}?user_id={user_id}"
    with db_lock:
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
    markup.add(InlineKeyboardButton(text="📜 የግብይት እና ጨዋታ ታሪክ (History)", callback_data="btn_history"))
    markup.add(
        InlineKeyboardButton(text="ℹ️ እርዳታ እና ህጎች", callback_data="btn_help"),
        InlineKeyboardButton(text="🎧 የደንበኞች አገልግሎት", url=support_deep_link)
    )
    return markup

def add_user_history(uid, history_type, details):
    with db_lock:
        if uid in users_db:
            if "history" not in users_db[uid]: users_db[uid]["history"] = []
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            users_db[uid]["history"].insert(0, {"time": timestamp, "type": history_type, "details": details})

@bot.message_handler(commands=['start', 'menu'])
def start_cmd(message):
    uid = int(message.from_user.id)
    first_name = message.from_user.first_name.replace('<', '&lt;').replace('>', '&gt;')
    username = (message.from_user.username or "የለውም").replace('<', '&lt;').replace('>', '&gt;')

    with db_lock:
        if uid not in users_db:
            users_db[uid] = {
                "id": uid, "name": first_name, "username": username,
                "balance": 50.0, "referred_by": None, "referral_count": 0, "history": []
            }
        bal = users_db[uid]['balance']

    welcome_txt = (
        f"👋 ሰላም <b>{first_name}</b>!\n\n"
        f"ወደ <b>BKBINGO Pro</b> እንኳን ደህና መጡ! 🎲\n"
        f"💰 ባላንስዎ፦ <b>{bal:.2f} ETB</b>\n\n"
        "ለመጫወት ከታች ያለውን <b>'🎲 ጨዋታ ጀምር'</b> የሚለውን ይጫኑ።"
    )
    bot.send_message(message.chat.id, welcome_txt, reply_markup=main_menu_keyboard(uid), parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith('btn_'))
def handle_main_menu_callbacks(call):
    uid = int(call.from_user.id)
    action = call.data
    bot.answer_callback_query(call.id)
    with db_lock:
        bal = users_db.get(uid, {}).get("balance", 0.0)

    if action == "btn_profile":
        bot.send_message(call.message.chat.id, f"👤 <b>პროფაይል</b>\n🆔 ID: <code>{uid}</code>\n💰 ባላንስ: <b>{bal:.2f} ETB</b>", parse_mode="HTML")
    elif action == "btn_deposit":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("CBE BIRR", callback_data="depmeth_cbe"), InlineKeyboardButton("TELE BIRR", callback_data="depmeth_tele"))
        bot.send_message(call.message.chat.id, "💳 የክፍያ ዘዴ ይምረጡ:", reply_markup=markup, parse_mode="HTML")
    elif action == "btn_withdraw":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton("📱 Telebirr", callback_data="wdmeth_Telebirr"), InlineKeyboardButton("🏦 CBE Birr", callback_data="wdmeth_CBE"))
        bot.send_message(call.message.chat.id, f"📤 ገንዘብ ማውጫ ዘዴ ይምረጡ፦\n💰 ባላንስ፦ <b>{bal:.2f} ETB</b>", reply_markup=markup, parse_mode="HTML")
    elif action == "btn_help":
        bot.send_message(call.message.chat.id, "ℹ️ የ BKBINGO Pro ህጎች:\n1. የካርቴላ ዋጋ 10 ETB ነው።\n2. በአንድ ዙር ቢበዛ 2 ካርቴላ መግዛት ይቻላል።", parse_mode="HTML")

@socketio.on('get_user_balance')
def handle_get_balance(data):
    if not data or 'user_id' not in data: return
    uid = int(data.get('user_id'))
    with db_lock:
        if uid not in users_db:
            users_db[uid] = {"id": uid, "name": f"User {uid}", "balance": 50.0, "history": []}
        bal = users_db[uid]["balance"]
    emit('balance_update', {'user_id': uid, 'balance': bal})

@socketio.on('select_card')
def handle_card_selection(data):
    if game_state["status"] == "PLAYING":
        return emit('error_msg', {'msg': 'ጨዋታው ተጀምሯል። እባክዎን ይጠብቁ!'})
    uid = int(data.get('user_id'))
    card_id = int(data.get('card_id'))

    with db_lock:
        if uid not in users_db: users_db[uid] = {"balance": 50.0, "history": []}
        bal = users_db[uid]["balance"]
        
        if card_id in game_state['selected_cards'].values():
            return emit('error_msg', {'msg': 'ይህ ካርቴላ አስቀድሞ ተይዟል!'})
        if len(game_state['player_cards'].get(uid, [])) >= MAX_CARDS_PER_PLAYER:
            return emit('error_msg', {'msg': 'ቢበዛ 2 ካርቴላ ብቻ መግዛት ይቻላል!'})
        if bal < CARD_PRICE:
            return emit('error_msg', {'msg': 'በቂ ባላንስ የሎትም።'})

        users_db[uid]["balance"] -= CARD_PRICE
        new_bal = users_db[uid]["balance"]
        game_state['selected_cards'][f"{uid}_{card_id}"] = card_id
        if uid not in game_state['player_cards']: game_state['player_cards'][uid] = []
        game_state['player_cards'][uid].append(card_id)

    matrix = cards_database.get(card_id)
    emit('card_confirmed', {'card_id': card_id, 'matrix': matrix, 'new_balance': new_bal})
    socketio.emit('update_selected_cards', {'taken_cards': list(game_state['selected_cards'].values())})

@socketio.on('claim_bingo')
def handle_bingo_claim(data):
    user_sid = request.sid
    uid = int(data.get('user_id'))
    card_id = int(data.get('card_id'))
    board = data.get('board')
    
    if game_state["status"] != "PLAYING":
        return emit('bingo_response', {'status': 'error', 'message': 'ጨዋታው ገና አልጀመረም!'}, room=user_sid)

    if validate_bingo_board(board):
        emit('bingo_response', {'status': 'success', 'message': 'እንኳን ደስ አለዎት! ቢንጎ አሸንፈዋል!'}, room=user_sid)
        prize = game_state['derash']
        game_state['status'] = 'ENDED'
        with db_lock:
            if uid in users_db:
                users_db[uid]["balance"] += prize
                w_name = users_db[uid].get("name", f"Player {uid}")
                socketio.emit('balance_update', {'user_id': uid, 'balance': users_db[uid]["balance"]})
            else: w_name = f"Player {uid}"

        socketio.emit('winner_announced', {'winner_ids': [uid], 'winner_name': w_name, 'prize': prize, 'card_id': card_id, 'card_matrix': cards_database.get(card_id)})
    else:
        emit('bingo_response', {'status': 'error', 'message': 'ስህተት! ገና በህጉ መሰረት ቢንጎ አልደረሱም!'}, room=user_sid)

def game_loop():
    global game_state
    while True:
        game_state["status"] = "WAITING"
        game_state["time_left"] = 15
        game_state["selected_cards"] = {}
        game_state["player_cards"] = {}
        game_state["drawn_numbers"] = []
        socketio.emit('reset_game')
        socketio.emit('update_selected_cards', {'taken_cards': []})

        while len(game_state["selected_cards"]) == 0:
            socketio.sleep(1)

        game_state["status"] = "COUNTDOWN"
        for t in range(15, 0, -1):
            if len(game_state["selected_cards"]) == 0: break
            socketio.emit('timer_update', {'time_left': t, 'sold_count': len(game_state["selected_cards"])})
            socketio.sleep(1)

        game_state["status"] = "PLAYING"
        total_pool = len(game_state["selected_cards"]) * CARD_PRICE
        derash = total_pool * (1 - COMMISSION_RATE)
        game_state["derash"] = derash

        socketio.emit('game_started', {'status': 'PLAYING', 'derash': derash})
        available_balls = list(range(1, 76))
        random.shuffle(available_balls)

        for ball in available_balls:
            if game_state["status"] != "PLAYING": break
            game_state["drawn_numbers"].append(ball)
            ball_info = get_letter_and_display(ball)
            socketio.emit('new_number', {'ball': ball, 'display': ball_info['display']})
            socketio.sleep(30)

        if game_state["status"] == "PLAYING":
            game_state["status"] = "ENDED"
            socketio.emit('winner_announced', {'winner_ids': [], 'winner_name': 'ምንም አሸናፊ የለም (Draw)', 'prize': 0.0, 'card_id': 0, 'card_matrix': None})

        socketio.sleep(8)

if __name__ == '__main__':
    Thread(target=lambda: bot.infinity_polling(skip_pending=True), daemon=True).start()
    socketio.start_background_task(game_loop)
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
