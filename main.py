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
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, BotCommand
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

RENDER_WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://bingo-bot-c90r.onrender.com")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "855985673"))

# PAYMENT ACCOUNTS (MANUAL DEPOSIT & SMS VERIFICATION)
CBE_ACCOUNT = "0991983522"
CBE_NAME = "BIRUK RETA"
TELEBIRR_ACCOUNT = "0991983522"
TELEBIRR_NAME = "BIRUK RETA"

CARD_PRICE = 10.0
COMMISSION_RATE = 0.10  # 10% የቦት ኮሚሽን
AGENT_COMMISSION_RATE = 0.05 # ከኤጀንት ተጫዋቾች የሚገኝ 5% ኮሚሽን
MAX_CARDS_PER_PLAYER = 2 
MIN_WITHDRAWAL = 50.0   # ዝቅተኛው ዊዝድሮው
MILESTONE_REFERRAL_TARGET = 100  # 100 ሰው ሲጋብዝ
MILESTONE_BONUS = 500.0          # 500 ብር ቦነስ

OPERATOR_IMAGE_URL = os.environ.get("OPERATOR_IMAGE_URL", "https://i.ibb.co/6y4GfJ2/customer-service-operator.jpg")

# DATABASE, LOCKS & USER STATES
db_lock = Lock()
users_db = {}            
agents_db = {}           
user_states = {}         
deposit_data = {}        
withdraw_data = {}       
admin_reply_state = {}   
pending_deposits = {}    
pending_withdrawals = {} 
used_txn_ids = set()     
broadcast_state = {}     
player_marked_hits = {}

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
    "selected_cards": {},  
    "player_cards": {},    
    "derash": 0.0
}

def validate_bingo_board(board):
    if not board or len(board) != 5:
        return False
    for r in range(5):
        if all(board[r][c] for c in range(5)):
            return True
    for c in range(5):
        if all(board[r][c] for r in range(5)):
            return True
    if all(board[i][i] for i in range(5)):
        return True
    if all(board[i][4 - i] for i in range(5)):
        return True
    return False

