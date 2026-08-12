import eventlet
Eventlet.monkey_patch(all=True)

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

Bot = telebot.TeleBot(MAIN_BOT_TOKEN)
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
MAX_CARDS_PER_PLAYER = 2 
MIN_WITHDRAWAL = 50.0   # ዝቅተኛው ዊዝድሮው
MILESTONE_REFERRAL_TARGET = 100  # 100 ሰው ሲጋብዝ
MILESTONE_BONUS = 500.0          # 500 ብር ቦነስ

OPERATOR_IMAGE_URL = os.environ.get("OPERATOR_IMAGE_URL", "https://i.ibb.co/6y4GfJ2/customer-service-operator.jpg")

# DATABASE, LOCKS & USER STATES
Db_lock = Lock()
Users_db = {}            
User_states = {}         
Deposit_data = {}        
Withdraw_data = {}       
Admin_reply_state = {}   
Pending_deposits = {}    
Pending_withdrawals = {} 
Used_txn_ids = set()     
Broadcast_state = {}     

# =========================================================
# 2. BINGO CARDS DATABASE (1-104 CARDS)
# =========================================================
Cards_database = {}

def generate_official_bingo_card(card_id):
    Seed = int(card_id) * 997
    Def get_col(min_v, max_v, count):
        Nums = list(range(min_v, max_v + 1))
        Nums.sort(key=lambda x: (abs(hash(str(seed + x)))))
        Return sorted(nums[:count])

    B = get_col(1, 15, 5)
    I = get_col(16, 30, 5)
    N = get_col(31, 45, 4) 
    G = get_col(46, 60, 5)
    O = get_col(61, 75, 5)

    Matrix = []
    For r in range(5):
        Row = [
            B[r],
            I[r],
            'FREE' if r == 2 else (n[r] if r < 2 else n[r-1]),
            G[r],
            O[r]
        ]
        Matrix.append(row)
    Return matrix

For c_num in range(1, 105):
    Cards_database[c_num] = generate_official_bingo_card(c_num)

Def get_letter_and_display(num):
    If num >= 1 and num <= 15: return {'letter': 'B', 'display': f'B-{num}'}
    If num >= 16 and num <= 30: return {'letter': 'I', 'display': f'I-{num}'}
    If num >= 31 and num <= 45: return {'letter': 'N', 'display': f'N-{num}'}
    If num >= 46 and num <= 60: return {'letter': 'G', 'display': f'G-{num}'}
    If num >= 61 and num <= 75: return {'letter': 'O', 'display': f'O-{num}'}
    Return {'letter': '', 'display': str(num)}

# =========================================================
# 3. GAME STATE & BINGO WINNER CHECKER
# =========================================================
Game_state = {
    "status": "WAITING",
    "time_left": 15,
    "drawn_numbers": [],
    "selected_cards": {},  
    "player_cards": {},    
    "derash": 0.0
}

Def validate_bingo_board(board):
    If not board or len(board) != 5:
        Return False

    For r in range(5):
        If all(board[r][c] for c in range(5)):
            Return True

    For c in range(5):
        If all(board[r][c] for r in range(5)):
            Return True

    If all(board[i][i] for i in range(5)):
        Return True
    If all(board[i][4 - i] for i in range(5)):
        Return True

    Return False