# =========================================================
# 4. FRONTEND HTML TEMPLATE (ENHANCED UI / UX)
# =========================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="am">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>BKBINGO Pro - Ultimate Experience</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Cinzel+Decorative:wght@700&family=Orbitron:wght@700;900&family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        body { 
            font-family: 'Plus Jakarta Sans', sans-serif; 
            background: radial-gradient(circle at top, #1e1b4b 0%, #0f172a 50%, #020617 100%);
            color: #f8fafc; 
            min-height: 100vh; 
        }
        .font-orbitron { font-family: 'Orbitron', sans-serif; }
        .font-cinzel { font-family: 'Cinzel Decorative', cursive; }
        .glass-panel { 
            background: rgba(30, 41, 59, 0.75); 
            backdrop-filter: blur(20px); 
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.12); 
            box-shadow: 0 10px 40px 0 rgba(0, 0, 0, 0.5);
        }
        .gold-gradient-text { 
            background: linear-gradient(135deg, #fffbeb 0%, #fde047 30%, #eab308 70%, #ca8a04 100%); 
            -webkit-background-clip: text; 
            -webkit-text-fill-color: transparent; 
            filter: drop-shadow(0 2px 4px rgba(234, 179, 8, 0.3));
        }
        .ball-glow { 
            background: radial-gradient(circle at 35% 35%, #c084fc 0%, #9333ea 50%, #581c87 100%);
            box-shadow: 0 0 30px rgba(168, 85, 247, 0.7), inset 0 0 15px rgba(255, 255, 255, 0.4);
        }
        .card-btn-selected { 
            background: linear-gradient(135deg, #059669 0%, #047857 100%) !important; 
            color: #ffffff !important; 
            border-color: #34d399 !important;
            box-shadow: 0 0 15px rgba(16, 185, 129, 0.6);
            transform: scale(1.02);
        }
        .card-btn-taken {
            background: #1e293b !important;
            color: #475569 !important;
            border-color: #0f172a !important;
            cursor: not-allowed;
            opacity: 0.5;
        }
        .bingo-hit { 
            background: linear-gradient(135deg, #10b981 0%, #047857 100%) !important; 
            color: #ffffff !important; 
            font-weight: 800 !important;
            box-shadow: inset 0 0 10px rgba(255, 255, 255, 0.6);
            animation: pulse-hit 0.3s ease-in-out;
        }
        @keyframes pulse-hit {
            0% { transform: scale(0.95); }
            50% { transform: scale(1.08); }
            100% { transform: scale(1); }
        }
        .bingo-header-b { background: linear-gradient(135deg, #f87171, #dc2626); color: #fff; }
        .bingo-header-i { background: linear-gradient(135deg, #60a5fa, #2563eb); color: #fff; }
        .bingo-header-n { background: linear-gradient(135deg, #facc15, #ca8a04); color: #1e1b4b; }
        .bingo-header-g { background: linear-gradient(135deg, #34d399, #059669); color: #fff; }
        .bingo-header-o { background: linear-gradient(135deg, #c084fc, #9333ea); color: #fff; }

        .stat-card {
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            padding: 10px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: rgba(15, 23, 42, 0.6);
        }
        .bingo-cell-custom {
            font-size: 13px; 
            font-weight: 600; 
            padding: 12px 2px;
            transition: all 0.2s ease;
        }
    </style>
</head>
<body class="select-none pb-12 px-3">
    <!-- Audio Banner -->
    <div id="audio-banner" class="bg-gradient-to-r from-amber-500 to-yellow-400 p-2 my-2 rounded-xl flex justify-between items-center shadow-lg animate-bounce">
        <span class="text-slate-950 font-black text-xs">🔊 የድምፅ ማስታወቂያ እና ሐሴት ለማንቃት ይጫኑ!</span>
        <button onclick="enableAudioSystem()" class="bg-slate-950 text-amber-300 px-3 py-1 rounded-lg font-black text-[11px] shadow">አንቃ (Enable)</button>
    </div>

    <!-- Header Brand Panel -->
    <div class="relative overflow-hidden rounded-3xl my-2 border border-purple-500/30 glass-panel p-4">
        <div class="flex justify-between items-center">
            <div class="flex items-center gap-3">
                <div class="w-12 h-12 rounded-2xl bg-gradient-to-tr from-purple-600 via-indigo-600 to-amber-400 flex items-center justify-center text-2xl shadow-xl border border-white/20">🎲</div>
                <div>
                    <h1 class="font-orbitron text-lg font-black gold-gradient-text tracking-wider">BKBINGO PRO</h1>
                    <p class="text-[10px] text-purple-200 font-semibold tracking-widest">🌟 VIP LIVE BINGO CASINO 🌟</p>
                </div>
            </div>
            <div class="flex flex-col items-end gap-1.5">
                <div class="bg-slate-900/90 border border-slate-700 px-2.5 py-1 rounded-xl flex items-center gap-2 shadow-inner">
                    <span class="text-[10px] text-slate-300 font-bold">🤖 Auto-Daub</span>
                    <input type="checkbox" id="auto-daub-toggle" class="w-4 h-4 accent-emerald-500 cursor-pointer" onchange="toggleAutoDaub(this)">
                </div>
                <div class="bg-emerald-500/20 border border-emerald-500/40 px-3 py-1 rounded-xl text-right shadow-lg">
                    <div class="text-[9px] text-emerald-300 font-bold uppercase tracking-wider">ሒሳብ (Balance)</div>
                    <div id="user-balance-disp" class="text-xs font-black text-emerald-400">0.00 ETB</div>
                </div>
            </div>
        </div>
    </div>

    <!-- Stats Bar -->
    <div class="grid grid-cols-3 gap-2 mb-3 text-center">
        <div class="stat-card border-l-4 border-amber-400 shadow-lg">
            <span class="text-[10px] text-slate-400 font-bold mb-0.5">🎟️ የተሸጡ ካርቴላ</span>
            <span id="sold-count" class="text-amber-400 text-base font-black">0</span>
        </div>
        <div class="stat-card border-l-4 border-rose-500 shadow-lg">
            <span class="text-[10px] text-slate-400 font-bold mb-0.5">⏳ የቀረ ጊዜ</span>
            <span id="timer" class="text-rose-400 text-base font-black">15s</span>
        </div>
        <div class="stat-card border-l-4 border-purple-500 shadow-lg">
            <span class="text-[10px] text-slate-400 font-bold mb-0.5">🎯 የወጡ ኳሶች</span>
            <span id="balls-count" class="text-purple-300 text-base font-black">0/75</span>
        </div>
    </div>

    <!-- Selection Screen -->
    <div id="selection-screen">
        <div class="flex justify-between items-center mb-2 px-1">
            <span class="text-xs font-bold text-slate-200 flex items-center gap-1">✨ እድለኛ ካርቴላ ይምረጡ (1-104)</span>
            <span class="text-[11px] font-extrabold text-amber-300 bg-amber-500/20 px-3 py-1 rounded-full border border-amber-500/40 shadow">💎 ዋጋ: 10 ETB</span>
        </div>

        <div id="cartela-grid" class="grid grid-cols-8 gap-1.5 glass-panel p-3 rounded-3xl max-h-[38vh] overflow-y-auto border border-slate-700 shadow-2xl"></div>
        <p class="text-center text-[11px] text-amber-300/90 font-semibold my-2">⚠️ በአንድ ዙር መግዛት የሚችሉት ቢበዛ 2 ካርቴላዎች ብቻ ናቸው።</p>
        
        <div id="preview-cards-container" class="grid grid-cols-1 gap-3 mt-3"></div>
    </div>

    <!-- Game Screen -->
    <div id="game-screen" class="hidden mt-2">
        <div class="glass-panel p-3.5 rounded-2xl mb-3 flex justify-between items-center border border-emerald-500/40 shadow-xl">
            <div>
                <span class="text-[10px] text-slate-400 font-bold uppercase">🏆 የአሸናፊው ደራሽ (PRIZE)</span>
                <span class="text-lg font-black text-emerald-400" id="derash-amount">0 ETB</span>
            </div>
            <div class="text-right">
                <span class="text-[10px] text-slate-400 font-bold uppercase">🎯 የተጠራው ኳስ</span>
                <span id="game-balls-count" class="text-sm font-extrabold text-purple-300">0/75</span>
            </div>
        </div>

        <div class="flex gap-2">
            <div class="w-1/3 glass-panel rounded-2xl p-2 border border-slate-700 shadow-lg">
                <div class="text-[10px] font-extrabold text-center text-amber-300 mb-1.5 uppercase">📋 የወጡ ቁጥሮች</div>
                <div id="bingo-75-grid" class="grid grid-cols-1 gap-1 text-center text-[10px] max-h-[42vh] overflow-y-auto"></div>
            </div>

            <div class="w-2/3 flex flex-col items-center">
                <div id="current-ball" class="w-24 h-24 rounded-full ball-glow flex items-center justify-center text-xl font-black mb-3 border-4 border-purple-300/60 transform transition-all duration-300 text-center px-1 text-white shadow-2xl">
                    READY
                </div>
                <div id="my-cards-container" class="w-full space-y-3"></div>
            </div>
        </div>
    </div>

    <!-- Winner Modal -->
    <div id="winner-modal" class="fixed inset-0 bg-slate-950/90 backdrop-blur-xl flex items-center justify-center p-4 hidden z-50">
        <div class="glass-panel text-white rounded-3xl p-6 w-full max-w-sm text-center border-2 border-amber-400 shadow-2xl animate-pulse">
            <div class="text-5xl mb-2">🎉🏆✨</div>
            <div class="text-xl font-black gold-gradient-text" id="winner-name">Winner</div>
            <div id="winner-prize" class="text-4xl font-black text-emerald-400 my-3">0 ETB</div>
            
            <div class="text-xs font-bold text-slate-200 mt-3 mb-1">🌟 የአሸናፊው ካርቴላ 🌟</div>
            <div id="winner-card-matrix" class="glass-panel p-2 rounded-2xl my-2 border border-slate-600 shadow-inner"></div>
            <div class="text-[11px] text-amber-300 font-bold mt-3">🚀 አዲስ ዙር በቅርቡ ይጀምራል...</div>
        </div>
    </div>

    <script>
        const sounds = {
            click: new Audio('https://assets.mixkit.co/active_storage/sfx/2568/2568-preview.mp3'),
            win: new Audio('https://assets.mixkit.co/active_storage/sfx/2701/2701-preview.mp3'),
            error: new Audio('https://assets.mixkit.co/active_storage/sfx/2572/2572-preview.mp3')
        };

        function playSound(effectName) {
            if (sounds[effectName]) {
                sounds[effectName].currentTime = 0;
                sounds[effectName].volume = 0.6;
                sounds[effectName].play().catch(e => console.log("Audio restriction:", e));
            }
        }

        let speechUnlocked = false;
        let isAutoDaubEnabled = false;

        function toggleAutoDaub(checkbox) {
            isAutoDaubEnabled = checkbox.checked;
            playSound('click');
        }

        function enableAudioSystem() {
            if ('speechSynthesis' in window) {
                const utterance = new SpeechSynthesisUtterance("ድምፅ እና የጨዋታ ስርዓቱ ተጀምሯል");
                utterance.lang = 'am-ET';
                utterance.volume = 1.0;
                window.speechSynthesis.speak(utterance);
                speechUnlocked = true;
                const banner = document.getElementById('audio-banner');
                if (banner) banner.style.display = 'none';
            }
        }

        function speakNumber(ballNum, displayStr) {
            if (!('speechSynthesis' in window)) return;
            let letterName = '';
            if (ballNum >= 1 && ballNum <= 15) letterName = 'ቢ';
            else if (ballNum >= 16 && ballNum <= 30) letterName = 'አይ';
            else if (ballNum >= 31 && ballNum <= 45) letterName = 'ኤን';
            else if (ballNum >= 46 && ballNum <= 60) letterName = 'ጂ';
            else if (ballNum >= 61 && ballNum <= 75) letterName = 'ኦ';

            const phrase = `${letterName} ${ballNum}`;
            try {
                window.speechSynthesis.cancel();
                const utterance = new SpeechSynthesisUtterance(phrase);
                utterance.lang = 'am-ET';
                utterance.rate = 0.85;
                utterance.pitch = 1.0;
                utterance.volume = 1.0;
                window.speechSynthesis.speak(utterance);
            } catch (e) {
                console.log("Speech error:", e);
            }
        }

        document.addEventListener('click', () => {
            if (!speechUnlocked && 'speechSynthesis' in window) {
                enableAudioSystem();
            }
        }, { once: true });

        const socket = io();
        let userId = null;
        let takenCards = [];

        if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initDataUnsafe && window.Telegram.WebApp.initDataUnsafe.user) {
            userId = parseInt(window.Telegram.WebApp.initDataUnsafe.user.id);
            window.Telegram.WebApp.expand();
        } else {
            const urlParams = new URLSearchParams(window.location.search);
            userId = parseInt(urlParams.get('user_id')) || 12345;
        }

        let mySelectedCards = [];
        let drawnNumbersSet = new Set();
        let markedNumbersMap = {}; 
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
            playSound('error');
            alert("⚠️ " + data.msg);
        });

        socket.on('bingo_response', (data) => {
            if (data.status === 'success') {
                playSound('win');
            } else {
                playSound('error');
            }
            alert(data.message);
        });

        function getFrontendLetterAndDisplay(num) {
            if (num >= 1 && num <= 15) return `B-${num}`;
            if (num >= 16 && num <= 30) return `I-${num}`;
            if (num >= 31 && num <= 45) return `N-${num}`;
            if (num >= 46 && num <= 60) return `G-${num}`;
            if (num >= 61 && num <= 75) return `O-${num}`;
            return `${num}`;
        }

        function init75Grid() {
            const grid = document.getElementById('bingo-75-grid');
            grid.innerHTML = '';
            for(let i=1; i<=75; i++) {
                const cell = document.createElement('div');
                cell.id = `ball-cell-${i}`;
                cell.className = 'p-1.5 bg-slate-900/90 rounded-lg text-slate-400 font-bold text-[10px] border border-slate-800';
                cell.innerText = getFrontendLetterAndDisplay(i);
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
                    btn.className = 'p-2 text-xs font-black rounded-xl border bg-slate-800/90 text-slate-100 border-slate-700 hover:bg-slate-700 active:scale-95 transition-all shadow-md';
                    btn.onclick = () => {
                        if (mySelectedCards.length >= 2) {
                            playSound('error');
                            return alert("⚠️ በአንድ ዙር ቢበዛ 2 ካርቴላ ብቻ መግዛት ይቻላል!");
                        }
                        playSound('click');
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
            playSound('click');
            if(!mySelectedCards.includes(data.card_id)) mySelectedCards.push(data.card_id);
            cardsDatabase[data.card_id] = data.matrix;
            if(!markedNumbersMap[data.card_id]) markedNumbersMap[data.card_id] = new Set();
            initCartelaGrid();
            renderPreviewCards();
            document.getElementById('user-balance-disp').innerText = `${parseFloat(data.new_balance).toFixed(2)} ETB`;
        });

        function createCardHTML(cid, matrix, isPlayMode = false) {
            const cardDiv = document.createElement('div');
            cardDiv.className = 'glass-panel p-3.5 rounded-3xl w-full border border-slate-700/80 bingo-card-container shadow-xl';
            cardDiv.innerHTML = `<div class="text-xs font-black text-amber-300 mb-2.5 text-center tracking-wider">🌟 የካርቴላ ቁጥር #${cid} 🌟</div>`;

            const mGrid = document.createElement('div');
            mGrid.className = 'grid grid-cols-5 gap-1.5 text-center font-bold text-xs bg-slate-950/90 p-2.5 rounded-2xl mb-3 border border-slate-800 shadow-inner';

            const headers = [
                { title: 'B', class: 'bingo-header-b' },
                { title: 'I', class: 'bingo-header-i' },
                { title: 'N', class: 'bingo-header-n' },
                { title: 'G', class: 'bingo-header-g' },
                { title: 'O', class: 'bingo-header-o' }
            ];

            headers.forEach(h => {
                const hCell = document.createElement('div');
                hCell.className = `py-1.5 rounded-xl font-black text-xs shadow-md ${h.class}`;
                hCell.innerText = h.title;
                mGrid.appendChild(hCell);
            });

            matrix.forEach(row => {
                row.forEach(val => {
                    const cell = document.createElement('div');
                    if(isPlayMode) cell.id = `card-${cid}-val-${val}`;
                    
                    const isFree = val === 'FREE';
                    const isMarked = isFree || (markedNumbersMap[cid] && markedNumbersMap[cid].has(val));

                    cell.className = `rounded-xl bingo-cell-custom shadow-sm ${
                        isFree 
                        ? 'bg-gradient-to-tr from-amber-500 to-yellow-300 text-slate-950 font-black text-xs shadow-amber-500/50' 
                        : (isMarked ? 'bingo-hit' : 'bg-slate-900/90 text-slate-100 hover:bg-slate-800 cursor-pointer border border-slate-800')
                    }`;
                    cell.innerText = val;

                    if (isPlayMode && !isFree) {
                        cell.onclick = () => {
                            if (!drawnNumbersSet.has(val)) {
                                playSound('error');
                                return alert("⚠️ ይህ ቁጥር ገና አልተጠራም!");
                            }
                            playSound('click');
                            if (!markedNumbersMap[cid]) markedNumbersMap[cid] = new Set();
                            markedNumbersMap[cid].add(val);
                            
                            cell.className = 'rounded-xl bingo-cell-custom bingo-hit scale-105 transition-all';
                            
                            socket.emit('player_mark_number', {
                                user_id: userId,
                                card_id: cid,
                                marked_numbers: Array.from(markedNumbersMap[cid])
                            });
                        };
                    }
                    mGrid.appendChild(cell);
                });
            });

            cardDiv.appendChild(mGrid);

            if (isPlayMode) {
                const claimBtn = document.createElement('button');
                claimBtn.className = 'w-full py-2.5 bg-gradient-to-r from-emerald-500 via-green-500 to-teal-600 hover:from-emerald-400 hover:to-green-500 text-slate-950 font-black text-xs rounded-2xl shadow-lg shadow-emerald-500/30 border border-emerald-300 transform active:scale-95 transition-all';
                claimBtn.innerHTML = `🎉 BINGO! (ካርቴላ #${cid})`;
                claimBtn.onclick = () => {
                    playSound('click');
                    const matrixData = cardsDatabase[cid];
                    const markedSet = markedNumbersMap[cid] || new Set();

                    let boardValidationMatrix = [];
                    for(let r=0; r<5; r++) {
                        let rowArr = [];
                        for(let c=0; c<5; c++) {
                            let val = matrixData[r][c];
                            let isHit = (val === 'FREE' || markedSet.has(val));
                            rowArr.push(isHit);
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
            markedNumbersMap = {};
            mySelectedCards.forEach(cid => { markedNumbersMap[cid] = new Set(); });
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
            const displayStr = data.display;
            drawnNumbersSet.add(ball);
            
            speakNumber(ball, displayStr);

            const ballEl = document.getElementById('current-ball');
            ballEl.innerText = displayStr;
            ballEl.classList.add('scale-110');
            setTimeout(() => ballEl.classList.remove('scale-110'), 200);

            document.getElementById('game-balls-count').innerText = `${drawnNumbersSet.size}/75`;
            
            const cell75 = document.getElementById(`ball-cell-${ball}`);
            if(cell75) {
                cell75.className = 'p-1.5 bg-gradient-to-tr from-amber-400 to-yellow-300 text-slate-950 font-black rounded-lg shadow-lg scale-105 transition-all text-[10px] border border-amber-200';
            }

            if (isAutoDaubEnabled) {
                mySelectedCards.forEach(cid => {
                    const matrix = cardsDatabase[cid];
                    if (!matrix) return;
                    matrix.forEach(row => {
                        row.forEach(val => {
                            if (val === ball) {
                                if (!markedNumbersMap[cid]) markedNumbersMap[cid] = new Set();
                                markedNumbersMap[cid].add(val);

                                const cellEl = document.getElementById(`card-${cid}-val-${val}`);
                                if (cellEl) {
                                    cellEl.className = 'rounded-xl bingo-cell-custom bingo-hit scale-105 transition-all';
                                }

                                socket.emit('player_mark_number', {
                                    user_id: userId,
                                    card_id: cid,
                                    marked_numbers: Array.from(markedNumbersMap[cid])
                                });
                            }
                        });
                    });
                });
            }
        });

        socket.on('winner_announced', (data) => {
            playSound('win');
            document.getElementById('winner-name').innerText = `${data.winner_name} አሸንፏል! 🏆`;
            document.getElementById('winner-prize').innerText = `${parseFloat(data.prize).toFixed(2)} ETB`;
            
            if(data.winner_ids && data.winner_ids.includes(userId)) {
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

AGENT_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="am">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BKBINGO Pro - Advanced Agent Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Plus Jakarta Sans', sans-serif; background: #0f172a; color: #f8fafc; min-height: 100vh; }
        .glass-panel { background: rgba(30, 41, 59, 0.8); backdrop-filter: blur(20px); border: 1px solid rgba(255, 255, 255, 0.12); box-shadow: 0 10px 30px rgba(0,0,0,0.4); }
        .tab-btn { transition: all 0.2s ease; }
        .tab-btn.active { background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); color: #0f172a; font-weight: 800; box-shadow: 0 0 15px rgba(245, 158, 11, 0.4); }
    </style>
</head>
<body class="p-3 pb-12">
    <div class="max-w-md mx-auto">
        <!-- Header -->
        <div class="glass-panel p-4 rounded-3xl mb-3 text-center border border-purple-500/30">
            <h1 class="text-base font-black text-amber-300">🤝 BKBINGO AGENT PANEL 🤝</h1>
            <p class="text-[11px] text-slate-300 mt-0.5">የኤጀንት የላቀ የቁጥጥር እና የገቢ ማዕከል</p>
        </div>

        <!-- Top Balances & Stats -->
        <div class="grid grid-cols-2 gap-2.5 mb-3">
            <div class="glass-panel p-3.5 rounded-2xl text-center border-l-4 border-emerald-400 shadow-lg">
                <span class="text-[10px] text-slate-300 font-bold block mb-1">💰 የኮሚሽን ባላንስ</span>
                <span id="agent-bal" class="text-sm font-black text-emerald-400">0.00 ETB</span>
                <button onclick="withdrawCommission()" class="mt-2.5 w-full py-1.5 bg-gradient-to-r from-emerald-500 to-green-600 hover:from-emerald-400 hover:to-green-500 text-slate-950 font-black text-[11px] rounded-xl shadow">Withdraw</button>
            </div>
            <div class="glass-panel p-3.5 rounded-2xl text-center border-l-4 border-amber-400 shadow-lg">
                <span class="text-[10px] text-slate-300 font-bold block mb-1">👥 የተጋበዙ ተጫዋቾች</span>
                <span id="agent-refs" class="text-base font-black text-amber-400">0</span>
                <span class="text-[9px] text-slate-400 block mt-2 font-semibold">አጠቃላይ ተሳታፊዎች</span>
            </div>
        </div>

        <!-- Navigation Tabs -->
        <div class="grid grid-cols-4 gap-1 mb-3 glass-panel p-1.5 rounded-2xl text-xs font-bold text-center">
            <button onclick="switchTab('overview')" id="tab-overview" class="tab-btn active py-2 rounded-xl">ዳሽቦርድ</button>
            <button onclick="switchTab('topup')" id="tab-topup" class="tab-btn py-2 rounded-xl text-slate-300">ዲፖዚት</button>
            <button onclick="switchTab('players')" id="tab-players" class="tab-btn py-2 rounded-xl text-slate-300">ተጫዋቾች</button>
            <button onclick="switchTab('support')" id="tab-support" class="tab-btn py-2 rounded-xl text-slate-300">ድጋፍ</button>
        </div>

        <!-- TAB 1: OVERVIEW & LIVE MONITOR & CHART -->
        <div id="section-overview" class="space-y-3">
            <div class="glass-panel p-3.5 rounded-3xl border border-purple-500/30">
                <h2 class="text-xs font-bold text-amber-300 mb-2">📊 የዕለቱ የሽያጭ እና ኮሚሽን ማጠቃለያ</h2>
                <canvas id="earningsChart" height="120"></canvas>
            </div>

            <div class="glass-panel p-3.5 rounded-3xl border border-slate-700">
                <h2 class="text-xs font-bold text-slate-200 mb-2">🎯 የሎተሪ እና ቢንጎ ዙር መቆጣጠሪያ (Live Monitor)</h2>
                <div class="grid grid-cols-2 gap-2 text-center text-xs">
                    <div class="bg-slate-900/90 p-3 rounded-2xl border border-slate-800">
                        <span class="text-[10px] text-slate-400 block mb-1">የጨዋታ ሁኔታ</span>
                        <span id="live-status" class="text-emerald-400 font-black">መጠባበቂያ (WAITING)</span>
                    </div>
                    <div class="bg-slate-900/90 p-3 rounded-2xl border border-slate-800">
                        <span class="text-[10px] text-slate-400 block mb-1">የተሸጡ ካርቴላዎች</span>
                        <span id="live-sold" class="text-amber-400 font-black">0</span>
                    </div>
                </div>
            </div>

            <div class="glass-panel p-3.5 rounded-3xl">
                <h2 class="text-xs font-bold text-slate-200 mb-1.5">🔗 የእርስዎ ልዩ የኤጀንት ሊንክ</h2>
                <div class="bg-slate-950 p-3 rounded-2xl text-[11px] text-amber-300 break-all select-all border border-slate-800 shadow-inner" id="agent-link-text">
                    ሎዲንግ...
                </div>
            </div>
        </div>

        <!-- TAB 2: INSTANT TOP-UP & PAYOUT -->
        <div id="section-topup" class="glass-panel p-4 rounded-3xl hidden space-y-3">
            <h2 class="text-xs font-bold text-amber-400 mb-1">⚡ ፈጣን የዲፖዚት እና ዊዝድሮቫል ማስተናገጃ</h2>
            <p class="text-[10px] text-slate-300 mb-3">ተጫዋቾችን በሰከንዶች ውስጥ በቴሌብር ወይም በባንክ ሒሳብ ይርዱ።</p>
            
            <div class="space-y-2.5">
                <div>
                    <label class="text-[10px] text-slate-300 font-bold block mb-1">የተጫዋች User ID</label>
                    <input type="number" id="topup-uid" placeholder="ለምሳሌ: 12345678" class="w-full bg-slate-900 border border-slate-700 rounded-2xl px-3.5 py-2.5 text-xs text-white focus:outline-none focus:border-amber-400 shadow-inner">
                </div>
                <div>
                    <label class="text-[10px] text-slate-300 font-bold block mb-1">የብር መጠን (ETB)</label>
                    <input type="number" id="topup-amount" placeholder="0.00" class="w-full bg-slate-900 border border-slate-700 rounded-2xl px-3.5 py-2.5 text-xs text-white focus:outline-none focus:border-amber-400 shadow-inner">
                </div>
                <div>
                    <label class="text-[10px] text-slate-300 font-bold block mb-1">ትራንዛክሽን ኮድ (Transaction ID / SMS)</label>
                    <input type="text" id="topup-txn" placeholder="Txn ID or Bank Reference" class="w-full bg-slate-900 border border-slate-700 rounded-2xl px-3.5 py-2.5 text-xs text-white focus:outline-none focus:border-amber-400 shadow-inner">
                </div>
                <div class="grid grid-cols-2 gap-2.5 pt-2">
                    <button onclick="processAgentAction('deposit')" class="py-3 bg-gradient-to-r from-emerald-500 to-green-600 hover:from-emerald-400 hover:to-green-500 text-slate-950 font-black text-xs rounded-2xl shadow-lg">➕ ዲፖዚት ጫን</button>
                    <button onclick="processAgentAction('withdraw')" class="py-3 bg-gradient-to-r from-rose-500 to-red-600 hover:from-rose-400 hover:to-red-500 text-white font-black text-xs rounded-2xl shadow-lg">➖ ዊዝድሮ አድርግ</button>
                </div>
            </div>
        </div>

        <!-- TAB 3: PLAYER MANAGEMENT -->
        <div id="section-players" class="glass-panel p-4 rounded-3xl hidden space-y-3">
            <h2 class="text-xs font-bold text-amber-400 mb-1">👥 የተጫዋቾች አስተዳደር (Player Management)</h2>
            <div class="flex gap-2">
                <input type="text" id="search-player-id" placeholder="ተጫዋች ID ፈልግ..." class="flex-1 bg-slate-900 border border-slate-700 rounded-2xl px-3.5 py-2.5 text-xs text-white shadow-inner">
                <button onclick="searchPlayer()" class="bg-amber-400 text-slate-950 px-4 py-2.5 rounded-2xl font-extrabold text-xs shadow-md">ፈልግ</button>
            </div>
            <div id="player-search-result" class="mt-2 text-xs space-y-2"></div>
        </div>

        <!-- TAB 4: AGENT SUPPORT HUB -->
        <div id="section-support" class="glass-panel p-4 rounded-3xl hidden space-y-3">
            <h2 class="text-xs font-bold text-amber-400 mb-1">🎧 የድጋፍ እና ቲክኬት መስጫ (Support Hub)</h2>
            <p class="text-[10px] text-slate-300 mb-2">ማንኛውም ቴክኒካዊ ችግር ወይም ጥያቄ ካለዎት በቀጥታ ለአስተዳዳሪው ይላኩ።</p>
            <textarea id="support-ticket-msg" rows="3" placeholder="ችግርዎን እዚህ ይጻፉ..." class="w-full bg-slate-900 border border-slate-700 rounded-2xl p-3.5 text-xs text-white focus:outline-none focus:border-amber-400 shadow-inner"></textarea>
            <button onclick="sendSupportTicket()" class="w-full py-3 bg-gradient-to-r from-purple-600 to-amber-500 text-slate-950 font-black text-xs rounded-2xl shadow-lg">📩 ቲክኬት ላክ (Send Ticket)</button>
        </div>
    </div>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const agentId = urlParams.get('agent_id');
        
        if(window.Telegram && window.Telegram.WebApp) {
            window.Telegram.WebApp.expand();
        }

        function switchTab(tabName) {
            ['overview', 'topup', 'players', 'support'].forEach(t => {
                document.getElementById(`section-${t}`).classList.add('hidden');
                document.getElementById(`tab-${t}`).classList.remove('active', 'text-slate-950');
                document.getElementById(`tab-${t}`).classList.add('text-slate-300');
            });
            document.getElementById(`section-${tabName}`).classList.remove('hidden');
            document.getElementById(`tab-${tabName}`).classList.add('active', 'text-slate-950');
            document.getElementById(`tab-${tabName}`).classList.remove('text-slate-300');
        }

        let earningsChartInstance = null;

        function loadAgentData() {
            fetch(`/api/agent_data?agent_id=${agentId}`)
                .then(res => res.json())
                .then(data => {
                    document.getElementById('agent-bal').innerText = `${data.balance.toFixed(2)} ETB`;
                    document.getElementById('agent-refs').innerText = data.referred_players.length;
                    document.getElementById('agent-link-text').innerText = data.link;
                    
                    if(data.live_game) {
                        document.getElementById('live-status').innerText = data.live_game.status;
                        document.getElementById('live-sold').innerText = data.live_game.sold_count;
                    }

                    const ctx = document.getElementById('earningsChart').getContext('2d');
                    if(earningsChartInstance) earningsChartInstance.destroy();
                    
                    earningsChartInstance = new Chart(ctx, {
                        type: 'bar',
                        data: {
                            labels: ['ሰኞ', 'ማክሰኞ', 'ረቡዕ', 'ሐሙስ', 'አርብ', 'ቅዳሜ', 'እሁድ'],
                            datasets: [{
                                label: 'የተገኘ ኮሚሽን (ETB)',
                                data: data.weekly_earnings || [0, 0, 0, 0, 0, 0, data.balance],
                                backgroundColor: '#f59e0b',
                                borderRadius: 8
                            }]
                        },
                        options: {
                            responsive: true,
                            plugins: { legend: { display: false } },
                            scales: {
                                y: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.05)' } },
                                x: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { display: false } }
                            }
                        }
                    });
                });
        }

        function withdrawCommission() {
            fetch('/api/agent_withdraw_commission', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ agent_id: agentId })
            }).then(res => res.json()).then(data => {
                alert(data.msg);
                loadAgentData();
            });
        }

        function processAgentAction(actionType) {
            const uid = document.getElementById('topup-uid').value;
            const amount = document.getElementById('topup-amount').value;
            const txn = document.getElementById('topup-txn').value;

            if(!uid || !amount) return alert("⚠️ እባክዎን የተጫዋች ID እና የብር መጠን ያስገቡ!");

            fetch('/api/agent_process_topup', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ agent_id: agentId, user_id: uid, amount: amount, txn_id: txn, action: actionType })
            }).then(res => res.json()).then(data => {
                alert(data.msg);
                if(data.success) {
                    document.getElementById('topup-uid').value = '';
                    document.getElementById('topup-amount').value = '';
                    document.getElementById('topup-txn').value = '';
                }
                loadAgentData();
            });
        }

        function searchPlayer() {
            const queryUid = document.getElementById('search-player-id').value;
            if(!queryUid) return alert("⚠️ እባክዎን የሚፈልጉትን የተጫዋች ID ያስገቡ!");

            fetch(`/api/agent_search_player?agent_id=${agentId}&target_user_id=${queryUid}`)
                .then(res => res.json())
                .then(data => {
                    const resContainer = document.getElementById('player-search-result');
                    if(data.found) {
                        resContainer.innerHTML = `
                            <div class="bg-slate-900/90 p-3.5 rounded-2xl border border-slate-700 space-y-1 shadow-lg">
                                <div>👤 ስም: <b>${data.name}</b></div>
                                <div>🆔 ID: <code>${data.id}</code></div>
                                <div>💰 ባላንስ: <b class="text-emerald-400">${data.balance.toFixed(2)} ETB</b></div>
                                <div>📌 የግብይት ብዛት: ${data.history_count} ታሪኮች</div>
                            </div>
                        `;
                    } else {
                        resContainer.innerHTML = `<div class="text-rose-400 text-center font-bold">❌ ተጫዋቹ አልተገኘም ወይም በእርስዎ ስር አይደለም።</div>`;
                    }
                });
        }

        function sendSupportTicket() {
            const msg = document.getElementById('support-ticket-msg').value;
            if(!msg) return alert("⚠️ እባክዎን መልእክት ይጻፉ!");

            fetch('/api/agent_support_ticket', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ agent_id: agentId, message: msg })
            }).then(res => res.json()).then(data => {
                alert(data.msg);
                document.getElementById('support-ticket-msg').value = '';
            });
        }

        loadAgentData();
        setInterval(loadAgentData, 5000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/agent')
def agent_dashboard_web():
    return render_template_string(AGENT_HTML_TEMPLATE)

@app.route('/api/agent_data')
def api_agent_data():
    agent_id = request.args.get('agent_id', type=int)
    with db_lock:
        if agent_id not in agents_db:
            agents_db[agent_id] = {"balance": 0.0, "total_earned": 0.0, "referred_players": [], "weekly_earnings": [0,0,0,0,0,0,0]}
        
        data = agents_db[agent_id]
        bot_username = bot.get_me().username
        link = f"https://t.me/{bot_username}?start=agent_{agent_id}"
        
        live_game_info = {
            "status": game_state["status"],
            "sold_count": len(game_state["selected_cards"])
        }

        return jsonify({
            "balance": data["balance"],
            "total_earned": data["total_earned"],
            "referred_players": data["referred_players"],
            "weekly_earnings": data.get("weekly_earnings", [0,0,0,0,0,0, data["balance"]]),
            "link": link,
            "live_game": live_game_info
        })

@app.route('/api/agent_withdraw_commission', methods=['POST'])
def api_agent_withdraw_commission():
    req = request.json
    agent_id = int(req.get('agent_id'))
    with db_lock:
        if agent_id in agents_db and agents_db[agent_id]["balance"] > 0:
            amount = agents_db[agent_id]["balance"]
            agents_db[agent_id]["balance"] = 0.0
            if agent_id not in users_db:
                users_db[agent_id] = {"id": agent_id, "name": "Agent", "balance": 0.0, "history": []}
            users_db[agent_id]["balance"] += amount
            new_bal = users_db[agent_id]["balance"]
            
            add_user_history(agent_id, "የኤጀንት ኮሚሽን ዊዝድሮ", f"+{amount:.2f} ETB ወደ ዋና ባላንስ ተላልፏል")
            socketio.emit('balance_update', {'user_id': agent_id, 'balance': new_bal})
            
            try:
                bot.send_message(agent_id, f"✅ <b>{amount:.2f} ETB</b> የኮሚሽን ባላንስዎ ተላልፎ ወደ ዋናው አካውንትዎ ገብቷል!\n💳 አዲሱ ባላንስዎ፦ <b>{new_bal:.2f} ETB</b>", parse_mode="HTML")
            except Exception:
                pass

            return jsonify({"success": True, "msg": f"✅ {amount:.2f} ETB በተሳካ ሁኔታ ተዛውሯል!"})
        else:
            return jsonify({"success": False, "msg": "❌ በቂ የኮሚሽን ባላንስ የለዎትም!"})

@app.route('/api/agent_process_topup', methods=['POST'])
def api_agent_process_topup():
    req = request.json
    agent_id = int(req.get('agent_id'))
    target_uid = int(req.get('user_id'))
    amount = float(req.get('amount'))
    action = req.get('action') 
    txn_id = req.get('txn_id', 'AGENT_DIRECT')

    with db_lock:
        if target_uid not in users_db:
            users_db[target_uid] = {"id": target_uid, "name": f"User {target_uid}", "balance": 0.0, "history": []}

        if action == 'deposit':
            users_db[target_uid]["balance"] += amount
            new_bal = users_db[target_uid]["balance"]
            socketio.emit('balance_update', {'user_id': target_uid, 'balance': new_bal})
            add_user_history(target_uid, "በኤጀንት ዲፖዚት", f"+{amount:.2f} ETB በኤጀንት ተጭኗል")
            try:
                bot.send_message(target_uid, f"🎉 <b>በኤጀንት ዲፖዚት ተደርጓል!</b>\n\n💰 መጠን: <b>+{amount:.2f} ETB</b>\n💳 አዲሱ ባላንስዎ: <b>{new_bal:.2f} ETB</b>", parse_mode="HTML")
            except Exception:
                pass
            return jsonify({"success": True, "msg": f"✅ ለተጫዋች {target_uid} {amount:.2f} ETB ዲፖዚት ተደርጓል!"})
        
        elif action == 'withdraw':
            if users_db[target_uid]["balance"] < amount:
                return jsonify({"success": False, "msg": "❌ የተጫዋቹ ባላንስ በቂ አይደለም!"})
            users_db[target_uid]["balance"] -= amount
            new_bal = users_db[target_uid]["balance"]
            socketio.emit('balance_update', {'user_id': target_uid, 'balance': new_bal})
            add_user_history(target_uid, "በኤጀንት ዊዝድሮ", f"-{amount:.2f} ETB በኤጀንት ተወስዷል")
            try:
                bot.send_message(target_uid, f"📤 <b>በኤጀንት ዊዝድሮ ተፈጽሟል!</b>\n\n💰 የተወሰደው: <b>-{amount:.2f} ETB</b>\n💳 የቀረ ባላንስ: <b>{new_bal:.2f} ETB</b>", parse_mode="HTML")
            except Exception:
                pass
            return jsonify({"success": True, "msg": f"✅ ከተጫዋች {target_uid} {amount:.2f} ETB ዊዝድሮ ተደርጓል!"})

    return jsonify({"success": False, "msg": "❌ ስህተት ተፈጥሯል!"})

@app.route('/api/agent_search_player')
def api_agent_search_player():
    agent_id = request.args.get('agent_id', type=int)
    target_uid = request.args.get('target_user_id', type=int)
    
    with db_lock:
        if target_uid in users_db:
            u_data = users_db[target_uid]
            return jsonify({
                "found": True,
                "id": target_uid,
                "name": u_data.get("name", "User"),
                "balance": u_data.get("balance", 0.0),
                "history_count": len(u_data.get("history", []))
            })
    return jsonify({"found": False})

@app.route('/api/agent_support_ticket', methods=['POST'])
def api_agent_support_ticket():
    req = request.json
    agent_id = int(req.get('agent_id'))
    msg = req.get('message')
    
    admin_alert = (
        f"🎧 <b>አዲስ የኤጀንት ድጋፍ ቲክኬት!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🤝 ከኤጀንት ID: <code>{agent_id}</code>\n"
        f"💬 መልእክት: <i>{msg}</i>"
    )
    try:
        bot.send_message(ADMIN_ID, admin_alert, parse_mode="HTML")
    except Exception:
        pass

    return jsonify({"success": True, "msg": "✅ ቲክኬቱ ለአድሚኑ ቡድን በተሳካ ሁኔታ ተልኳል!"})

# =========================================================
# 5. TELEGRAM MAIN BOT & COMMAND HANDLERS
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
    
    if int(user_id) == ADMIN_ID or int(user_id) in agents_db:
        markup.add(
            InlineKeyboardButton(text="🤝 የኤጀንት ዳሽቦርድ (Agent)", callback_data="btn_agent_menu")
        )

    markup.add(
        InlineKeyboardButton(text="📜 የግብይት እና ጨዋታ ታሪክ (History)", callback_data="btn_history")
    )
    markup.add(
        InlineKeyboardButton(text="ℹ️ እርዳታ እና ህጎች", callback_data="btn_help"),
        InlineKeyboardButton(text="🎧 የደንበኞች አገልግሎት", url=support_deep_link)
    )
    return markup

def add_user_history(uid, history_type, details):
    with db_lock:
        if uid in users_db:
            if "history" not in users_db[uid]:
                users_db[uid]["history"] = []
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            users_db[uid]["history"].insert(0, {
                "time": timestamp,
                "type": history_type,
                "details": details
            })
            if len(users_db[uid]["history"]) > 20:
                users_db[uid]["history"].pop()

@bot.message_handler(commands=['start', 'menu'])
def start_cmd(message):
    uid = int(message.from_user.id)
    first_name = message.from_user.first_name.replace('<', '&lt;').replace('>', '&gt;')
    username = (message.from_user.username or "የለውም").replace('<', '&lt;').replace('>', '&gt;')

    args = message.text.split()
    referred_by = None
    agent_referred_by = None

    if len(args) > 1:
        if args[1].startswith('ref_'):
            try:
                ref_id = int(args[1].split('_')[1])
                if ref_id != uid:
                    referred_by = ref_id
            except ValueError:
                pass
        elif args[1].startswith('agent_'):
            try:
                ag_id = int(args[1].split('_')[1])
                if ag_id != uid:
                    agent_referred_by = ag_id
            except ValueError:
                pass

    with db_lock:
        if uid not in users_db:
            users_db[uid] = {
                "id": uid,
                "name": first_name,
                "username": username,
                "balance": 0.0,
                "referred_by": referred_by,
                "agent_referred_by": agent_referred_by,
                "referral_count": 0,
                "has_deposited": False,
                "milestone_rewarded": False,
                "history": []
            }
            if referred_by and referred_by in users_db:
                users_db[referred_by]["referral_count"] = users_db[referred_by].get("referral_count", 0) + 1
            
            if agent_referred_by:
                if agent_referred_by not in agents_db:
                    agents_db[agent_referred_by] = {"balance": 0.0, "total_earned": 0.0, "referred_players": [], "weekly_earnings": [0,0,0,0,0,0,0]}
                if uid not in agents_db[agent_referred_by]["referred_players"]:
                    agents_db[agent_referred_by]["referred_players"].append(uid)

        bal = users_db[uid]['balance']

    welcome_txt = (
        f"👋 ሰላም <b>{first_name}</b>!\n\n"
        f"ወደ <b>BKBINGO Pro</b> እንኳን ደህና መጡ! 🎲\n"
        f"💰 ባላንስዎ፦ <b>{bal:.2f} ETB</b>\n\n"
        "ለመጫወት ከታች ያለውን <b>'🎲 ጨዋታ ጀምር'</b> የሚለውን ይጫኑ。"
    )
    bot.send_message(message.chat.id, welcome_txt, reply_markup=main_menu_keyboard(uid), parse_mode="HTML")

@bot.message_handler(commands=['play'])
def play_command(message):
    uid = int(message.from_user.id)
    first_name = message.from_user.first_name.replace('<', '&lt;').replace('>', '&gt;')
    with db_lock:
        if uid not in users_db:
            users_db[uid] = {"id": uid, "name": first_name, "balance": 0.0, "history": []}
        bal = users_db[uid]['balance']

    welcome_txt = (
        f"🎲 <b>BKBINGO Pro ጨዋታ</b>\n\n"
        f"ሰላም <b>{first_name}</b>፣ ለመጫወት ዝግጁ ኖት?\n"
        f"💰 ባላንስዎ፦ <b>{bal:.2f} ETB</b>\n\n"
        "ከታች ያለውን ቁልፍ በመጫን አፑን ከፍተው ይጫወቱ!"
    )
    bot.send_message(message.chat.id, welcome_txt, reply_markup=main_menu_keyboard(uid), parse_mode="HTML")

@bot.message_handler(commands=['balance'])
def balance_command(message):
    uid = int(message.from_user.id)
    with db_lock:
        if uid not in users_db:
            users_db[uid] = {"id": uid, "name": message.from_user.first_name, "balance": 0.0, "history": []}
        bal = users_db[uid]["balance"]
        ref_count = users_db[uid].get("referral_count", 0)

    msg = f"👤 <b>የተጫዋች ፕሮፋይል እና ባላንስ</b>\n\n🆔 ID: <code>{uid}</code>\n💰 ቀሪ ሂሳብ: <b>{bal:.2f} ETB</b>\n👥 የጋበዟቸው ሰዎች: <b>{ref_count}/{MILESTONE_REFERRAL_TARGET}</b>"
    bot.send_message(message.chat.id, msg, reply_markup=main_menu_keyboard(uid), parse_mode="HTML")

@bot.message_handler(commands=['deposit'])
def deposit_command(message):
    uid = int(message.from_user.id)
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("CBE BIRR", callback_data="depmeth_cbe"),
        InlineKeyboardButton("TELE BIRR", callback_data="depmeth_tele")
    )
    bot.send_message(
        message.chat.id,
        "💳 <b>የክፍያ መንገድ ይምረጡ (Select Deposit Method)</b>\n\nእባክዎ ሂሳብ ለመሙላት የሚጠቀሙበትን መንገድ ይምረጡ፦",
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.message_handler(commands=['withdraw'])
def withdraw_command(message):
    uid = int(message.from_user.id)
    with db_lock:
        if uid not in users_db:
            users_db[uid] = {"id": uid, "balance": 0.0, "history": []}
        bal = users_db[uid]["balance"]

    if bal < MIN_WITHDRAWAL:
        bot.send_message(message.chat.id, f"❌ <b>ዝቅተኛው የዊዝድሮው መጠን {MIN_WITHDRAWAL:.2f} ETB ነው።</b>\nየእርስዎ ባላንስ፦ <b>{bal:.2f} ETB</b>", parse_mode="HTML")
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📱 Telebirr", callback_data="wdmeth_Telebirr"),
        InlineKeyboardButton("🏦 CBE Birr", callback_data="wdmeth_CBE")
    )
    bot.send_message(message.chat.id, f"📤 <b>ገንዘብ ማውጫ ዘዴ ይምረጡ፦</b>\n💰 የሚገኝ ባላንስ፦ <b>{bal:.2f} ETB</b>", reply_markup=markup, parse_mode="HTML")

@bot.message_handler(commands=['agent'])
def agent_command(message):
    uid = int(message.from_user.id)
    first_name = message.from_user.first_name.replace('<', '&lt;').replace('>', '&gt;')
    
    with db_lock:
        if uid not in agents_db:
            agents_db[uid] = {
                "balance": 0.0,
                "total_earned": 0.0,
                "referred_players": [],
                "weekly_earnings": [0,0,0,0,0,0,0]
            }
        agent_info = agents_db[uid]
        bal = agent_info["balance"]
        earned = agent_info["total_earned"]
        ref_players = len(agent_info["referred_players"])

    bot_username = bot.get_me().username
    agent_link = f"https://t.me/{bot_username}?start=agent_{uid}"

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(text="📊 ሙሉ የኤጀንት ዳሽቦርድ ክፈት (Web App)", web_app=WebAppInfo(url=f"{RENDER_WEBAPP_URL}/agent?agent_id={uid}")),
        InlineKeyboardButton(text="💸 ኮሚሽን ወደ ዋና ባላንስ አስተላልፍ", callback_data="agent_transfer_bal")
    )

    agent_msg = (
        f"🤝 <b>የ BKBINGO Pro የኤጀንት ዳሽቦርድ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"ሰላም <b>{first_name}</b>፣ የእርስዎ የኤጀንት ዝርዝር መረጃ ከታች ተቀምጧል፦\n\n"
        f"👥 በሊንክዎ የተመዘገቡ ተጫዋቾች: <b>{ref_players}</b>\n"
        f"💰 የሚገኝ የኮሚሽን ባላንስ: <b>{bal:.2f} ETB</b>\n"
        f"🏆 አጠቃላይ የተገኘ ገቢ: <b>{earned:.2f} ETB</b>\n\n"
        f"🔗 <b>የእርስዎ ኤጀንት ሊንክ፦</b>\n<code>{agent_link}</code>"
    )
    bot.send_message(message.chat.id, agent_msg, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(commands=['history'])
def history_command(message):
    uid = int(message.from_user.id)
    with db_lock:
        if uid not in users_db:
            users_db[uid] = {"id": uid, "name": message.from_user.first_name, "balance": 0.0, "history": []}
        history_list = users_db[uid].get("history", [])

    if not history_list:
        hist_msg = "📜 <b>የታሪክ መዝገብ</b>\n\nእስካሁን የተመዘገበ ምንም አይነት የጨዋታ፣ ዲፖዚት ወይም ዊዝድሮ ታሪክ የለዎትም አሁን ይጀምሩ! 🎲"
    else:
        hist_msg = "📜 <b>የእርስዎ የቅርብ ጊዜ ታሪኮች (Activity History)</b>\n━━━━━━━━━━━━━━━━━━━\n"
        for item in history_list[:10]:
            hist_msg += f"⏱ <code>{item['time']}</code>\n📌 <b>{item['type']}</b>: {item['details']}\n\n"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 ወደ ዋናው ምናሌ ተመለስ", callback_data="btn_main_menu"))
    bot.send_message(message.chat.id, hist_msg, parse_mode="HTML", reply_markup=markup)

@bot.message_handler(commands=['instructions'])
def instructions_command(message):
    instruction_text = (
        "📖 <b>የ BKBINGO Pro አጠቃቀም መመሪያ (Instructions):</b>\n\n"
        "1. <code>/play</code> በመጫወት ጨዋታውን ይጀምሩ።\n"
        "2. ሂሳብ ለመሙላት <code>/deposit</code> ይጠቀሙ።\n"
        "3. ያሸነፉትን ገንዘብ ለማውጣት <code>/withdraw</code> ይጠቀሙ።\n"
        "4. ኤጀንት ለመሆን ወይም ዳሽቦርድ ለመክፈት <code>/agent</code> ይጠቀሙ።"
    )
    bot.send_message(message.chat.id, instruction_text, parse_mode="HTML")

@bot.message_handler(commands=['support'])
def support_command(message):
    uid = int(message.from_user.id)
    with db_lock:
        user_bal = users_db.get(uid, {}).get("balance", 0.0)
    support_deep_link = f"https://t.me/BkbingosupportBot?start=USER_{uid}_BAL_{int(user_bal)}"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="🎧 የደንበኞች አገልግሎት ቡድን ማነጋገር", url=support_deep_link))
    
    bot.send_message(
        message.chat.id,
        "🎧 <b>የደንበኞች አገልግሎት (Support)</b>\n\nማንኛውም ጥያቄ ወይም የክፍያ ማስተካከያ ካለዎት ከታች ባለው ሊንክ በቀጥታ ማነጋገር ይችላሉ።",
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.message_handler(commands=['stats'])
def admin_statistics(message):
    uid = int(message.from_user.id)
    if uid != ADMIN_ID:
        bot.send_message(message.chat.id, "❌ ይህ ትዕዛዝ ለአድሚን ብቻ የተፈቀደ ነው።")
        return

    with db_lock:
        total_users = len(users_db)
        total_agents = len(agents_db)
        total_deposit_amount = 0.0
        total_withdraw_amount = 0.0

        for user_data in users_db.values():
            for hist in user_data.get("history", []):
                if "ዲፖዚት" in hist["type"]:
                    nums = re.findall(r'\+?(\d+(?:\.\d+)?)', hist["details"])
                    if nums:
                        total_deposit_amount += float(nums[0])
                elif "ዊዝድሮ" in hist["type"] and "ውድቅ" not in hist["type"]:
                    nums = re.findall(r'-?(\d+(?:\.\d+)?)', hist["details"])
                    if nums:
                        total_withdraw_amount += float(nums[0])

    stats_msg = (
        f"📊 <b>የ BKBINGO Pro አድሚን ስታስቲክስ (Statistics)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👥 አጠቃላይ የተጠቃሚዎች ቁጥር: <b>{total_users}</b>\n"
        f"🤝 አጠቃላይ ኤጀንቶች: <b>{total_agents}</b>\n"
        f"📥 አጠቃላይ የገባ ገንዘብ (Total Deposit): <b>{total_deposit_amount:.2f} ETB</b>\n"
        f"📤 አጠቃላይ የወጣ ገንዘብ (Total Withdrawal): <b>{total_withdraw_amount:.2f} ETB</b>\n"
        f"💰 የተጣራ ልዩነት (Net Flow): <b>{(total_deposit_amount - total_withdraw_amount):.2f} ETB</b>"
    )
    bot.send_message(message.chat.id, stats_msg, parse_mode="HTML")

@bot.message_handler(commands=['broadcast'])
def broadcast_command(message):
    uid = int(message.from_user.id)
    if uid != ADMIN_ID:
        bot.send_message(message.chat.id, "❌ ይህ ትዕዛዝ ለአድሚን ብቻ የተፈቀደ ነው።")
        return
    
    broadcast_state[ADMIN_ID] = True
    bot.send_message(
        message.chat.id, 
        "📢 <b>የብሮድካስት ሁነታ (Broadcast Mode) ተከፍቷል!</b>\n\nለተጠቃሚዎች ማስተላለፍ የሚፈልጉትን <b>ጽሁፍ፣ ፎቶ፣ ቪዲዮ ወይም ዶክመንት</b> አሁን ይላኩ።", 
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda m: int(m.from_user.id) == ADMIN_ID and broadcast_state.get(ADMIN_ID) == True, content_types=['text', 'photo', 'video', 'document'])
def send_broadcast_to_users(message):
    broadcast_state[ADMIN_ID] = False
    with db_lock:
        all_user_ids = list(users_db.keys())

    success_count = 0
    fail_count = 0

    bot.send_message(message.chat.id, f"⏳ መልእክቱ ለ <b>{len(all_user_ids)}</b> ተጠቃሚዎች በመላክ ላይ ይገኛል...", parse_mode="HTML")

    for uid in all_user_ids:
        try:
            if message.photo:
                bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.video:
                bot.send_video(uid, message.video.file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.document:
                bot.send_document(uid, message.document.file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.text:
                bot.send_message(uid, message.text, parse_mode="HTML")
            success_count += 1
            time.sleep(0.05)
        except Exception:
            fail_count += 1

    bot.send_message(
        message.chat.id, 
        f"✅ <b>ብሮድካስቱ በተሳካ ሁኔታ ተጠናቋል!</b>\n\n📤 የደረሳቸው: <b>{success_count}</b>\n❌ ያልደረሳቸው: <b>{fail_count}</b>", 
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('btn_'))
def handle_main_menu_callbacks(call):
    uid = int(call.from_user.id)
    action = call.data
    bot.answer_callback_query(call.id)

    safe_name = call.from_user.first_name.replace('<', '&lt;').replace('>', '&gt;')
    
    with db_lock:
        if uid not in users_db:
            users_db[uid] = {"id": uid, "name": safe_name, "username": call.from_user.username or "የለውም", "balance": 0.0, "referral_count": 0, "history": []}
        bal = users_db[uid]["balance"]
        ref_count = users_db[uid].get("referral_count", 0)

    if action == "btn_profile":
        msg = f"👤 <b>የተጫዋች ፕሮፋይል</b>\n🆔 ID: <code>{uid}</code>\n💰 ባላንስ: <b>{bal:.2f} ETB</b>\n👥 የጋበዟቸው ሰዎች: <b>{ref_count}/{MILESTONE_REFERRAL_TARGET}</b>"
        bot.send_message(call.message.chat.id, msg, reply_markup=main_menu_keyboard(uid), parse_mode="HTML")

    elif action == "btn_deposit":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("CBE BIRR", callback_data="depmeth_cbe"),
            InlineKeyboardButton("TELE BIRR", callback_data="depmeth_tele")
        )
        bot.send_message(
            call.message.chat.id,
            "💳 <b>የክፍያ መንገድ ይምረጡ (Select Deposit Method)</b>\n\nእባክዎ ሂሳብ ለመሙላት የሚጠቀሙበትን መንገድ ይምረጡ፦",
            reply_markup=markup,
            parse_mode="HTML"
        )

    elif action == "btn_withdraw":
        if bal < MIN_WITHDRAWAL:
            bot.send_message(call.message.chat.id, f"❌ <b>ዝቅተኛው የዊዝድሮው መጠን {MIN_WITHDRAWAL:.2f} ETB ነው።</b>\nየእርስዎ ባላንስ፦ <b>{bal:.2f} ETB</b>", parse_mode="HTML")
            return
        
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📱 Telebirr", callback_data="wdmeth_Telebirr"),
            InlineKeyboardButton("🏦 CBE Birr", callback_data="wdmeth_CBE")
        )
        bot.send_message(call.message.chat.id, f"📤 <b>ገንዘብ ማውጫ ዘዴ ይምረጡ፦</b>\n💰 የሚገኝ ባላንስ፦ <b>{bal:.2f} ETB</b>", reply_markup=markup, parse_mode="HTML")

    elif action == "btn_referral":
        bot_username = bot.get_me().username
        ref_link = f"https://t.me/{bot_username}?start=ref_{uid}"
        ref_msg = (
            f"👥 <b>የሪፈራል ፕሮግራም (Referral System)</b>\n\n"
            f"ጓደኞችዎን ወደ ቦቱ በመጋበዝ ትልቅ ሽልማት ያግኙ! 🎁\n"
            f"እስከ <b>{MILESTONE_REFERRAL_TARGET}</b> ሰዎችን ሲጋብዙ በራስ ሰር የ<b>{MILESTONE_BONUS:.2f} ETB</b> ልዩ ቦነስ ይሸለማሉ!\n\n"
            f"🔗 <b>የእርስዎ ልዩ የሪፈራል ሊንክ፦</b>\n<code>{ref_link}</code>\n\n"
            f"📊 የጋበዟቸው ሰዎች ብዛት፦ <b>{ref_count} / {MILESTONE_REFERRAL_TARGET}</b>"
        )
        bot.send_message(call.message.chat.id, ref_msg, reply_markup=main_menu_keyboard(uid), parse_mode="HTML")

    elif action == "btn_agent_menu":
        with db_lock:
            if uid not in agents_db:
                agents_db[uid] = {"balance": 0.0, "total_earned": 0.0, "referred_players": [], "weekly_earnings": [0,0,0,0,0,0,0]}
            agent_info = agents_db[uid]
            ag_bal = agent_info["balance"]
            ag_earned = agent_info["total_earned"]
            ag_refs = len(agent_info["referred_players"])

        bot_username = bot.get_me().username
        agent_link = f"https://t.me/{bot_username}?start=agent_{uid}"

        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton(text="📊 ሙሉ የኤጀንት ዳሽቦርድ ክፈት (Web App)", web_app=WebAppInfo(url=f"{RENDER_WEBAPP_URL}/agent?agent_id={uid}")),
            InlineKeyboardButton(text="💸 ኮሚሽን ወደ ዋና ባላንስ አስተላልፍ", callback_data="agent_transfer_bal")
        )

        agent_menu_msg = (
            f"📈 <b>የ BKBINGO Pro ኤጀንት ዳሽቦርድ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👥 በሊንክዎ የተመዘገቡ ተጫዋቾች: <b>{ag_refs}</b>\n"
            f"💰 የሚገኝ የኮሚሽን ባላንስ: <b>{ag_bal:.2f} ETB</b>\n"
            f"🏆 አጠቃላይ የተገኘ ገቢ: <b>{ag_earned:.2f} ETB</b>\n\n"
            f"🔗 <b>የእርስዎ ኤጀንት ሊንክ፦</b>\n<code>{agent_link}</code>"
        )
        bot.send_message(call.message.chat.id, agent_menu_msg, reply_markup=markup, parse_mode="HTML")

    elif action == "btn_history":
        with db_lock:
            history_list = users_db.get(uid, {}).get("history", [])

        if not history_list:
            hist_msg = "📜 <b>የታሪክ መዝገብ</b>\n\nእስካሁን የተመዘገበ ምንም አይነት የጨዋታ፣ ዲፖዚት ወይም ዊዝድሮ ታሪክ የለዎትም አሁን ይጀምሩ! 🎲"
        else:
            hist_msg = "📜 <b>የእርስዎ የቅርብ ጊዜ ታሪኮች (Activity History)</b>\n━━━━━━━━━━━━━━━━━━━\n"
            for item in history_list[:10]:
                hist_msg += f"⏱ <code>{item['time']}</code>\n📌 <b>{item['type']}</b>: {item['details']}\n\n"

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 ወደ ዋናው ምናሌ ተመለስ", callback_data="btn_main_menu"))
        bot.edit_message_text(hist_msg, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)

    elif action == "btn_main_menu":
        welcome_txt = (
            f"👋 ሰላም <b>{call.from_user.first_name}</b>!\n\n"
            f"ወደ <b>BKBINGO Pro</b> እንኳን ደህና መጡ! 🎲\n"
            f"💰 ባላንስዎ፦ <b>{bal:.2f} ETB</b>\n\n"
            "ለመጫወት ከታች ያለውን <b>'🎲 ጨዋታ ጀምር'</b> የሚለውን ይጫኑ。"
        )
        bot.edit_message_text(welcome_txt, call.message.chat.id, call.message.message_id, reply_markup=main_menu_keyboard(uid), parse_mode="HTML")

    elif action == "btn_help":
        bot.send_message(call.message.chat.id, "ℹ️ <b>የ BKBINGO Pro ህጎች</b>\n1. የካርቴላ ዋጋ 10 ETB ነው።\n2. በአንድ ዙር ቢበዛ 2 ካርቴላ መግዛት ይቻላል።\n3. አሸናፊው ደራሹን በሙሉ ይወስዳል።", parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "agent_transfer_bal")
def handle_agent_transfer_callback(call):
    uid = int(call.from_user.id)
    with db_lock:
        if uid in agents_db and agents_db[uid]["balance"] > 0:
            amount = agents_db[uid]["balance"]
            agents_db[uid]["balance"] = 0.0
            if uid not in users_db:
                users_db[uid] = {"id": uid, "name": call.from_user.first_name, "balance": 0.0, "history": []}
            users_db[uid]["balance"] += amount
            new_bal = users_db[uid]["balance"]
            
            bot.answer_callback_query(call.id, f"{amount:.2f} ETB ወደ ዋና ባላንስዎ ተዛውሯል!", show_alert=True)
            add_user_history(uid, "የኤጀንት ኮሚሽን ዝውውር", f"+{amount:.2f} ETB ወደ ዋና ባላንስ ገብቷል")
            
            socketio.emit('balance_update', {'user_id': uid, 'balance': new_bal})
            bot.send_message(call.message.chat.id, f"✅ <b>{amount:.2f} ETB</b> የኮሚሽን ባላንስዎ በተሳካ ሁኔታ ወደ ዋናው አካውንትዎ ተዛውሯል!\n💳 አዲሱ ባላንስዎ፦ <b>{new_bal:.2f} ETB</b>", parse_mode="HTML")
        else:
            bot.answer_callback_query(call.id, "❌ በቂ የኮሚሽን ባላንስ የለዎትም!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('depmeth_'))
def handle_deposit_method_selection(call):
    uid = int(call.from_user.id)
    method = call.data.split('_')[1]
    bot.answer_callback_query(call.id)

    if method == "cbe":
        deposit_data[uid] = {"method": "CBE-Birr", "account": CBE_ACCOUNT, "name": CBE_NAME}
        method_title = "የ CBE-Birr አካውንት"
        merchant_info = f"CBE-BIRR Merchant - {CBE_ACCOUNT}\n({CBE_NAME})"
    else:
        deposit_data[uid] = {"method": "Telebirr", "account": TELEBIRR_ACCOUNT, "name": TELEBIRR_NAME}
        method_title = "የ Telebirr አካውንት"
        merchant_info = f"TELEBIRR Account - {TELEBIRR_ACCOUNT}\n({TELEBIRR_NAME})"

    user_states[uid] = "WAITING_SMS_RECEIPT"

    instructions = (
        f"የ <b>{method_title}</b> አካውንት\n\n"
        f"<b>{merchant_info}</b>\n\n"
        "<b>መመሪያ</b>\n"
        f"1. ከላይ ባለው የ {method_title} Pay for Merchant በሚለው ገንዘቡን ያስገቡ\n"
        "2. ብሩን ስትልክ የክፍያዎን መረጃ የያዘ አጭር የሩፍ መልክት(sms) ከ ባንኩ/ቴሌብር ይደርሶታል\n"
        "3. የደርሰሶትን አጭር የሩፍ መልክት(sms) ሙሉውን ኮፒ(copy) በማድረግ ከታች ባለው የቴሌግራም የሩፍ መዢኛው ላይ ፔስት(paste) በማድረግ ይላኩት\n\n"
        f"የሚያጋጥሞት የክፍያ ችግር ካለ @BkbingosupportBot በዚህ ታችን ማውራት ይችላሉ"
    )
    bot.send_message(call.message.chat.id, instructions, parse_mode="HTML")

@bot.message_handler(func=lambda m: user_states.get(int(m.from_user.id)) == "WAITING_SMS_RECEIPT")
def handle_sms_receipt_verification(message):
    uid = int(message.from_user.id)
    text = message.text.strip()

    if len(text) < 15:
        bot.send_message(message.chat.id, "❌ <b>የላኩት የደረሰኝ ጽሁፍ በጣም አጭር ነው። እባክዎን ትክክለኛውን የባንክ/ቴሌብር አጭር መልእክት (SMS) ሙሉውን ኮፒ አድርገው ይላኩ።</b>", parse_mode="HTML")
        return

    txn_id_match = re.search(r'(?:Txn|ID|Ref|TRX)[^\w]?([A-Za-z0-9]{8,})', text, re.IGNORECASE)
    txn_id = txn_id_match.group(1) if txn_id_match else hashlib.md5(text.encode()).hexdigest()[:12]

    if txn_id in used_txn_ids:
        bot.send_message(message.chat.id, "❌ <b>ይህ የክፍያ ደረሰኝ አስቀድሞ ጥቅም ላይ ውሏል!</b>", parse_mode="HTML")
        return

    amounts = re.findall(r'(\d+(?:\.\d+)?)\s*(?:ETB|ብር|Birr)', text, re.IGNORECASE)
    if not amounts:
        amounts = re.findall(r'(?:Transferred|Sent|Paid|Received|Amount)[^\d]*(\d+(?:\.\d+)?)', text, re.IGNORECASE)

    if not amounts:
        numbers = [float(n) for n in re.findall(r'\b\d+(?:\.\d+)?\b', text) if float(n) >= 5.0]
        if numbers:
            deposit_amount = numbers[0] 
        else:
            bot.send_message(message.chat.id, "❌ <b>ከደረሰኙ ላይ የክፍያ መጠን ማግኘት አልተቻለም። እባክዎን ትክክለኛውን የSMS መልእክት ኮፒ አድርገው ይላኩ።</b>", parse_mode="HTML")
            return
    else:
        deposit_amount = float(amounts[0])

    if deposit_amount < 5.0:
        bot.send_message(message.chat.id, "❌ <b>የተገኘው የብር መጠን በጣም አነስተኛ ነው። እባክዎን ትክክለኛ ደረሰኝ ይላኩ።</b>", parse_mode="HTML")
        return

    user_states[uid] = None
    req_id = str(uuid.uuid4())[:8]
    pending_deposits[req_id] = {
        "user_id": uid,
        "amount": deposit_amount,
        "txn_id": txn_id,
        "text": text
    }

    bot.send_message(
        message.chat.id,
        f"⏳ <b>የክፍያ ጥያቄዎ ተቀብሏል!</b>\n\n💰 መጠን: <b>{deposit_amount:.2f} ETB</b>\n🔍 <i>አድሚኑ ደረሰኙን አጣርቶ በቅርቡ አካውንትዎ ላይ ይጨምረዋል።</i>",
        parse_mode="HTML"
    )

    admin_markup = InlineKeyboardMarkup(row_width=2)
    admin_markup.add(
        InlineKeyboardButton("✅ አረጋግጥ (Approve)", callback_data=f"adm_app_{req_id}"),
        InlineKeyboardButton("❌ ውድቅ አድርግ (Reject)", callback_data=f"adm_rej_{req_id}")
    )

    admin_alert = (
        f"🔔 <b>አዲስ የዲፖዚት ማረጋገጫ (Verification Request)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 ተጫዋች ID: <code>{uid}</code>\n"
        f"💰 መጠን: <b>{deposit_amount:.2f} ETB</b>\n"
        f"🆔 Txn ID: <code>{txn_id}</code>\n"
        f"📄 SMS: <i>{text[:150]}...</i>"
    )
    try:
        bot.send_message(ADMIN_ID, admin_alert, reply_markup=admin_markup, parse_mode="HTML")
    except Exception:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('adm_app_') or call.data.startswith('adm_rej_'))
def handle_admin_verification_action(call):
    if int(call.from_user.id) != ADMIN_ID:
        bot.answer_callback_query(call.id, "ይህ ትዕዛዝ ለአድሚን ብቻ የተፈቀደ ነው!", show_alert=True)
        return

    action, req_id = call.data.split('_')[1], call.data.split('_')[2]
    bot.answer_callback_query(call.id)

    if req_id not in pending_deposits:
        bot.edit_message_text("⚠️ ይህ ጥያቄ አስቀድሞ ተስተናግዷል ወይም አልፏል።", call.message.chat.id, call.message.message_id)
        return

    dep_info = pending_deposits.pop(req_id)
    uid = dep_info["user_id"]
    amount = dep_info["amount"]
    txn_id = dep_info["txn_id"]

    if action == "app":
        with db_lock:
            used_txn_ids.add(txn_id)
            if uid not in users_db:
                users_db[uid] = {"id": uid, "name": f"User {uid}", "balance": 0.0, "has_deposited": False, "history": []}
            
            users_db[uid]["balance"] += amount
            new_bal = users_db[uid]["balance"]
            users_db[uid]["has_deposited"] = True
            
            agent_owner_id = users_db[uid].get("agent_referred_by")
            if agent_owner_id and agent_owner_id in agents_db:
                agent_comm = amount * AGENT_COMMISSION_RATE
                agents_db[agent_owner_id]["balance"] += agent_comm
                agents_db[agent_owner_id]["total_earned"] += agent_comm
                try:
                    bot.send_message(
                        agent_owner_id,
                        f"🤝 <b>አዲስ የኤጀንት ኮሚሽን ደርሶዎታል!</b>\n\nበሊንክዎ የተመዘገበ ተጫዋች <b>{amount:.2f} ETB</b> ዲፖዚት በማድረጉ ምክንያት <b>{agent_comm:.2f} ETB</b> (5%) ኮሚሽን አግኝተዋል!",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

            referrer_id = users_db[uid].get("referred_by")
            if referrer_id and referrer_id in users_db:
                ref_user = users_db[referrer_id]
                ref_count = ref_user.get("referral_count", 0)
                
                if ref_count >= MILESTONE_REFERRAL_TARGET and not ref_user.get("milestone_rewarded", False):
                    ref_user["milestone_rewarded"] = True
                    ref_user["balance"] += MILESTONE_BONUS
                    ref_new_bal = ref_user["balance"]
                    
                    socketio.emit('balance_update', {'user_id': referrer_id, 'balance': ref_new_bal})
                    add_user_history(referrer_id, "ሪፈራል ቦነስ (Referral Milestone)", f"+{MILESTONE_BONUS:.2f} ETB ተሸልመዋል")
                    try:
                        bot.send_message(
                            referrer_id,
                            f"🎉 <b>ልዩ የሪፈራል ሽልማት አሸንፈዋል!</b>\n\nእስከ <b>{MILESTONE_REFERRAL_TARGET}</b> ሰዎችን በመጋበዝዎ ምክንያት የሲስተሙ የ<b>{MILESTONE_BONUS:.2f} ETB</b> ልዩ ቦነስ ወደ ባላንስዎ ገብቷል!\n💳 አዲሱ ባላንስዎ፦ <b>{ref_new_bal:.2f} ETB</b>",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass

        socketio.emit('balance_update', {'user_id': uid, 'balance': new_bal})
        add_user_history(uid, "ዲፖዚት (Deposit)", f"+{amount:.2f} ETB በአድሚን ጸድቋል")

        try:
            bot.send_message(
                uid,
                f"🎉 <b>ዲፖዚትዎ በአድሚን ጸድቋል!</b>\n\n💰 የተጨመረ: <b>+{amount:.2f} ETB</b>\n💳 አዲሱ ባላንስዎ: <b>{new_bal:.2f} ETB</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass

        bot.edit_message_text(
            f"✅ <b>ዲፖዚቱ ጸድቆ ለተጫዋች (<code>{uid}</code>) ተጭኗል!</b>\n💰 መጠን: {amount:.2f} ETB",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML"
        )
    else:
        try:
            bot.send_message(
                uid,
                f"❌ <b>የዲፖዚት ጥያቄዎ ውድቅ ተደርጓል (Rejected)።</b>\nእባክዎን ትክክለኛ የክፍያ ደረሰኝ መላክዎን ያረጋግጡ።",
                parse_mode="HTML"
            )
        except Exception:
            pass

        bot.edit_message_text(
            f"❌ <b>ዲፖዚቱ ውድቅ ተደርጓል (Rejected) ለተጫዋች (<code>{uid}</code>)።</b>",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML"
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith('wdmeth_'))
def handle_withdraw_method(call):
    uid = int(call.from_user.id)
    bank_code = call.data.split('_')[1]
    
    with db_lock:
        bal = users_db.get(uid, {}).get("balance", 0.0)

    if bal < MIN_WITHDRAWAL:
        bot.answer_callback_query(call.id, f"ዝቅተኛው የዊዝድሮው መጠን {MIN_WITHDRAWAL} ETB ነው!", show_alert=True)
        return

    method_name = "Telebirr" if bank_code == "Telebirr" else "CBE Birr"
    withdraw_data[uid] = {'bank_code': bank_code, 'method_name': method_name}
    user_states[uid] = "WAITING_WITHDRAW_ACC"
    
    bot.edit_message_text(
        f"✅ የተመረጠው ማውጫ፦ <b>{method_name}</b>\n\n📱 እባክዎን ገንዘቡ የሚላክበትን ትክክለኛ <b>የ{method_name} ስልክ ቁጥር ወይም የባንክ ሂሳብ ቁጥር</b> ብቻ ያስገቡ፦", 
        call.message.chat.id, 
        call.message.message_id, 
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda m: user_states.get(int(m.from_user.id)) == "WAITING_WITHDRAW_ACC")
def handle_withdraw_account(message):
    uid = int(message.from_user.id)
    account_num = message.text.strip()
    
    if uid not in withdraw_data:
        user_states[uid] = None
        return

    if not account_num.isdigit() or not (4 <= len(account_num) <= 20):
        bot.send_message(message.chat.id, "❌ <b>ስህተት፦ እባክዎን ትክክለኛ የባንክ አካውንት ቁጥር ወይም የስልክ ቁጥር ብቻ ያስገቡ።</b>", parse_mode="HTML")
        return

    withdraw_data[uid]['account'] = account_num
    user_states[uid] = "WAITING_WITHDRAW_AMT"
    
    with db_lock:
        bal = users_db.get(uid, {}).get("balance", 0.0)

    bot.send_message(
        message.chat.id, 
        f"👍 የተቀበልነው ቁጥር፦ <code>{account_num}</code>\n\n💰 ማውጣት የሚፈልጉትን <b>የገንዘብ መጠን (ETB)</b> ያስገቡ፦\n(የሚገኝ ባላንስ፦ <b>{bal:.2f} ETB</b>)", 
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda m: user_states.get(int(m.from_user.id)) == "WAITING_WITHDRAW_AMT")
def handle_withdraw_amount(message):
    uid = int(message.from_user.id)
    
    try:
        amount = float(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "❌ <b>እባክዎን ትክክለኛ የቁጥር መጠን ያስገቡ!</b>", parse_mode="HTML")
        return

    with db_lock:
        bal = users_db.get(uid, {}).get("balance", 0.0)

        if amount < MIN_WITHDRAWAL:
            bot.send_message(message.chat.id, f"❌ <b>ዝቅተኛው ማውጣት የሚችሉት መጠን {MIN_WITHDRAWAL:.2f} ETB ነው።</b>", parse_mode="HTML")
            return

        if amount > bal:
            bot.send_message(message.chat.id, f"❌ <b>በቂ ባላንስ የለዎትም።</b>\nየእርስዎ ባላንስ፦ <b>{bal:.2f} ETB</b>", parse_mode="HTML")
            return

        account = withdraw_data[uid]['account']
        method_name = withdraw_data[uid]['method_name']
        user_states[uid] = None

        users_db[uid]["balance"] -= amount
        current_bal = users_db[uid]["balance"]

    socketio.emit('balance_update', {'user_id': uid, 'balance': current_bal})
    add_user_history(uid, "ዊዝድሮ (Withdraw)", f"-{amount:.2f} ETB ወደ {method_name} ({account}) ተጠይቋል")

    success_msg = (
        f"📤 <b>የገንዘብ ማውጣት (Withdrawal) ጥያቄዎ ተቀባይነት አግኝቷል!</b>\n\n"
        f"💰 መጠን፦ <b>{amount:.2f} ETB</b>\n🏦 ዘዴ፦ <b>{method_name}</b>\n📱 ሂሳብ ቁጥር፦ <code>{account}</code>\n💳 የቀረ ባላንስ፦ <b>{current_bal:.2f} ETB</b>"
    )
    bot.send_message(message.chat.id, success_msg, parse_mode="HTML")

    wd_req_id = str(uuid.uuid4())[:8]
    pending_withdrawals[wd_req_id] = {
        "user_id": uid,
        "amount": amount,
        "account": account,
        "method_name": method_name
    }

    admin_markup = InlineKeyboardMarkup(row_width=2)
    admin_markup.add(
        InlineKeyboardButton("✅ ዊዝድሮ አረጋግጥ (Approve)", callback_data=f"wd_app_{wd_req_id}"),
        InlineKeyboardButton("❌ ውድቅ አድርግ (Reject & Refund)", callback_data=f"wd_rej_{wd_req_id}")
    )

    admin_info = (
        f"🔔 <b>አዲስ የገንዘብ ማውጣት (Withdraw) ጥያቄ!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 ተጫዋች ID: <code>{uid}</code>\n"
        f"💰 መጠን: <b>{amount:.2f} ETB</b>\n"
        f"📱 ሂሳብ ቁጥር: <code>{account}</code> ({method_name})"
    )
    try:
        bot.send_message(ADMIN_ID, admin_info, reply_markup=admin_markup, parse_mode="HTML")
    except Exception:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('wd_app_') or call.data.startswith('wd_rej_'))
def handle_admin_withdraw_action(call):
    if int(call.from_user.id) != ADMIN_ID:
        bot.answer_callback_query(call.id, "ይህ ትዕዛዝ ለአድሚን ብቻ የተፈቀደ ነው!", show_alert=True)
        return

    action, wd_req_id = call.data.split('_')[1], call.data.split('_')[2]
    bot.answer_callback_query(call.id)

    if wd_req_id not in pending_withdrawals:
        bot.edit_message_text("⚠️ ይህ የዊዝድሮ ጥያቄ አስቀድሞ ተስተናግዷል ወይም አልፏል።", call.message.chat.id, call.message.message_id)
        return

    wd_info = pending_withdrawals.pop(wd_req_id)
    uid = wd_info["user_id"]
    amount = wd_info["amount"]
    account = wd_info["account"]
    method_name = wd_info["method_name"]

    if action == "app":
        try:
            bot.send_message(
                uid,
                f"✅ <b>የገንዘብ ማውጣት (Withdrawal) ጥያቄዎ ተፈፅሟል!</b>\n\n💰 መጠን፦ <b>{amount:.2f} ETB</b> ተልኳል።\n🏦 ሂሳብ ቁጥር፦ <code>{account}</code> ({method_name})",
                parse_mode="HTML"
            )
        except Exception:
            pass

        bot.edit_message_text(
            f"✅ <b>ዊዝድሮው ጸድቆ ተልኳል!</b>\n👤 ተጫዋች: <code>{uid}</code>\n💰 መጠን: {amount:.2f} ETB",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML"
        )
    else:
        with db_lock:
            if uid not in users_db:
                users_db[uid] = {"id": uid, "name": f"User {uid}", "balance": 0.0, "history": []}
            users_db[uid]["balance"] += amount
            refunded_bal = users_db[uid]["balance"]

        socketio.emit('balance_update', {'user_id': uid, 'balance': refunded_bal})
        add_user_history(uid, "ዊዝድሮ ውድቅ (Withdraw Rejected)", f"{amount:.2f} ETB ተመላሽ (Refund) ሆኗል")

        try:
            bot.send_message(
                uid,
                f"❌ <b>የገንዘብ ማውጣት (Withdrawal) ጥያቄዎ ውድቅ ተደርጓል።</b>\n\n💰 የተወገደው <b>{amount:.2f} ETB</b> ወደ ባላንስዎ ተመልሷል (Refunded)።\n💳 አዲሱ ባላንስዎ፦ <b>{refunded_bal:.2f} ETB</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass

        bot.edit_message_text(
            f"❌ <b>ዊዝድሮው ውድቅ ተደርጎ ገንዘቡ ተመልሷል (Refunded)!</b>\n👤 ተጫዋች: <code>{uid}</code>\n💰 መጠን: {amount:.2f} ETB",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML"
        )

@support_bot.message_handler(commands=['start'])
def start_support_bot(message):
    text = message.text
    user_info = ""
    safe_name = message.from_user.first_name.replace('<', '&lt;').replace('>', '&gt;')
    
    if "USER_" in text and "_BAL_" in text:
        try:
            parts = text.split("USER_")[1].split("_BAL_")
            u_id = parts[0]
            bal = parts[1]
            user_info = f"\n\n👤 <b>የተጫዋች መረጃ፦</b>\n🆔 ID: <code>{u_id}</code>\n💰 ባላንስ: <b>{bal} ETB</b>"
        except Exception:
            pass

    welcome_msg = (
        f'<a href="{OPERATOR_IMAGE_URL}">&#8203;</a>'
        f"👋 ሰላም <b>{safe_name}</b>!\n\n"
        f"ወደ <b>BKBINGO Pro</b> የደንበኞች አገልግሎት እንኳን ደህና መጡ! 🎧{user_info}\n\n"
        f"ያጋጠመዎትን ችግር ወይም ጥያቄ በአንድ መልእክት ጽፈው ይላኩልን。"
    )
    support_bot.send_message(message.chat.id, welcome_msg, parse_mode="HTML")

@support_bot.message_handler(func=lambda m: int(m.from_user.id) != ADMIN_ID, content_types=['text', 'photo'])
def handle_support_inquiry(message):
    uid = int(message.from_user.id)
    safe_name = message.from_user.first_name.replace('<', '&lt;').replace('>', '&gt;')
    safe_msg = message.text.replace('<', '&lt;').replace('>', '&gt;') if message.text else 'Photo Sent'
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✍️ መልስ ስጥ (Reply)", callback_data=f"suppreply_{uid}"))

    admin_msg = (
        f"📩 <b>አዲስ የደንበኞች ጥያቄ!</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 ከ: {safe_name} (<code>{uid}</code>)\n"
        f"💬 መልእክት፦ {safe_msg}"
    )

    if message.photo:
        support_bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=admin_msg, reply_markup=markup, parse_mode="HTML")
    else:
        support_bot.send_message(ADMIN_ID, admin_msg, reply_markup=markup, parse_mode="HTML")

    confirm_msg = (
        f'<a href="{OPERATOR_IMAGE_URL}">&#8203;</a>'
        "✅ <b>መልእክትዎ ለደንበኞች አገልግሎት ደርሷል!</b>"
    )
    support_bot.send_message(message.chat.id, confirm_msg, parse_mode="HTML")

@support_bot.callback_query_handler(func=lambda call: call.data.startswith('suppreply_'))
def prepare_support_reply(call):
    target_uid = int(call.data.split('_')[1])
    admin_reply_state[ADMIN_ID] = target_uid
    support_bot.answer_callback_query(call.id)
    support_bot.send_message(ADMIN_ID, f"✍️ ለ ተጫዋች <code>{target_uid}</code> የሚላከውን መልስ አሁን ይጻፉ፦", parse_mode="HTML")

@support_bot.message_handler(func=lambda m: int(m.from_user.id) == ADMIN_ID and ADMIN_ID in admin_reply_state)
def send_support_reply(message):
    target_uid = admin_reply_state.pop(ADMIN_ID, None)
    if target_uid:
        safe_text = message.text.replace('<', '&lt;').replace('>', '&gt;')
        reply_msg = (
            f'<a href="{OPERATOR_IMAGE_URL}">&#8203;</a>'
            f"🎧 <b>ከደንበኞች አገልግሎት የተሰጠ መልስ፦</b>\n━━━━━━━━━━━━━━━\n{safe_text}"
        )
        try:
            support_bot.send_message(target_uid, reply_msg, parse_mode="HTML")
            support_bot.send_message(ADMIN_ID, f"✅ መልሱ ለተጫዋች <code>{target_uid}</code> በተሳካ ሁኔታ ተልቋል!", parse_mode="HTML")
        except Exception as ex:
            support_bot.send_message(ADMIN_ID, f"❌ መልእክቱን መላክ አልተቻለም፦ {ex}", parse_mode="HTML")

@socketio.on('get_user_balance')
def handle_get_balance(data):
    if not data or 'user_id' not in data:
        return
    uid = int(data.get('user_id'))
    with db_lock:
        if uid not in users_db:
            users_db[uid] = {"id": uid, "name": f"User {uid}", "balance": 0.0, "history": []}
        bal = users_db[uid]["balance"]
    emit('balance_update', {'user_id': uid, 'balance': bal})

@socketio.on('select_card')
def handle_card_selection(data):
    if game_state["status"] == "PLAYING":
        emit('error_msg', {'msg': 'ጨዋታው ተጀምሯል። እባክዎን አዲሱን ዙር ይጠብጉ!'})
        return

    uid = int(data.get('user_id'))
    card_id = int(data.get('card_id'))

    with db_lock:
        if uid not in users_db:
            users_db[uid] = {"id": uid, "name": f"User {uid}", "balance": 0.0, "history": []}

        bal = users_db[uid]["balance"]
        
        if card_id in game_state['selected_cards'].values():
            emit('error_msg', {'msg': 'ይህ ካርቴላ አስቀድሞ በሌላ ተጫዋች ተይዟል!'})
            return

        user_cards = game_state['player_cards'].get(uid, [])
        if len(user_cards) >= MAX_CARDS_PER_PLAYER:
            emit('error_msg', {'msg': f'በአንድ ዙር ቢበዛ {MAX_CARDS_PER_PLAYER} ካርቴላ ብቻ መግዛት ይቻላል!'})
            return

        if bal < CARD_PRICE:
            emit('error_msg', {'msg': 'በቂ ባላንስ የሎትም። እባክዎን አስቀድመው ዲፖዚት ያድርጉ።'})
            return

        users_db[uid]["balance"] -= CARD_PRICE
        new_bal = users_db[uid]["balance"]
        
        game_state['selected_cards'][f"{uid}_{card_id}"] = card_id
        if uid not in game_state['player_cards']:
            game_state['player_cards'][uid] = []
        game_state['player_cards'][uid].append(card_id)

    matrix = cards_database.get(card_id)
    emit('card_confirmed', {'card_id': card_id, 'matrix': matrix, 'new_balance': new_bal}, broadcast=False)
    emit('balance_update', {'user_id': uid, 'balance': new_bal}, broadcast=False)
    socketio.emit('update_selected_cards', {'taken_cards': list(game_state['selected_cards'].values())})

@socketio.on('player_mark_number')
def handle_player_mark(data):
    uid = int(data.get('user_id'))
    card_id = int(data.get('card_id'))
    marked_list = data.get('marked_numbers', [])

    if uid not in player_marked_hits:
        player_marked_hits[uid] = {}
    player_marked_hits[uid][card_id] = set(marked_list)

@socketio.on('claim_bingo')
def handle_claim_bingo(data):
    uid = int(data.get('user_id'))
    card_id = int(data.get('card_id'))
    board = data.get('board')

    if game_state["status"] != "PLAYING":
        emit('bingo_response', {'status': 'error', 'message': '❌ ጨዋታው ገና አልተጀመረም!'})
        return

    if uid not in game_state['player_cards'] or card_id not in game_state['player_cards'][uid]:
        emit('bingo_response', {'status': 'error', 'message': '❌ ይህ ካርቴላ የእርስዎ አይደለም!'})
        return

    if not validate_bingo_board(board):
        emit('bingo_response', {'status': 'error', 'message': '❌ የተሳሳተ የቢንጎ እሰጥ አገባብ! (Bingo pattern not complete)'})
        return

    game_state["status"] = "FINISHED"
    
    total_cards_sold = len(game_state['selected_cards'])
    total_pool = total_cards_sold * CARD_PRICE
    admin_commission = total_pool * COMMISSION_RATE
    winner_prize = total_pool - admin_commission

    with db_lock:
        if uid not in users_db:
            users_db[uid] = {"id": uid, "balance": 0.0, "history": []}
        users_db[uid]["balance"] += winner_prize
        new_bal = users_db[uid]["balance"]
        winner_name = users_db[uid].get("name", f"User {uid}")

    add_user_history(uid, "የቢንጎ አሸናፊ (Bingo Win)", f"+{winner_prize:.2f} ETB ከካርቴላ #{card_id} አሸንፈዋል")
    socketio.emit('balance_update', {'user_id': uid, 'balance': new_bal})

    winner_matrix = cards_database.get(card_id)
    socketio.emit('winner_announced', {
        'winner_name': winner_name,
        'winner_ids': [uid],
        'prize': winner_prize,
        'card_id': card_id,
        'card_matrix': winner_matrix
    })

    def delayed_reset():
        time.sleep(8)
        game_state["status"] = "WAITING"
        game_state["drawn_numbers"] = []
        game_state["selected_cards"] = {}
        game_state["player_cards"] = {}
        game_state["derash"] = 0.0
        player_marked_hits.clear()
        socketio.emit('reset_game')

    Thread(target=delayed_reset).start()
    emit('bingo_response', {'status': 'success', 'message': f'🎉 እንኳን ደስ አለዎት! {winner_prize:.2f} ETB አሸንፈዋል!'})

def background_game_loop():
    while True:
        if game_state["status"] == "WAITING":
            if len(game_state["selected_cards"]) > 0:
                game_state["time_left"] -= 1
                total_cards = len(game_state["selected_cards"])
                game_state["derash"] = (total_cards * CARD_PRICE) * (1.0 - COMMISSION_RATE)
                
                socketio.emit('timer_update', {
                    'time_left': game_state["time_left"],
                    'sold_count': total_cards,
                    'derash': game_state["derash"]
                })

                if game_state["time_left"] <= 0:
                    game_state["status"] = "PLAYING"
                    game_state["drawn_numbers"] = []
                    socketio.emit('game_started', {'derash': game_state["derash"]})
            else:
                game_state["time_left"] = 15
                socketio.emit('timer_update', {'time_left': 15, 'sold_count': 0, 'derash': 0.0})
        
        elif game_state["status"] == "PLAYING":
            available_balls = [b for b in range(1, 76) if b not in game_state["drawn_numbers"]]
            if available_balls and len(game_state["drawn_numbers"]) < 75:
                next_ball = random.choice(available_balls)
                game_state["drawn_numbers"].append(next_ball)

                def get_letter_and_display(num):
                    if 1 <= num <= 15: return {'letter': 'B', 'display': f'B-{num}'}
                    if 16 <= num <= 30: return {'letter': 'I', 'display': f'I-{num}'}
                    if 31 <= num <= 45: return {'letter': 'N', 'display': f'N-{num}'}
                    if 46 <= num <= 60: return {'letter': 'G', 'display': f'G-{num}'}
                    if 61 <= num <= 75: return {'letter': 'O', 'display': f'O-{num}'}
                    return {'letter': '', 'display': str(num)}

                ball_info = get_letter_and_display(next_ball)
                socketio.emit('new_number', {
                    'ball': next_ball,
                    'display': ball_info['display'],
                    'letter': ball_info['letter']
                })
            else:
                game_state["status"] = "FINISHED"
                def force_reset():
                    time.sleep(5)
                    game_state["status"] = "WAITING"
                    game_state["drawn_numbers"] = []
                    game_state["selected_cards"] = {}
                    game_state["player_cards"] = {}
                    game_state["derash"] = 0.0
                    player_marked_hits.clear()
                    socketio.emit('reset_game')
                Thread(target=force_reset).start()

        time.sleep(1.5)

if __name__ == '__main__':
    set_bot_commands()
    Thread(target=background_game_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