# =========================================================
# 4. FRONTEND HTML TEMPLATE
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
        Body { 
            Font-family: 'Poppins', sans-serif; 
            Background: linear-gradient(135deg, #0f172a 0%, #020617 100%);
            Color: #fff; 
            Min-height: 100vh; 
        }
        .font-orbitron { font-family: 'Orbitron', sans-serif; }
        .glass-panel { 
            Background: rgba(30, 41, 59, 0.7); 
            Backdrop-filter: blur(16px); 
            Border: 1px solid rgba(255, 255, 255, 0.1); 
            Box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }
        .gold-gradient-text { 
            Background: linear-gradient(135deg, #fef08a 0%, #facc15 50%, #ca8a04 100%); 
            -webkit-background-clip: text; 
            -webkit-text-fill-color: transparent; 
        }
        .ball-glow { 
            Background: radial-gradient(circle at 30% 30%, #a855f7 0%, #6b21a8 60%, #3b0764 100%);
            Box-shadow: 0 0 25px rgba(168, 85, 247, 0.6);
        }
        .card-btn-selected { 
            Background: linear-gradient(135deg, #10b981 0%, #047857 100%) !important; 
            Color: #ffffff !important; 
            Border-color: #34d399 !important;
            Box-shadow: 0 0 12px rgba(16, 185, 129, 0.5);
        }
        .card-btn-taken {
            Background: #334155 !important;
            Color: #64748b !important;
            Border-color: #475569 !important;
            Cursor: not-allowed;
            Opacity: 0.6;
        }
        .bingo-hit { 
            Background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important; 
            Color: #ffffff !important; 
            Font-weight: 800 !important;
            Box-shadow: inset 0 0 6px rgba(255, 255, 255, 0.6);
        }
        .bingo-header-b { background: #ef4444; color: #fff; }
        .bingo-header-i { background: #3b82f6; color: #fff; }
        .bingo-header-n { background: #eab308; color: #000; }
        .bingo-header-g { background: #10b981; color: #fff; }
        .bingo-header-o { background: #a855f7; color: #fff; }

        /* የተስተካከሉ አዳዲስ የስታይል ማሻሻያዎች (ከድምፅ ማንቂያ ባር እና ከካርዶች ጋር የተጣጣመ) */
        #audio-banner {
            Padding: 6px 12px;
            Font-size: 11px;
            Margin-bottom: 6px;
            Border-radius: 12px;
        }
        .stat-card {
            Border-radius: 12px;
            Border: 2px solid rgba(255, 255, 255, 0.1);
            Padding: 8px;
            Display: flex;
            Flex-direction: column;
            Align-items: center;
            Justify-content: center;
        }
        .bingo-card-container {
            Width: 100%;
            Max-width: 100%;
        }
        .bingo-cell-custom {
            Font-size: 14px; 
            Font-weight: 500; 
            Padding: 10px 2px;
        }
    </style>
</head>
<body class="select-none pb-10 px-3">
    <div id="audio-banner" class="bg-amber-500 border border-amber-400 my-1 flex justify-between items-center shadow-lg animate-pulse">
        <span class="text-slate-950 font-black">🔊 የድምፅ ማስታወቂያ ለማንቃት ይጫኑ!</span>
        <button onclick="enableAudioSystem()" class="bg-slate-950 text-amber-400 px-2 py-1 rounded font-black text-[10px] shadow">አንቃ</button>
    </div>

    <div class="relative overflow-hidden rounded-2xl mt-1 mb-2 border border-purple-500/30 glass-panel">
        <div class="p-3 flex justify-between items-center">
            <div class="flex items-center gap-2">
                <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-purple-600 to-amber-400 flex items-center justify-center font-black text-lg shadow-lg">🎯</div>
                <div>
                    <h1 class="font-orbitron text-base font-black gold-gradient-text tracking-wider">BKBINGO PRO</h1>
                    <p class="text-[9px] text-purple-300/80">LIVE CASINO BINGO</p>
                </div>
            </div>
            <div class="bg-emerald-500/20 border border-emerald-500/40 px-2.5 py-1 rounded-xl text-right">
                <div class="text-[9px] text-emerald-300 font-bold">ሒሳብ (BAL)</div>
                <div id="user-balance-disp" class="text-xs font-black text-emerald-400">0.00 ETB</div>
            </div>
        </div>
    </div>

    <div class="grid grid-cols-3 gap-2 mb-2 text-center text-xs font-bold">
        <div class="glass-panel stat-card border-l-4 border-amber-400">
            <span class="text-[9px] text-slate-400 block mb-0.5">የተሸጡ ካርቴላዎች</span>
            <span id="sold-count" class="text-amber-400 text-sm font-black">0</span>
        </div>
        <div class="glass-panel stat-card border-l-4 border-rose-500">
            <span class="text-[9px] text-slate-400 block mb-0.5">የቀረ ጊዜ</span>
            <span id="timer" class="text-rose-400 text-sm font-black">15s</span>
        </div>
        <div class="glass-panel stat-card border-l-4 border-purple-500">
            <span class="text-[9px] text-slate-400 block mb-0.5">የወጡ ኳሶች</span>
            <span id="balls-count" class="text-purple-300 text-sm font-black">0/75</span>
        </div>
    </div>

    <div id="selection-screen">
        <div class="flex justify-between items-center mb-2 px-1">
            <span class="text-xs font-bold text-slate-300">ካርቴላ ይምረጡ (1-104)</span>
            <span class="text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full border border-amber-500/20">ዋጋ: 10 ETB</span>
        </div>

        <div id="cartela-grid" class="grid grid-cols-8 gap-1.5 glass-panel p-3 rounded-2xl max-h-[35vh] overflow-y-auto border border-slate-800"></div>
        <p class="text-center text-[10px] text-slate-400 my-2">⚠️ በአንድ ዙር መግዛት የሚችሉት ቢበዛ 2 ካርቴላዎች ብቻ ናቸው።</p>
        
        <div id="preview-cards-container" class="grid grid-cols-1 gap-2 mt-2"></div>
    </div>

    <div id="game-screen" class="hidden mt-2">
        <div class="glass-panel p-3 rounded-2xl mb-2 flex justify-between items-center border border-emerald-500/30">
            <div>
                <span class="text-[9px] text-slate-400 block">የአሸናፊው ደራሽ (PRIZE)</span>
                <span class="text-base font-black text-emerald-400" id="derash-amount">0 ETB</span>
            </div>
            <div class="text-right">
                <span class="text-[9px] text-slate-400 block">የተጠራው ኳስ</span>
                <span id="game-balls-count" class="text-xs font-bold text-purple-300">0/75</span>
            </div>
        </div>

        <div class="flex gap-2">
            <div class="w-1/3 glass-panel rounded-2xl p-1.5 border border-slate-800">
                <div class="text-[9px] font-bold text-center text-slate-400 mb-1">የወጡ ቁጥሮች</div>
                <div id="bingo-75-grid" class="grid grid-cols-1 gap-1 text-center text-[9px] max-h-[40vh] overflow-y-auto"></div>
            </div>

            <div class="w-2/3 flex flex-col items-center">
                <div id="current-ball" class="w-20 h-20 rounded-full ball-glow flex items-center justify-center text-lg font-black mb-2 border-2 border-purple-300/50 transform transition-all duration-300 text-center px-1">
                    READY
                </div>
                <div id="my-cards-container" class="w-full space-y-3"></div>
            </div>
        </div>
    </div>

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
        Const sounds = {
            Click: new Audio('https://assets.mixkit.co/active_storage/sfx/2568/2568-preview.mp3'),
            Win: new Audio('https://assets.mixkit.co/active_storage/sfx/2701/2701-preview.mp3'),
            Error: new Audio('https://assets.mixkit.co/active_storage/sfx/2572/2572-preview.mp3')
        };

        Function playSound(effectName) {
            If (sounds[effectName]) {
                Sounds[effectName].currentTime = 0;
                Sounds[effectName].volume = 0.5;
                Sounds[effectName].play().catch(e => console.log("Audio restriction:", e));
            }
        }

        Let speechUnlocked = false;

        Function enableAudioSystem() {
            If ('speechSynthesis' in window) {
                Const utterance = new SpeechSynthesisUtterance("ድምፅ ተጀምሯል");
                Utterance.lang = 'am-ET';
                Utterance.volume = 1.0;
                Window.speechSynthesis.speak(utterance);
                SpeechUnlocked = true;
                Const banner = document.getElementById('audio-banner');
                If (banner) banner.style.display = 'none';
            }
        }

        Function speakNumber(ballNum, displayStr) {
            If (!('speechSynthesis' in window)) return;
            Let letterName = '';
            If (ballNum >= 1 && ballNum <= 15) letterName = 'ቢ';
            Else if (ballNum >= 16 && ballNum <= 30) letterName = 'አይ';
            Else if (ballNum >= 31 && ballNum <= 45) letterName = 'ኤን';
            Else if (ballNum >= 46 && ballNum <= 60) letterName = 'ጂ';
            Else if (ballNum >= 61 && ballNum <= 75) letterName = 'ኦ';

            Const phrase = `${letterName} ${ballNum}`;
            Try {
                Window.speechSynthesis.cancel();
                Const utterance = new SpeechSynthesisUtterance(phrase);
                Utterance.lang = 'am-ET';
                Utterance.rate = 0.85;
                Utterance.pitch = 1.0;
                Utterance.volume = 1.0;
                Window.speechSynthesis.speak(utterance);
            } catch (e) {
                Console.log("Speech error:", e);
            }
        }

        Document.addEventListener('click', () => {
            If (!speechUnlocked && 'speechSynthesis' in window) {
                EnableAudioSystem();
            }
        }, { once: true });

        Const socket = io();
        Let userId = null;
        Let takenCards = [];

        If (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initDataUnsafe && window.Telegram.WebApp.initDataUnsafe.user) {
            UserId = parseInt(window.Telegram.WebApp.initDataUnsafe.user.id);
            Window.Telegram.WebApp.expand();
        } else {
            Const urlParams = new URLSearchParams(window.location.search);
            UserId = parseInt(urlParams.get('user_id')) || 12345;
        }

        Let mySelectedCards = [];
        Let drawnNumbersSet = new Set();
        Let markedNumbersMap = {}; 
        Let cardsDatabase = {};

        Socket.on('connect', () => {
            If (userId) {
                Socket.emit('get_user_balance', { user_id: userId });
            }
        });

        Socket.on('balance_update', (data) => {
            If(parseInt(data.user_id) === userId) {
                Document.getElementById('user-balance-disp').innerText = `${parseFloat(data.balance).toFixed(2)} ETB`;
            }
        });

        Socket.on('error_msg', (data) => {
            PlaySound('error');
            Alert("⚠️ " + data.msg);
        });

        Socket.on('bingo_response', (data) => {
            If (data.status === 'success') {
                PlaySound('win');
            } else {
                PlaySound('error');
            }
            Alert(data.message);
        });

        Function getFrontendLetterAndDisplay(num) {
            If (num >= 1 && num <= 15) return `B-${num}`;
            If (num >= 16 && num <= 30) return `I-${num}`;
            If (num >= 31 && num <= 45) return `N-${num}`;
            If (num >= 46 && num <= 60) return `G-${num}`;
            If (num >= 61 && num <= 75) return `O-${num}`;
            Return `${num}`;
        }

        Function init75Grid() {
            Const grid = document.getElementById('bingo-75-grid');
            Grid.innerHTML = '';
            For(let i=1; i<=75; i++) {
                Const cell = document.createElement('div');
                Cell.id = `ball-cell-${i}`;
                Cell.className = 'p-1 bg-slate-800/80 rounded text-slate-400 font-bold text-[9px]';
                Cell.innerText = getFrontendLetterAndDisplay(i);
                Grid.appendChild(cell);
            }
        }

        Function initCartelaGrid() {
            Const gridContainer = document.getElementById('cartela-grid');
            GridContainer.innerHTML = '';
            For (let i = 1; i <= 104; i++) {
                Const btn = document.createElement('button');
                Const isSelected = mySelectedCards.includes(i);
                Const isTaken = takenCards.includes(i) && !isSelected;

                If (isTaken) {
                    Btn.className = 'p-2 text-xs font-black rounded-xl border card-btn-taken';
                    Btn.disabled = true;
                } else if (isSelected) {
                    Btn.className = 'p-2 text-xs font-black rounded-xl border card-btn-selected';
                } else {
                    Btn.className = 'p-2 text-xs font-black rounded-xl border bg-slate-800/80 text-slate-200 border-slate-700/60 active:scale-95';
                    Btn.onclick = () => {
                        If (mySelectedCards.length >= 2) {
                            PlaySound('error');
                            Return alert("⚠️ በአንድ ዙር ቢበዛ 2 ካርቴላ ብቻ መግዛት ይቻላል!");
                        }
                        PlaySound('click');
                        Socket.emit('select_card', { user_id: userId, card_id: i });
                    };
                }
                Btn.innerText = i;
                GridContainer.appendChild(btn);
            }
        }

        Socket.on('update_selected_cards', (data) => {
            TakenCards = data.taken_cards || [];
            InitCartelaGrid();
        });

        Socket.on('card_confirmed', (data) => {
            PlaySound('click');
            If(!mySelectedCards.includes(data.card_id)) mySelectedCards.push(data.card_id);
            CardsDatabase[data.card_id] = data.matrix;
            If(!markedNumbersMap[data.card_id]) markedNumbersMap[data.card_id] = new Set();
            InitCartelaGrid();
            RenderPreviewCards();
            Document.getElementById('user-balance-disp').innerText = `${parseFloat(data.new_balance).toFixed(2)} ETB`;
        });

        Function createCardHTML(cid, matrix, isPlayMode = false) {
            Const cardDiv = document.createElement('div');
            CardDiv.className = 'glass-panel p-3 rounded-2xl w-full border border-slate-700/80 bingo-card-container';
            CardDiv.innerHTML = `<div class="text-xs font-black text-amber-400 mb-2 text-center">ካርቴላ #${cid}</div>`;

            Const mGrid = document.createElement('div');
            MGrid.className = 'grid grid-cols-5 gap-1 text-center font-bold text-xs bg-slate-950/80 p-2 rounded-xl mb-2.5';

            Const headers = [
                { title: 'B', class: 'bingo-header-b' },
                { title: 'I', class: 'bingo-header-i' },
                { title: 'N', class: 'bingo-header-n' },
                { title: 'G', class: 'bingo-header-g' },
                { title: 'O', class: 'bingo-header-o' }
            ];

            Headers.forEach(h => {
                Const hCell = document.createElement('div');
                HCell.className = `p-1 rounded-lg font-black text-[11px] ${h.class}`;
                HCell.innerText = h.title;
                MGrid.appendChild(hCell);
            });

            Matrix.forEach(row => {
                Row.forEach(val => {
                    Const cell = document.createElement('div');
                    If(isPlayMode) cell.id = `card-${cid}-val-${val}`;
                    
                    Const isFree = val === 'FREE';
                    Const isMarked = isFree || (markedNumbersMap[cid] && markedNumbersMap[cid].has(val));

                    Cell.className = `rounded-lg bingo-cell-custom transition-all ${
                        IsFree 
                        ? 'bg-amber-500 text-slate-950 font-black text-[12px]' 
                        : (isMarked ? 'bingo-hit' : 'bg-slate-800/90 text-slate-200 cursor-pointer')
                    }`;
                    Cell.innerText = val;

                    If (isPlayMode && !isFree) {
                        Cell.onclick = () => {
                            If (!drawnNumbersSet.has(val)) {
                                PlaySound('error');
                                Return alert("⚠️ ይህ ቁጥር ገና አልተጠራም!");
                            }
                            PlaySound('click');
                            If (!markedNumbersMap[cid]) markedNumbersMap[cid] = new Set();
                            MarkedNumbersMap[cid].add(val);
                            
                            Cell.className = 'rounded-lg bingo-cell-custom bingo-hit scale-105 transition-all';
                            
                            Socket.emit('player_mark_number', {
                                User_id: userId,
                                Card_id: cid,
                                Marked_numbers: Array.from(markedNumbersMap[cid])
                            });
                        };
                    }
                    MGrid.appendChild(cell);
                });
            });

            CardDiv.appendChild(mGrid);

            If (isPlayMode) {
                Const claimBtn = document.createElement('button');
                ClaimBtn.className = 'w-full py-2 bg-gradient-to-r from-emerald-500 to-green-600 hover:from-emerald-400 hover:to-green-500 text-slate-950 font-black text-xs rounded-xl shadow-lg shadow-emerald-500/20 border border-emerald-400/50 transform active:scale-95 transition-all';
                ClaimBtn.innerHTML = `🎉 BINGO ለካርቴላ #${cid}`;
                ClaimBtn.onclick = () => {
                    PlaySound('click');
                    Const matrixData = cardsDatabase[cid];
                    Const markedSet = markedNumbersMap[cid] || new Set();

                    Let boardValidationMatrix = [];
                    For(let r=0; r<5; r++) {
                        Let rowArr = [];
                        For(let c=0; c<5; c++) {
                            Let val = matrixData[r][c];
                            Let isHit = (val === 'FREE' || markedSet.has(val));
                            RowArr.push(isHit);
                        }
                        BoardValidationMatrix.push(rowArr);
                    }

                    Socket.emit('claim_bingo', { user_id: userId, card_id: cid, board: boardValidationMatrix });
                };
                CardDiv.appendChild(claimBtn);
            }

            Return cardDiv;
        }

        Function renderPreviewCards() {
            Const container = document.getElementById('preview-cards-container');
            Container.innerHTML = '';
            MySelectedCards.forEach(cid => {
                Const matrix = cardsDatabase[cid];
                If(!matrix) return;
                Container.appendChild(createCardHTML(cid, matrix, false));
            });
        }

        Socket.on('timer_update', (data) => {
            Document.getElementById('timer').innerText = `${data.time_left}s`;
            Document.getElementById('sold-count').innerText = data.sold_count;
        });

        Socket.on('game_started', (data) => {
            DrawnNumbersSet.clear();
            MarkedNumbersMap = {};
            MySelectedCards.forEach(cid => { markedNumbersMap[cid] = new Set(); });
            Init75Grid();
            Document.getElementById('selection-screen').classList.add('hidden');
            Document.getElementById('game-screen').classList.remove('hidden');
            Document.getElementById('derash-amount').innerText = `${parseFloat(data.derash).toFixed(2)} ETB`;
            RenderMyGameCards();
        });

        Function renderMyGameCards() {
            Const container = document.getElementById('my-cards-container');
            Container.innerHTML = '';
            MySelectedCards.forEach(cid => {
                Const matrix = cardsDatabase[cid];
                If(!matrix) return;
                Container.appendChild(createCardHTML(cid, matrix, true));
            });
        }

        Socket.on('new_number', (data) => {
            Const ball = data.ball;
            Const displayStr = data.display;
            DrawnNumbersSet.add(ball);
            
            SpeakNumber(ball, displayStr);

            Const ballEl = document.getElementById('current-ball');
            BallEl.innerText = displayStr;
            BallEl.classList.add('scale-110');
            SetTimeout(() => ballEl.classList.remove('scale-110'), 200);

            Document.getElementById('game-balls-count').innerText = `${drawnNumbersSet.size}/75`;
            
            Const cell75 = document.getElementById(`ball-cell-${ball}`);
            If(cell75) {
                Cell75.className = 'p-1 bg-amber-400 text-slate-950 font-black rounded shadow-lg scale-105 transition-all text-[9px]';
            }
        });

        Socket.on('winner_announced', (data) => {
            PlaySound('win');
            Document.getElementById('winner-name').innerText = `${data.winner_name} አሸንፏል!`;
            Document.getElementById('winner-prize').innerText = `${parseFloat(data.prize).toFixed(2)} ETB`;
            
            If(data.winner_ids && data.winner_ids.includes(userId)) {
                Socket.emit('get_user_balance', { user_id: userId });
            }

            Const wGrid = document.getElementById('winner-card-matrix');
            WGrid.innerHTML = '';
            If(data.card_matrix) {
                WGrid.appendChild(createCardHTML(data.card_id, data.card_matrix, false));
            }
            Document.getElementById('winner-modal').classList.remove('hidden');
        });

        Socket.on('reset_game', () => {
            MySelectedCards = [];
            TakenCards = [];
            DrawnNumbersSet.clear();
            MarkedNumbersMap = {};
            Document.getElementById('winner-modal').classList.add('hidden');
            Document.getElementById('game-screen').classList.add('hidden');
            Document.getElementById('selection-screen').classList.remove('hidden');
            Document.getElementById('preview-cards-container').innerHTML = '';
            InitCartelaGrid();
            If(userId) socket.emit('get_user_balance', { user_id: userId });
        });

        InitCartelaGrid();
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    Return render_template_string(HTML_TEMPLATE)

# =========================================================
# 5. TELEGRAM MAIN BOT & COMMAND HANDLERS
# =========================================================
Def main_menu_keyboard(user_id):
    Markup = InlineKeyboardMarkup(row_width=2)
    App_url = f"{RENDER_WEBAPP_URL}?user_id={user_id}"
    
    With db_lock:
        User_bal = users_db.get(int(user_id), {}).get("balance", 0.0)
    Support_deep_link = f"https://t.me/BkbingosupportBot?start=USER_{user_id}_BAL_{int(user_bal)}"

    Markup.add(InlineKeyboardButton(text="🎲 ጨዋታ ጀምር (Open App)", web_app=WebAppInfo(url=app_url)))
    Markup.add(
        InlineKeyboardButton(text="👤 ፕሮፋይል / ባላንስ", callback_data="btn_profile"),
        InlineKeyboardButton(text="📥 ዲፖዚት (Deposit)", callback_data="btn_deposit")
    )
    Markup.add(
        InlineKeyboardButton(text="📤 ዊዝድሮው (Withdraw)", callback_data="btn_withdraw"),
        InlineKeyboardButton(text="👥 ሪፈራል / ግብዣ", callback_data="btn_referral")
    )
    Markup.add(
        InlineKeyboardButton(text="📜 የግብይት እና ጨዋታ ታሪክ (History)", callback_data="btn_history")
    )
    Markup.add(
        InlineKeyboardButton(text="ℹ️ እርዳታ እና ህጎች", callback_data="btn_help"),
        InlineKeyboardButton(text="🎧 የደንበኞች አገልግሎት", url=support_deep_link)
    )
    Return markup

Def add_user_history(uid, history_type, details):
    With db_lock:
        If uid in users_db:
            If "history" not in users_db[uid]:
                Users_db[uid]["history"] = []
            Timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            Users_db[uid]["history"].insert(0, {
                "time": timestamp,
                "type": history_type,
                "details": details
            })
            If len(users_db[uid]["history"]) > 20:
                Users_db[uid]["history"].pop()

Def set_bot_commands():
    Commands = [
        BotCommand("play", "ጨዋታውን ለመጀመር (Open App)"),
        BotCommand("balance", "ቀሪ ሂሳብ ለማየት"),
        BotCommand("deposit", "በ Telebirr ወይም CBE Birr ገንዘብ ገቢ ለማድረግ"),
        BotCommand("withdraw", "በ Telebirr ወይም CBE Birr ገንዘብ ለማውጣት"),
        BotCommand("history", "የሂሳብ ዝውውር ታሪክዎን ለማየት"),
        BotCommand("instructions", "የ ጨዋታው አጠቃቀም መመሪያዎችን ለማየት"),
        BotCommand("register", "በቦቱ ላይ መመዝገቢያዎን ለማረጋገጥ"),
        BotCommand("agent", "የኤጀንት ፕሮግራም መረጃዎችን ለማግኘት"),
        BotCommand("support", "የደንበኞች አገልግሎት (Support)")
    ]
    Try:
        Bot.set_my_commands(commands)
    Except Exception as e:
        Print(f"Error setting bot commands: {e}")

@bot.message_handler(commands=['start', 'menu'])
def start_cmd(message):
    Uid = int(message.from_user.id)
    First_name = message.from_user.first_name.replace('<', '&lt;').replace('>', '&gt;')
    Username = (message.from_user.username or "የለውም").replace('<', '&lt;').replace('>', '&gt;')

    Args = message.text.split()
    Referred_by = None
    If len(args) > 1 and args[1].startswith('ref_'):
        Try:
            Ref_id = int(args[1].split('_')[1])
            If ref_id != uid:
                Referred_by = ref_id
        Except ValueError:
            Pass

    With db_lock:
        If uid not in users_db:
            Users_db[uid] = {
                "id": uid,
                "name": first_name,
                "username": username,
                "balance": 0.0,
                "referred_by": referred_by,
                "referral_count": 0,
                "has_deposited": False,
                "milestone_rewarded": False,
                "history": []
            }
            If referred_by and referred_by in users_db:
                Users_db[referred_by]["referral_count"] = users_db[referred_by].get("referral_count", 0) + 1

        Bal = users_db[uid]['balance']

    Welcome_txt = (
        f"👋 ሰላም <b>{first_name}</b>!\n\n"
        f"ወደ <b>BKBINGO Pro</b> እንኳን ደህና መጡ! 🎲\n"
        f"💰 ባላንስዎ፦ <b>{bal:.2f} ETB</b>\n\n"
        "ለመጫወት ከታች ያለውን <b>'🎲 ጨዋታ ጀምር'</b> የሚለውን ይጫኑ。"
    )
    Bot.send_message(message.chat.id, welcome_txt, reply_markup=main_menu_keyboard(uid), parse_mode="HTML")

@bot.message_handler(commands=['play'])
def play_command(message):
    Uid = int(message.from_user.id)
    First_name = message.from_user.first_name.replace('<', '&lt;').replace('>', '&gt;')
    With db_lock:
        If uid not in users_db:
            Users_db[uid] = {"id": uid, "name": first_name, "balance": 0.0, "history": []}
        Bal = users_db[uid]['balance']

    Welcome_txt = (
        f"🎲 <b>BKBINGO Pro ጨዋታ</b>\n\n"
        f"ሰላም <b>{first_name}</b>፣ ለመጫወት ዝግጁ ኖት?\n"
        f"💰 ባላንስዎ፦ <b>{bal:.2f} ETB</b>\n\n"
        "ከታች ያለውን ቁልፍ በመጫን አፑንከፈቱ ይጫወቱ!"
    )
    Bot.send_message(message.chat.id, welcome_txt, reply_markup=main_menu_keyboard(uid), parse_mode="HTML")

@bot.message_handler(commands=['balance'])
def balance_command(message):
    Uid = int(message.from_user.id)
    With db_lock:
        If uid not in users_db:
            Users_db[uid] = {"id": uid, "name": message.from_user.first_name, "balance": 0.0, "history": []}
        Bal = users_db[uid]["balance"]
        Ref_count = users_db[uid].get("referral_count", 0)

    Msg = f"👤 <b>የተጫዋች ፕሮፋይል እና ባላንስ</b>\n\n🆔 ID: <code>{uid}</code>\n💰 ቀሪ ሂሳብ: <b>{bal:.2f} ETB</b>\n👥 የጋበዟቸው ሰዎች: <b>{ref_count}/{MILESTONE_REFERRAL_TARGET}</b>"
    Bot.send_message(message.chat.id, msg, reply_markup=main_menu_keyboard(uid), parse_mode="HTML")

@bot.message_handler(commands=['deposit'])
def deposit_command(message):
    Uid = int(message.from_user.id)
    Markup = InlineKeyboardMarkup(row_width=2)
    Markup.add(
        InlineKeyboardButton("CBE BIRR", callback_data="depmeth_cbe"),
        InlineKeyboardButton("TELE BIRR", callback_data="depmeth_tele")
    )
    Bot.send_message(
        message.chat.id,
        "💳 <b>የማንኛውን መንገድ ይምረጡ (Select Deposit Method)</b>\n\nእባክዎ ሂሳብ ለመሙላት የሚጠቀሙበትን መንገድ ይምረጡ፦",
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.message_handler(commands=['withdraw'])
def withdraw_command(message):
    Uid = int(message.from_user.id)
    With db_lock:
        If uid not in users_db:
            Users_db[uid] = {"id": uid, "balance": 0.0, "history": []}
        Bal = users_db[uid]["balance"]

    If bal < MIN_WITHDRAWAL:
        Bot.send_message(message.chat.id, f"❌ <b>ዝቅተኛው የዊዝድሮው መጠን {MIN_WITHDRAWAL:.2f} ETB ነው።</b>\nየእርስዎ ባላንስ፦ <b>{bal:.2f} ETB</b>", parse_mode="HTML")
        Return
    
    Markup = InlineKeyboardMarkup(row_width=2)
    Markup.add(
        InlineKeyboardButton("📱 Telebirr", callback_data="wdmeth_Telebirr"),
        InlineKeyboardButton("🏦 CBE Birr", callback_data="wdmeth_CBE")
    )
    Bot.send_message(message.chat.id, f"📤 <b>ገንዘብ ማውጫ ዘዴ ይምረጡ፦</b>\n💰 የሚገኝ ባላንስ፦ <b>{bal:.2f} ETB</b>", reply_markup=markup, parse_mode="HTML")

@bot.message_handler(commands=['history'])
def history_command(message):
    Uid = int(message.from_user.id)
    With db_lock:
        If uid not in users_db:
            Users_db[uid] = {"id": uid, "name": message.from_user.first_name, "balance": 0.0, "history": []}
        History_list = users_db[uid].get("history", [])

    If not history_list:
        Hist_msg = "📜 <b>የታሪክ መዝገብ</b>\n\nእስካሁን የተመዘገበ ምንም አይነት የጨዋታ፣ ዲፖዚት ወይም ዊዝድሮ ታሪክ የለዎትም አሁን ይጀምሩ! 🎲"
    else:
        Hist_msg = "📜 <b>የእርስዎ የቅርብ ጊዜ ታሪኮች (Activity History)</b>\n━━━━━━━━━━━━━━━━━━━\n"
        For item in history_list[:10]:
            Hist_msg += f"⏱ <code>{item['time']}</code>\n📌 <b>{item['type']}</b>: {item['details']}\n\n"

    Markup = InlineKeyboardMarkup()
    Markup.add(InlineKeyboardButton("🔙 ወደ ዋናው ምናሌ ተመለስ", callback_data="btn_main_menu"))
    Bot.send_message(message.chat.id, hist_msg, parse_mode="HTML", reply_markup=markup)

@bot.message_handler(commands=['instructions'])
def instructions_command(message):
    Instruction_text = (
        "📖 <b>የ BKBINGO አጠቃቀም መመሪያ (Instructions):</b>\n\n"
        "1. <code>/play</code> በመጫወት ጨዋታውን ይጀምሩ።\n"
        "2. ሂሳብ ለመሙላት <code>/deposit</code> ይጠቀሙ።\n"
        "3. ያሸነፉትን ገንዘብ ለማውጣት <code>/withdraw</code> ይጠቀሙ።\n"
        "4. ለተጨማሪ እርዳታ ኤጀንቶቻችንን ያነጋግሩ።"
    )
    Bot.send_message(message.chat.id, instruction_text, parse_mode="HTML")

@bot.message_handler(commands=['register'])
def register_command(message):
    Uid = int(message.from_user.id)
    First_name = message.from_user.first_name.replace('<', '&lt;').replace('>', '&gt;')
    With db_lock:
        If uid not in users_db:
            Users_db[uid] = {
                "id": uid,
                "name": first_name,
                "username": message.from_user.username or "የለውም",
                "balance": 0.0,
                "history": []
            }
    Register_text = (
        "✅ <b>ምዝገባ (Registration):</b>\n\n"
        f"እንኳን ደህና መጡ <b>{first_name}</b>! አካውንትዎ በተሳካ ሁኔታ ተመዝግቧል። አሁን በነፃነት መጫወት ይችላሉ!"
    )
    Bot.send_message(message.chat.id, register_text, parse_mode="HTML")

@bot.message_handler(commands=['agent'])
def agent_command(message):
    Agent_text = (
        "🤝 <b>የኤጀንት ፕሮግራሞች (Agent):</b>\n\n"
        "ሰዎችን በመጋበዝ ኮሚሽን መሰብሰብ ይፈልጋሉ? ኤጀንት ለመሆን የሚከተለውን አስተዳዳሪ ያነጋግሩ: @AdminUsername"
    )
    Bot.send_message(message.chat.id, agent_text, parse_mode="HTML")

@bot.message_handler(commands=['support'])
def support_command(message):
    Uid = int(message.from_user.id)
    With db_lock:
        User_bal = users_db.get(uid, {}).get("balance", 0.0)
    Support_deep_link = f"https://t.me/BkbingosupportBot?start=USER_{uid}_BAL_{int(user_bal)}"
    
    Markup = InlineKeyboardMarkup()
    Markup.add(InlineKeyboardButton(text="🎧 የደንበኞች አገልግሎት ቡድን ማነጋገር", url=support_deep_link))
    
    Bot.send_message(
        message.chat.id,
        "🎧 <b>የደንበኞች አገልግሎት (Support)</b>\n\nማንኛውም ጥያቄ ወይም የክፍያ ማስተካከያ ካለዎት ከታች ባለው ሊንክ በቀጥታ ማነጋገር ይችላሉ።",
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.message_handler(commands=['stats'])
def admin_statistics(message):
    Uid = int(message.from_user.id)
    If uid != ADMIN_ID:
        Bot.send_message(message.chat.id, "❌ ይህ ትዕዛዝ ለአድሚን ብቻ የተፈቀደ ነው።")
        Return

    With db_lock:
        Total_users = len(users_db)
        Total_deposit_amount = 0.0
        Total_withdraw_amount = 0.0

        For user_data in users_db.values():
            For hist in user_data.get("history", []):
                If "ዲፖዚት" in hist["type"]:
                    Nums = re.findall(r'\+?(\d+(?:\.\d+)?)', hist["details"])
                    If nums:
                        Total_deposit_amount += float(nums[0])
                elif "ዊዝድሮ" in hist["type"] and "ውድቅ" not in hist["type"]:
                    Nums = re.findall(r'-?(\d+(?:\.\d+)?)', hist["details"])
                    If nums:
                        Total_withdraw_amount += float(nums[0])

    Stats_msg = (
        f"📊 <b>የ BKBINGO Pro አድሚን ስታስቲክስ (Statistics)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👥 አጠቃላይ የተጠቃሚዎች ቁጥር: <b>{total_users}</b>\n"
        f"📥 አጠቃላይ የገባ ገንዘብ (Total Deposit): <b>{total_deposit_amount:.2f} ETB</b>\n"
        f"📤 አጠቃላይ የወጣ ገንዘብ (Total Withdrawal): <b>{total_withdraw_amount:.2f} ETB</b>\n"
        f"💰 የተጣራ ልዩነት (Net Flow): <b>{(total_deposit_amount - total_withdraw_amount):.2f} ETB</b>"
    )
    Bot.send_message(message.chat.id, stats_msg, parse_mode="HTML")

@bot.message_handler(commands=['broadcast'])
def broadcast_command(message):
    Uid = int(message.from_user.id)
    If uid != ADMIN_ID:
        Bot.send_message(message.chat.id, "❌ ይህ ትዕዛዝ ለአድሚን ብቻ የተፈቀደ ነው።")
        Return
    
    Broadcast_state[ADMIN_ID] = True
    Bot.send_message(
        message.chat.id, 
        "📢 <b>የብሮድካስት ሁነታ (Broadcast Mode) ተከፍቷል!</b>\n\nለተጠቃሚዎች ማስተላለፍ የሚፈልጉትን <b>ጽሁፍ፣ ፎቶ፣ ቪዲዮ ወይም ዶክመንት</b> አሁን ይላኩ።", 
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda m: int(m.from_user.id) == ADMIN_ID and broadcast_state.get(ADMIN_ID) == True, content_types=['text', 'photo', 'video', 'document'])
def send_broadcast_to_users(message):
    Broadcast_state[ADMIN_ID] = False
    With db_lock:
        All_user_ids = list(users_db.keys())

    Success_count = 0
    Fail_count = 0

    Bot.send_message(message.chat.id, f"⏳ መልእክቱ ለ <b>{len(all_user_ids)}</b> ተጠቃሚዎች በመላክ ላይ ይገኛል...", parse_mode="HTML")

    For uid in all_user_ids:
        Try:
            If message.photo:
                Bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.video:
                Bot.send_video(uid, message.video.file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.document:
                Bot.send_document(uid, message.document.file_id, caption=message.caption or "", parse_mode="HTML")
            elif message.text:
                Bot.send_message(uid, message.text, parse_mode="HTML")
            Success_count += 1
            Time.sleep(0.05)
        Except Exception:
            Fail_count += 1

    Bot.send_message(
        message.chat.id, 
        f"✅ <b>ብሮድካስቱ በተሳካ ሁኔታ ተጠናቋል!</b>\n\n📤 የደረሳቸው: <b>{success_count}</b>\n❌ ያልደረሳቸው: <b>{fail_count}</b>", 
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('btn_'))
def handle_main_menu_callbacks(call):
    Uid = int(call.from_user.id)
    Action = call.data
    Bot.answer_callback_query(call.id)

    Safe_name = call.from_user.first_name.replace('<', '&lt;').replace('>', '&gt;')
    
    With db_lock:
        If uid not in users_db:
            Users_db[uid] = {"id": uid, "name": safe_name, "username": call.from_user.username or "የለውም", "balance": 0.0, "referral_count": 0, "history": []}
        Bal = users_db[uid]["balance"]
        Ref_count = users_db[uid].get("referral_count", 0)

    If action == "btn_profile":
        Msg = f"👤 <b>የተጫዋች ፕሮፋይል</b>\n🆔 ID: <code>{uid}</code>\n💰 ባላንስ: <b>{bal:.2f} ETB</b>\n👥 የጋበዟቸው ሰዎች: <b>{ref_count}/{MILESTONE_REFERRAL_TARGET}</b>"
        Bot.send_message(call.message.chat.id, msg, reply_markup=main_menu_keyboard(uid), parse_mode="HTML")

    elif action == "btn_deposit":
        Markup = InlineKeyboardMarkup(row_width=2)
        Markup.add(
            InlineKeyboardButton("CBE BIRR", callback_data="depmeth_cbe"),
            InlineKeyboardButton("TELE BIRR", callback_data="depmeth_tele")
        )
        Bot.send_message(
            call.message.chat.id,
            "💳 <b>የማንኛውን መንገድ ይምረጡ (Select Deposit Method)</b>\n\nእባክዎ ሂሳብ ለመሙላት የሚጠቀሙበትን መንገድ ይምረጡ፦",
            reply_markup=markup,
            parse_mode="HTML"
        )

    elif action == "btn_withdraw":
        If bal < MIN_WITHDRAWAL:
            Bot.send_message(call.message.chat.id, f"❌ <b>ዝቅተኛው የዊዝድሮው መጠን {MIN_WITHDRAWAL:.2f} ETB ነው።</b>\nየእርስዎ ባላንስ፦ <b>{bal:.2f} ETB</b>", parse_mode="HTML")
            Return
        
        Markup = InlineKeyboardMarkup(row_width=2)
        Markup.add(
            InlineKeyboardButton("📱 Telebirr", callback_data="wdmeth_Telebirr"),
            InlineKeyboardButton("🏦 CBE Birr", callback_data="wdmeth_CBE")
        )
        Bot.send_message(call.message.chat.id, f"📤 <b>ገንዘብ ማውጫ ዘዴ ይምረጡ፦</b>\n💰 የሚገኝ ባላንስ፦ <b>{bal:.2f} ETB</b>", reply_markup=markup, parse_mode="HTML")

    elif action == "btn_referral":
        Bot_username = bot.get_me().username
        Ref_link = f"https://t.me/{bot_username}?start=ref_{uid}"
        Ref_msg = (
            f"👥 <b>የሪፈራል ፕሮግራም (Referral System)</b>\n\n"
            f"ጓደኞችዎን ወደ ቦቱ በመጋበዝ ትልቅ ሽልማት ያግኙ! 🎁\n"
            f"እስከ <b>{MILESTONE_REFERRAL_TARGET}</b> ሰዎችን ሲጋብዙ በራስ ሰር የ<b>{MILESTONE_BONUS:.2f} ETB</b> ልዩ ቦነስ ይሸለማሉ!\n\n"
            f"🔗 <b>የእርስዎ ልዩ የሪፈራል ሊንክ፦</b>\n<code>{ref_link}</code>\n\n"
            f"📊 የጋበዟቸው ሰዎች ብዛት፦ <b>{ref_count} / {MILESTONE_REFERRAL_TARGET}</b>"
        )
        Bot.send_message(call.message.chat.id, ref_msg, reply_markup=main_menu_keyboard(uid), parse_mode="HTML")

    elif action == "btn_history":
        With db_lock:
            History_list = users_db.get(uid, {}).get("history", [])

        If not history_list:
            Hist_msg = "📜 <b>የታሪክ መዝገብ</b>\n\nእስካሁን የተመዘገበ ምንም አይነት የጨዋታ፣ ዲፖዚት ወይም ዊዝድሮ ታሪክ የለዎትም አሁን ይጀምሩ! 🎲"
        else:
            Hist_msg = "📜 <b>የእርስዎ የቅርብ ጊዜ ታሪኮች (Activity History)</b>\n━━━━━━━━━━━━━━━━━━━\n"
            For item in history_list[:10]:
                Hist_msg += f"⏱ <code>{item['time']}</code>\n📌 <b>{item['type']}</b>: {item['details']}\n\n"

        Markup = InlineKeyboardMarkup()
        Markup.add(InlineKeyboardButton("🔙 ወደ ዋናው ምናሌ ተመለስ", callback_data="btn_main_menu"))
        Bot.edit_message_text(hist_msg, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)

    elif action == "btn_main_menu":
        Welcome_txt = (
            f"👋 ሰላም <b>{call.from_user.first_name}</b>!\n\n"
            f"ወደ <b>BKBINGO Pro</b> እንኳን ደህና መጡ! 🎲\n"
            f"💰 ባላንስዎ፦ <b>{bal:.2f} ETB</b>\n\n"
            "ለመጫወት ከታች ያለውን <b>'🎲 ጨዋታ ጀምር'</b> የሚለውን ይጫኑ。"
        )
        Bot.edit_message_text(welcome_txt, call.message.chat.id, call.message.message_id, reply_markup=main_menu_keyboard(uid), parse_mode="HTML")

    elif action == "btn_help":
        Bot.send_message(call.message.chat.id, "ℹ️ <b>የ BKBINGO Pro ህጎች</b>\n1. የካርቴላ ዋጋ 10 ETB ነው።\n2. በአንድ ዙር ቢበዛ 2 ካርቴላ መግዛት ይቻላል።\n3. አሸናፊው ደራሹን በሙሉ ይወስዳል።", parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith('depmeth_'))
def handle_deposit_method_selection(call):
    Uid = int(call.from_user.id)
    Method = call.data.split('_')[1]
    Bot.answer_callback_query(call.id)

    If method == "cbe":
        Deposit_data[uid] = {"method": "CBE-Birr", "account": CBE_ACCOUNT, "name": CBE_NAME}
        Method_title = "የ CBE-Birr አካውንት"
        Merchant_info = f"CBE-BIRR Merchant - {CBE_ACCOUNT}\n({CBE_NAME})"
    else:
        Deposit_data[uid] = {"method": "Telebirr", "account": TELEBIRR_ACCOUNT, "name": TELEBIRR_NAME}
        Method_title = "የ Telebirr አካውንት"
        Merchant_info = f"TELEBIRR Account - {TELEBIRR_ACCOUNT}\n({TELEBIRR_NAME})"

    User_states[uid] = "WAITING_SMS_RECEIPT"

    Instructions = (
        f"የ <b>{method_title}</b> አካውንት\n\n"
        f"<b>{merchant_info}</b>\n\n"
        "<b>መመሪያ</b>\n"
        f"1. ከላይ ባለው የ {method_title} Pay for Merchant በሚለው ገንዘቡን ያስገቡ\n"
        "2. ብሩን ስትልክ የክፍያዎን መረጃ የያዘ አጭር የሩፍ መልክት(sms) ከ ባንኩ/ቴሌብር ይደርሶታል\n"
        "3. የደርሰሶትን አጭር የሩፍ መልክት(sms) ሙሉውን ኮፒ(copy) በማድረግ ከታች ባለው የቴሌግራም የሩፍ መዢኛው ላይ ፔስት(paste) በማድረግ ይላኩት\n\n"
        f"የሚያጋጥሞት የክፍያ ችግር ካለ @BkbingosupportBot በዚህ ታችን ማውራት ይችላሉ"
    )
    Bot.send_message(call.message.chat.id, instructions, parse_mode="HTML")

@bot.message_handler(func=lambda m: user_states.get(int(m.from_user.id)) == "WAITING_SMS_RECEIPT")
def handle_sms_receipt_verification(message):
    Uid = int(message.from_user.id)
    Text = message.text.strip()

    If len(text) < 15:
        Bot.send_message(message.chat.id, "❌ <b>የላኩት የደረሰኝ ጽሁፍ በጣም አጭር ነው። እባክዎን ትክክለኛውን የባንክ/ቴሌብር አጭር መልእክት (SMS) ሙሉውን ኮፒ አድርገው ይላኩ።</b>", parse_mode="HTML")
        Return

    Txn_id_match = re.search(r'(?:Txn|ID|Ref|TRX)[^\w]?([A-Za-z0-9]{8,})', text, re.IGNORECASE)
    Txn_id = txn_id_match.group(1) if txn_id_match else hashlib.md5(text.encode()).hexdigest()[:12]

    If txn_id in used_txn_ids:
        Bot.send_message(message.chat.id, "❌ <b>ይህ የክፍያ ደረሰኝ አስቀድሞ ጥቅም ላይ ውሏል!</b>", parse_mode="HTML")
        Return

    Amounts = re.findall(r'(\d+(?:\.\d+)?)\s*(?:ETB|ብር|Birr)', text, re.IGNORECASE)
    If not amounts:
        Amounts = re.findall(r'(?:Transferred|Sent|Paid|Received|Amount)[^\d]*(\d+(?:\.\d+)?)', text, re.IGNORECASE)

    If not amounts:
        Numbers = [float(n) for n in re.findall(r'\b\d+(?:\.\d+)?\b', text) if float(n) >= 5.0]
        If numbers:
            Deposit_amount = numbers[0] 
        else:
            Bot.send_message(message.chat.id, "❌ <b>ከደረሰኙ ላይ የክፍያ መጠን ማግኘት አልተቻለም። እባክዎን ትክክለኛውን የSMS መልእክት ኮፒ አድርገው ይላኩ።</b>", parse_mode="HTML")
            Return
    else:
        Deposit_amount = float(amounts[0])

    If deposit_amount < 5.0:
        Bot.send_message(message.chat.id, "❌ <b>የተገኘው የብር መጠን በጣም አነስተኛ ነው። እባክዎን ትክክለኛ ደረሰኝ ይላኩ።</b>", parse_mode="HTML")
        Return

    User_states[uid] = None
    Req_id = str(uuid.uuid4())[:8]
    Pending_deposits[req_id] = {
        "user_id": uid,
        "amount": deposit_amount,
        "txn_id": txn_id,
        "text": text
    }

    Bot.send_message(
        message.chat.id,
        f"⏳ <b>የክፍያ ጥያቄዎ ተቀብሏል!</b>\n\n💰 መጠን: <b>{deposit_amount:.2f} ETB</b>\n🔍 <i>አድሚኑ ደረሰኙን አጣርቶ በቅርቡ አካውንትዎ ላይ ይጨምረዋል።</i>",
        parse_mode="HTML"
    )

    Admin_markup = InlineKeyboardMarkup(row_width=2)
    Admin_markup.add(
        InlineKeyboardButton("✅ አረጋግጥ (Approve)", callback_data=f"adm_app_{req_id}"),
        InlineKeyboardButton("❌ ውድቅ አድርግ (Reject)", callback_data=f"adm_rej_{req_id}")
    )

    Admin_alert = (
        f"🔔 <b>አዲስ የዲፖዚት ማረጋገጫ (Verification Request)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 ተጫዋች ID: <code>{uid}</code>\n"
        f"💰 መጠን: <b>{deposit_amount:.2f} ETB</b>\n"
        f"🆔 Txn ID: <code>{txn_id}</code>\n"
        f"📄 SMS: <i>{text[:150]}...</i>"
    )
    Try:
        Bot.send_message(ADMIN_ID, admin_alert, reply_markup=admin_markup, parse_mode="HTML")
    Except Exception:
        Pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('adm_app_') or call.data.startswith('adm_rej_'))
def handle_admin_verification_action(call):
    If int(call.from_user.id) != ADMIN_ID:
        Bot.answer_callback_query(call.id, "ይህ ትዕዛዝ ለአድሚን ብቻ የተፈቀደ ነው!", show_alert=True)
        Return

    Action, req_id = call.data.split('_')[1], call.data.split('_')[2]
    Bot.answer_callback_query(call.id)

    If req_id not in pending_deposits:
        Bot.edit_message_text("⚠️ ይህ ጥያቄ አስቀድሞ ተስተናግዷል ወይም አልፏል።", call.message.chat.id, call.message.message_id)
        Return

    Dep_info = pending_deposits.pop(req_id)
    Uid = dep_info["user_id"]
    Amount = dep_info["amount"]
    Txn_id = dep_info["txn_id"]

    If action == "app":
        With db_lock:
            Used_txn_ids.add(txn_id)
            If uid not in users_db:
                Users_db[uid] = {"id": uid, "name": f"User {uid}", "balance": 0.0, "has_deposited": False, "history": []}
            
            Users_db[uid]["balance"] += amount
            New_bal = users_db[uid]["balance"]
            Users_db[uid]["has_deposited"] = True
            
            Referrer_id = users_db[uid].get("referred_by")
            If referrer_id and referrer_id in users_db:
                Ref_user = users_db[referrer_id]
                Ref_count = ref_user.get("referral_count", 0)
                
                If ref_count >= MILESTONE_REFERRAL_TARGET and not ref_user.get("milestone_rewarded", False):
                    Ref_user["milestone_rewarded"] = True
                    Ref_user["balance"] += MILESTONE_BONUS
                    Ref_new_bal = ref_user["balance"]
                    
                    Socketio.emit('balance_update', {'user_id': referrer_id, 'balance': ref_new_bal})
                    Add_user_history(referrer_id, "ሪፈራል ቦነስ (Referral Milestone)", f"+{MILESTONE_BONUS:.2f} ETB ተሸልመዋል")
                    Try:
                        Bot.send_message(
                            referrer_id,
                            f"🎉 <b>ልዩ የሪፈራል ሽልማት አሸንፈዋል!</b>\n\nእስከ <b>{MILESTONE_REFERRAL_TARGET}</b> ሰዎችን በመጋበዝዎ ምክንያት የሲስተሙ የ<b>{MILESTONE_BONUS:.2f} ETB</b> ልዩ ቦነስ ወደ ባላንስዎ ገብቷል!\n💳 አዲሱ ባላንስዎ፦ <b>{ref_new_bal:.2f} ETB</b>",
                            parse_mode="HTML"
                        )
                    Except Exception:
                        Pass

        Socketio.emit('balance_update', {'user_id': uid, 'balance': new_bal})
        Add_user_history(uid, "ዲፖዚት (Deposit)", f"+{amount:.2f} ETB በአድሚን ጸድቋል")

        Try:
            Bot.send_message(
                uid,
                f"🎉 <b>ዲፖዚትዎ በአድሚን ጸድቋል!</b>\n\n💰 የተጨመረ: <b>+{amount:.2f} ETB</b>\n💳 አዲሱ ባላንስዎ: <b>{new_bal:.2f} ETB</b>",
                parse_mode="HTML"
            )
        Except Exception:
            Pass

        Bot.edit_message_text(
            f"✅ <b>ዲፖዚቱ ጸድቆ ለተጫዋች (<code>{uid}</code>) ተጭኗል!</b>\n💰 መጠን: {amount:.2f} ETB",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML"
        )
    else:
        Try:
            Bot.send_message(
                uid,
                f"❌ <b>የዲፖዚት ጥያቄዎ ውድቅ ተደርጓል (Rejected)።</b>\nእባክዎን ትክክለኛ የክፍያ ደረሰኝ መላክዎን ያረጋግጡ።",
                parse_mode="HTML"
            )
        Except Exception:
            Pass

        Bot.edit_message_text(
            f"❌ <b>ዲፖዚቱ ውድቅ ተደርጓል (Rejected) ለተጫዋች (<code>{uid}</code>)።</b>",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML"
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith('wdmeth_'))
def handle_withdraw_method(call):
    Uid = int(call.from_user.id)
    Bank_code = call.data.split('_')[1]
    
    With db_lock:
        Bal = users_db.get(uid, {}).get("balance", 0.0)

    If bal < MIN_WITHDRAWAL:
        Bot.answer_callback_query(call.id, f"ዝቅተኛው የዊዝድሮው መጠን {MIN_WITHDRAWAL} ETB ነው!", show_alert=True)
        Return

    Method_name = "Telebirr" if bank_code == "Telebirr" else "CBE Birr"
    Withdraw_data[uid] = {'bank_code': bank_code, 'method_name': method_name}
    User_states[uid] = "WAITING_WITHDRAW_ACC"
    
    Bot.edit_message_text(
        f"✅ የተመረጠው ማውጫ፦ <b>{method_name}</b>\n\n📱 እባክዎን ገንዘቡ የሚላክበትን ትክክለኛ <b>የ{method_name} ስልክ ቁጥር ወይም የባንክ ሂሳብ ቁጥር</b> ብቻ ያስገቡ፦", 
        call.message.chat.id, 
        call.message.message_id, 
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda m: user_states.get(int(m.from_user.id)) == "WAITING_WITHDRAW_ACC")
def handle_withdraw_account(message):
    Uid = int(message.from_user.id)
    Account_num = message.text.strip()
    
    If uid not in withdraw_data:
        User_states[uid] = None
        Return

    If not account_num.isdigit() or not (4 <= len(account_num) <= 20):
        Bot.send_message(message.chat.id, "❌ <b>ስህተት፦ እባክዎን ትክክለኛ የባንክ አካውንት ቁጥር ወይም የስልክ ቁጥር ብቻ ያስገቡ።</b>", parse_mode="HTML")
        Return

    Withdraw_data[uid]['account'] = account_num
    User_states[uid] = "WAITING_WITHDRAW_AMT"
    
    With db_lock:
        Bal = users_db.get(uid, {}).get("balance", 0.0)

    Bot.send_message(
        message.chat.id, 
        f"👍 የተቀበልነው ቁጥር፦ <code>{account_num}</code>\n\n💰 ማውጣት የሚፈልጉትን <b>የገንዘብ መጠን (ETB)</b> ያስገቡ፦\n(የሚገኝ ባላንስ፦ <b>{bal:.2f} ETB</b>)", 
        parse_mode="HTML"
    )

@bot.message_handler(func=lambda m: user_states.get(int(m.from_user.id)) == "WAITING_WITHDRAW_AMT")
def handle_withdraw_amount(message):
    Uid = int(message.from_user.id)
    
    Try:
        Amount = float(message.text.strip())
    Except ValueError:
        Bot.send_message(message.chat.id, "❌ <b>እባክዎን ትክክለኛ የቁጥር መጠን ያስገቡ!</b>", parse_mode="HTML")
        Return

    With db_lock:
        Bal = users_db.get(uid, {}).get("balance", 0.0)

        If amount < MIN_WITHDRAWAL:
            Bot.send_message(message.chat.id, f"❌ <b>ዝቅተኛው ማውጣት የሚችሉት መጠን {MIN_WITHDRAWAL:.2f} ETB ነው።</b>", parse_mode="HTML")
            Return

        If amount > bal:
            Bot.send_message(message.chat.id, f"❌ <b>በቂ ባላንስ የለዎትም።</b>\nየእርስዎ ባላንስ፦ <b>{bal:.2f} ETB</b>", parse_mode="HTML")
            Return

        Account = withdraw_data[uid]['account']
        Method_name = withdraw_data[uid]['method_name']
        User_states[uid] = None

        Users_db[uid]["balance"] -= amount
        Current_bal = users_db[uid]["balance"]

    Socketio.emit('balance_update', {'user_id': uid, 'balance': current_bal})
    Add_user_history(uid, "ዊዝድሮ (Withdraw)", f"-{amount:.2f} ETB ወደ {method_name} ({account}) ተጠይቋል")

    Success_msg = (
        f"📤 <b>የገንዘብ ማውጣት (Withdrawal) ጥያቄዎ ተቀባይነት አግኝቷል!</b>\n\n"
        f"💰 መጠን፦ <b>{amount:.2f} ETB</b>\n🏦 ዘዴ፦ <b>{method_name}</b>\n📱 ሂሳብ ቁጥር፦ <code>{account}</code>\n💳 የቀረ ባላንስ፦ <b>{current_bal:.2f} ETB</b>"
    )
    Bot.send_message(message.chat.id, success_msg, parse_mode="HTML")

    Wd_req_id = str(uuid.uuid4())[:8]
    Pending_withdrawals[wd_req_id] = {
        "user_id": uid,
        "amount": amount,
        "account": account,
        "method_name": method_name
    }

    Admin_markup = InlineKeyboardMarkup(row_width=2)
    Admin_markup.add(
        InlineKeyboardButton("✅ ዊዝድሮ አረጋግጥ (Approve)", callback_data=f"wd_app_{wd_req_id}"),
        InlineKeyboardButton("❌ ውድቅ አድርግ (Reject & Refund)", callback_data=f"wd_rej_{wd_req_id}")
    )

    Admin_info = (
        f"🔔 <b>አዲስ የገንዘብ ማውጣት (Withdraw) ጥያቄ!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 ተጫዋች ID: <code>{uid}</code>\n"
        f"💰 መጠን: <b>{amount:.2f} ETB</b>\n"
        f"📱 ሂሳብ ቁጥር: <code>{account}</code> ({method_name})"
    )
    Try:
        Bot.send_message(ADMIN_ID, admin_info, reply_markup=admin_markup, parse_mode="HTML")
    Except Exception:
        Pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('wd_app_') or call.data.startswith('wd_rej_'))
def handle_admin_withdraw_action(call):
    If int(call.from_user.id) != ADMIN_ID:
        Bot.answer_callback_query(call.id, "ይህ ትዕዛዝ ለአድሚን ብቻ የተፈቀደ ነው!", show_alert=True)
        Return

    Action, wd_req_id = call.data.split('_')[1], call.data.split('_')[2]
    Bot.answer_callback_query(call.id)

    If wd_req_id not in pending_withdrawals:
        Bot.edit_message_text("⚠️ ይህ የዊዝድሮ ጥያቄ አስቀድሞ ተስተናግዷል ወይም አልፏል።", call.message.chat.id, call.message.message_id)
        Return

    Wd_info = pending_withdrawals.pop(wd_req_id)
    Uid = wd_info["user_id"]
    Amount = wd_info["amount"]
    Account = wd_info["account"]
    Method_name = wd_info["method_name"]

    If action == "app":
        Try:
            Bot.send_message(
                uid,
                f"✅ <b>የገንዘብ ማውጣት (Withdrawal) ጥያቄዎ ተፈፅሟል!</b>\n\n💰 መጠን፦ <b>{amount:.2f} ETB</b> ተልኳል።\n🏦 ሂሳብ ቁጥር፦ <code>{account}</code> ({method_name})",
                parse_mode="HTML"
            )
        Except Exception:
            Pass

        Bot.edit_message_text(
            f"✅ <b>ዊዝድሮው ጸድቆ ተልኳል!</b>\n👤 ተጫዋች: <code>{uid}</code>\n💰 መጠን: {amount:.2f} ETB",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML"
        )
    else:
        With db_lock:
            If uid not in users_db:
                Users_db[uid] = {"id": uid, "name": f"User {uid}", "balance": 0.0, "history": []}
            Users_db[uid]["balance"] += amount
            Refunded_bal = users_db[uid]["balance"]

        Socketio.emit('balance_update', {'user_id': uid, 'balance': refunded_bal})
        Add_user_history(uid, "ዊዝድሮ ውድቅ (Withdraw Rejected)", f"{amount:.2f} ETB ተመላሽ (Refund) ሆኗል")

        Try:
            Bot.send_message(
                uid,
                f"❌ <b>የገንዘብ ማውጣት (Withdrawal) ጥያቄዎ ውድቅ ተደርጓል።</b>\n\n💰 የተወገደው <b>{amount:.2f} ETB</b> ወደ ባላንስዎ ተመልሷል (Refunded)።\n💳 አዲሱ ባላንስዎ፦ <b>{refunded_bal:.2f} ETB</b>",
                parse_mode="HTML"
            )
        Except Exception:
            Pass

        Bot.edit_message_text(
            f"❌ <b>ዊዝድሮው ውድቅ ተደርጎ ገንዘቡ ተመልሷል (Refunded)!</b>\n👤 ተጫዋች: <code>{uid}</code>\n💰 መጠን: {amount:.2f} ETB",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML"
        )

@support_bot.message_handler(commands=['start'])
def start_support_bot(message):
    Text = message.text
    User_info = ""
    Safe_name = message.from_user.first_name.replace('<', '&lt;').replace('>', '&gt;')
    
    If "USER_" in text and "_BAL_" in text:
        Try:
            Parts = text.split("USER_")[1].split("_BAL_")
            U_id = parts[0]
            Bal = parts[1]
            User_info = f"\n\n👤 <b>የተጫዋች መረጃ፦</b>\n🆔 ID: <code>{u_id}</code>\n💰 ባላንስ: <b>{bal} ETB</b>"
        Except Exception:
            Pass

    Welcome_msg = (
        f'<a href="{OPERATOR_IMAGE_URL}">&#8203;</a>'
        f"👋 ሰላም <b>{safe_name}</b>!\n\n"
        f"ወደ <b>BKBINGO Pro</b> የደንበኞች አገልግሎት እንኳን ደህና መጡ! 🎧{user_info}\n\n"
        f"ያጋጠመዎትን ችግር ወይም ጥያቄ በአንድ መልእክት ጽፈው ይላኩልን。"
    )
    Support_bot.send_message(message.chat.id, welcome_msg, parse_mode="HTML")

@support_bot.message_handler(func=lambda m: int(m.from_user.id) != ADMIN_ID, content_types=['text', 'photo'])
def handle_support_inquiry(message):
    Uid = int(message.from_user.id)
    Safe_name = message.from_user.first_name.replace('<', '&lt;').replace('>', '&gt;')
    Safe_msg = message.text.replace('<', '&lt;').replace('>', '&gt;') if message.text else 'Photo Sent'
    
    Markup = InlineKeyboardMarkup()
    Markup.add(InlineKeyboardButton("✍️ መልስ ስጥ (Reply)", callback_data=f"suppreply_{uid}"))

    Admin_msg = (
        f"📩 <b>አዲስ የደንበኞች ጥያቄ!</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 ከ: {safe_name} (<code>{uid}</code>)\n"
        f"💬 መልእክት፦ {safe_msg}"
    )

    If message.photo:
        Support_bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=admin_msg, reply_markup=markup, parse_mode="HTML")
    else:
        Support_bot.send_message(ADMIN_ID, admin_msg, reply_markup=markup, parse_mode="HTML")

    Confirm_msg = (
        f'<a href="{OPERATOR_IMAGE_URL}">&#8203;</a>'
        "✅ <b>መልእክትዎ ለደንበኞች አገልግሎት ደርሷል!</b>"
    )
    Support_bot.send_message(message.chat.id, confirm_msg, parse_mode="HTML")

@support_bot.callback_query_handler(func=lambda call: call.data.startswith('suppreply_'))
def prepare_support_reply(call):
    Target_uid = int(call.data.split('_')[1])
    Admin_reply_state[ADMIN_ID] = target_uid
    Support_bot.answer_callback_query(call.id)
    Support_bot.send_message(ADMIN_ID, f"✍️ ለ ተጫዋች <code>{target_uid}</code> የሚላከውን መልስ አሁን ይጻፉ፦", parse_mode="HTML")

@support_bot.message_handler(func=lambda m: int(m.from_user.id) == ADMIN_ID and ADMIN_ID in admin_reply_state)
def send_support_reply(message):
    Target_uid = admin_reply_state.pop(ADMIN_ID, None)
    If target_uid:
        Safe_text = message.text.replace('<', '&lt;').replace('>', '&gt;')
        Reply_msg = (
            f'<a href="{OPERATOR_IMAGE_URL}">&#8203;</a>'
            f"🎧 <b>ከደንበኞች አገልግሎት የተሰጠ መልስ፦</b>\n━━━━━━━━━━━━━━━\n{safe_text}"
        )
        Try:
            Support_bot.send_message(target_uid, reply_msg, parse_mode="HTML")
            Support_bot.send_message(ADMIN_ID, f"✅ መልሱ ለተጫዋች <code>{target_uid}</code> በተሳካ ሁኔታ ተልቋል!", parse_mode="HTML")
        Except Exception as ex:
            Support_bot.send_message(ADMIN_ID, f"❌ መልእክቱን መላክ አልተቻለም፦ {ex}", parse_mode="HTML")

@socketio.on('get_user_balance')
def handle_get_balance(data):
    If not data or 'user_id' not in data:
        Return
    Uid = int(data.get('user_id'))
    With db_lock:
        If uid not in users_db:
            Users_db[uid] = {"id": uid, "name": f"User {uid}", "balance": 0.0, "history": []}
        Bal = users_db[uid]["balance"]
    Emit('balance_update', {'user_id': uid, 'balance': bal})

@socketio.on('select_card')
def handle_card_selection(data):
    If game_state["status"] == "PLAYING":
        Emit('error_msg', {'msg': 'ጨዋታው ተጀምሯል። እባክዎን አዲሱን ዙር ይጠብጉ!'})
        Return

    Uid = int(data.get('user_id'))
    Card_id = int(data.get('card_id'))

    With db_lock:
        If uid not in users_db:
            Users_db[uid] = {"id": uid, "name": f"User {uid}", "balance": 0.0, "history": []}

        Bal = users_db[uid]["balance"]
        
        If card_id in game_state['selected_cards'].values():
            Emit('error_msg', {'msg': 'ይህ ካርቴላ አስቀድሞ በሌላ ተጫዋች ተይዟል!'})
            Return

        User_cards = game_state['player_cards'].get(uid, [])
        If len(user_cards) >= MAX_CARDS_PER_PLAYER:
            Emit('error_msg', {'msg': f'በአንድ ዙር ቢበዛ {MAX_CARDS_PER_PLAYER} ካርቴላ ብቻ መግዛት ይቻላል!'})
            Return

        If bal < CARD_PRICE:
            Emit('error_msg', {'msg': 'በቂ ባላንስ የሎትም። እባክዎን አስቀድመው ዲፖዚት ያድርጉ።'})
            Return

        Users_db[uid]["balance"] -= CARD_PRICE
        New_bal = users_db[uid]["balance"]
        
        Game_state['selected_cards'][f"{uid}_{card_id}"] = card_id
        If uid not in game_state['player_cards']:
            Game_state['player_cards'][uid] = []
        Game_state['player_cards'][uid].append(card_id)

    Matrix = cards_database.get(card_id)
    Emit('card_confirmed', {'card_id': card_id, 'matrix': matrix, 'new_balance': new_bal}, broadcast=False)
    Emit('balance_update', {'user_id': uid, 'balance': new_bal}, broadcast=False)
    Socketio.emit('update_selected_cards', {'taken_cards': list(game_state['selected_cards'].values())})

@socketio.on('player_mark_number')
def handle_player_mark(data):
    Uid = int(data.get('user_id'))
    Card_id = int(data.get('card_id'))
    Marked_list = data.get('marked_numbers', [])

    If uid not in player_marked_hits:
        Player_marked_hits[uid] = {}
    Player_marked_hits[uid][card_id] = set(marked_list)

@socketio.on('claim_bingo')
def handle_bingo_claim(data):
    User_sid = request.sid
    Uid = int(data.get('user_id'))
    Card_id = int(data.get('card_id'))
    Board = data.get('board')
    
    If game_state["status"] != "PLAYING":
        Emit('bingo_response', {'status': 'error', 'message': 'ጨዋታው ገና አልጀመረም!'}, room=user_sid)
        Return

    Is_valid = validate_bingo_board(board)
    
    If is_valid:
        Emit('bingo_response', {
            'status': 'success', 
            'message': 'እንኳን ደስ አለዎት! ትክክለኛ ቢንጎ ማሸነፍዎ ተረጋግጧል!'
        }, room=user_sid)
        
        Prize = game_state['derash']
        Game_state['status'] = 'ENDED'

        With db_lock:
            If uid in users_db:
                Users_db[uid]["balance"] += prize
                W_name = users_db[uid].get("name", f"Player {uid}")
                Socketio.emit('balance_update', {'user_id': uid, 'balance': users_db[uid]["balance"]})
            else:
                W_name = f"Player {uid}"

        Add_user_history(uid, "የአሸናፊነት ሽልማት (Bingo Win)", f"+{prize:.2f} ETB አሸንፈዋል")

        Socketio.emit('winner_announced', {
            'winner_ids': [uid],
            'winner_name': w_name,
            'prize': prize,
            'card_id': card_id,
            'card_matrix': cards_database.get(card_id)
        })
    else:
        Emit('bingo_response', {
            'status': 'error', 
            'message': 'ስህተት! ገና በህጉ መሰረት ቢንጎ አልደረሱም!'
        }, room=user_sid)

Player_marked_hits = {}

Def game_loop():
    Global game_state, player_marked_hits
    While True:
        Game_state["status"] = "WAITING"
        Game_state["time_left"] = 15
        Game_state["selected_cards"] = {}
        Game_state["player_cards"] = {}
        Game_state["drawn_numbers"] = []
        Player_marked_hits = {}
        Socketio.emit('reset_game')
        Socketio.emit('update_selected_cards', {'taken_cards': []})

        While len(game_state["selected_cards"]) == 0:
            Socketio.sleep(1)

        Game_state["status"] = "COUNTDOWN"
        For t in range(15, 0, -1):
            If len(game_state["selected_cards"]) == 0:
                Break
            Socketio.emit('timer_update', {
                'time_left': t,
                'sold_count': len(game_state["selected_cards"])
            })
            Socketio.sleep(1)

        Game_state["status"] = "PLAYING"
        Total_pool = len(game_state["selected_cards"]) * CARD_PRICE
        Derash = total_pool * (1 - COMMISSION_RATE)
        Game_state["derash"] = derash

        Socketio.emit('game_started', {'status': 'PLAYING', 'derash': derash})

        Available_balls = list(range(1, 76))
        Random.shuffle(available_balls)

        For ball in available_balls:
            If game_state["status"] != "PLAYING":
                Break

            Game_state["drawn_numbers"].append(ball)
            Ball_info = get_letter_and_display(ball)
            
            Socketio.emit('new_number', {
                'ball': ball, 
                'display': ball_info['display']
            })
            Socketio.sleep(4) 

        If game_state["status"] == "PLAYING":
            Game_state["status"] = "ENDED"
            Socketio.emit('winner_announced', {
                'winner_ids': [],
                'winner_name': 'ምንም አሸናፊ የለም (Draw)',
                'prize': 0.0,
                'card_id': 0,
                'card_matrix': None
            })

        Socketio.sleep(8)

Def run_main_bot():
    Set_bot_commands()
    While True:
        Try:
            Bot.remove_webhook()
            Time.sleep(1)
            Bot.infinity_polling(skip_pending=True)
        Except Exception as e:
            Print(f"Main Bot Error: {e}")
            Time.sleep(3)

Def run_support_bot():
    While True:
        Try:
            Support_bot.remove_webhook()
            Time.sleep(1)
            Support_bot.infinity_polling(skip_pending=True)
        Except Exception as e:
            Print(f"Support Bot Error: {e}")
            Time.sleep(3)

If __name__ == '__main__':
    Main_bot_thread = Thread(target=run_main_bot)
    Main_bot_thread.daemon = True
    Main_bot_thread.start()

    Support_bot_thread = Thread(target=run_support_bot)
    Support_bot_thread.daemon = True
    Support_bot_thread.start()

    Socketio.start_background_task(game_loop)
    
    Port = int(os.environ.get("PORT", 10000))
    Socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)

