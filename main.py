from gevent import monkey
monkey.patch_all()

from datetime import datetime
import os
import random
import re
import threading
import time
import traceback
import base64
import json
from flask import Flask, jsonify, render_template, request, redirect, url_for, session, flash
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy as sa
from sqlalchemy import func, text
import requests
import urllib3

# cryptography ሞጁል በትክክለኛ መጫኑን በማረጋገጥ ስህተት እንዳይፈጥር በጥንቃቄ መያዝ
try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

# የ SSL ማስጠንቀቂያዎችን ማጥፋት (በ IP አድራሻ ለሚሰሩ ጌትዌዮች አስፈላጊ ነው)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'bkbingo_secret_key_2026')

# ==========================================
# Database Configuration & Psycopg2 Fix
# ==========================================
database_url = os.environ.get('DATABASE_URL', 'sqlite:///bkbingo.db')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql+psycopg2://', 1)
elif database_url and database_url.startswith('postgresql://'):
    database_url = database_url.replace('postgresql://', 'postgresql+psycopg2://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='gevent')

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8734350453:AAEcn3M7BOk9aHkRhhBU85HJoirIsw82B2I')
TELEGRAM_ADMIN_CHAT_ID = os.environ.get('TELEGRAM_ADMIN_CHAT_ID', '8912812512')
ADMIN_SECRET_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Biruk@123456')

PROCESSED_TIDS = set()


# ==========================================
# Telebirr Integration & RSA Signing Functions
# ==========================================
def generate_rsa_signature(payload_dict):
    if not CRYPTO_AVAILABLE:
        return "DUMMY_SIGNATURE_TO_BE_REPLACED_OR_GENERATED_VIA_RSA"

    private_key_str = os.environ.get("TELEBIRR_PRIVATE_KEY", "")
    if not private_key_str:
        return "DUMMY_SIGNATURE_TO_BE_REPLACED_OR_GENERATED_VIA_RSA"
    
    try:
        if "-----BEGIN" not in private_key_str:
            private_key_str = f"-----BEGIN PRIVATE KEY-----\n{private_key_str}\n-----END PRIVATE KEY-----"
            
        private_key = serialization.load_pem_private_key(
            private_key_str.encode('utf-8'),
            password=None,
            backend=default_backend()
        )
        
        flat_dict = {}
        for k, v in payload_dict.items():
            if k in ['sign', 'sign_type', 'header', 'refund_info', 'openType', 'raw_request']:
                continue
            if isinstance(v, dict):
                for sub_k, sub_v in v.items():
                    if sub_v is not None:
                        flat_dict[sub_k] = str(sub_v)
            else:
                if v is not None:
                    flat_dict[k] = str(v)

        sorted_keys = sorted(flat_dict.keys())
        canonical_pairs = [f"{k}={flat_dict[k]}" for k in sorted_keys if flat_dict[k] != ""]
        canonical_content = "&".join(canonical_pairs)
        
        signature = private_key.sign(
            canonical_content.encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')
    except Exception as e:
        print("RSA Signing Error:", str(e))
        return "DUMMY_SIGNATURE_TO_BE_REPLACED_OR_GENERATED_VIA_RSA"


def apply_fabric_token():
    url = "https://196.188.120.3:38443/apiaccess/payment/gateway/payment/v1/token"
    app_id = os.environ.get("FABRIC_APP_ID", "c4182ef8-9249-458a-985e-06d191f4d505")
    app_secret = os.environ.get("APP_SECRET", "fad0f06383c6297f545876694b974599")
    
    headers = {
        "Content-Type": "application/json",
        "X-APP-Key": app_id
    }
    payload = {
        "appSecret": app_secret,
        "method": "payment.applyh5token"
    }
    
    try:
        verify_ssl = os.environ.get('VERIFY_TELEBIRR_SSL', 'False').lower() == 'true'
        response = requests.post(url, json=payload, headers=headers, verify=verify_ssl, timeout=30)
        response.raise_for_status()
        res_data = response.json()
        
        if isinstance(res_data, dict):
            token = res_data.get("token") or res_data.get("data", {}).get("token") or res_data.get("access_token")
            return token
        return None
    except Exception as e:
        print("Telebirr Token API Error:", str(e))
        return None


def create_telebirr_order(amount, user_phone, out_trade_no):
    access_token = apply_fabric_token()
    if not access_token:
        return {"error": "Token generation failed"}

    url = "https://196.188.120.3:38443/apiaccess/payment/gateway/payment/v1/merchant/preOrder"
    merchant_id = os.environ.get("MERCHANT_ID", "930231098009602")
    merchant_code = os.environ.get("MERCHANT_CODE", "101011")
    app_id = os.environ.get("FABRIC_APP_ID", "c4182ef8-9249-458a-985e-06d191f4d505")
    
    base_url = request.host_url.rstrip('/')
    timestamp = str(int(time.time() * 1000))
    nonce_str = f"bkbingo_{int(time.time())}_{random.randint(1000, 9999)}"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": access_token,
        "X-APP-Key": app_id
    }
    
    biz_content = {
        "trans_currency": "ETB",
        "total_amount": str(amount),
        "merch_order_id": out_trade_no,
        "appid": merchant_id,
        "merch_code": merchant_code,
        "timeout_express": "120m",
        "trade_type": "InApp",
        "notify_url": f"{base_url}/telebirr-callback",
        "return_url": f"{base_url}/",
        "title": "BKBINGO PRO Deposit",
        "business_type": "BuyGoods",
        "payee_identifier": merchant_code,
        "payee_identifier_type": "04",
        "payee_type": "5000"
    }
    
    payload_to_sign = {
        "nonce_str": nonce_str,
        "biz_content": biz_content,
        "method": "payment.preorder",
        "version": "1.0",
        "timestamp": timestamp,
        **biz_content
    }
    
    signature_val = generate_rsa_signature(payload_to_sign)
    payload = {
        "nonce_str": nonce_str,
        "biz_content": biz_content,
        "method": "payment.preorder",
        "version": "1.0",
        "sign_type": "SHA256WithRSA",
        "timestamp": timestamp,
        "sign": signature_val
    }
    
    try:
        verify_ssl = os.environ.get('VERIFY_TELEBIRR_SSL', 'False').lower() == 'true'
        response = requests.post(url, json=payload, headers=headers, verify=verify_ssl, timeout=30)
        response.raise_for_status()
        res_json = response.json()
        
        if str(res_json.get("code")) == "0":
            data_content = res_json.get("data", {})
            prepay_id = data_content.get("prepay_id") if isinstance(data_content, dict) else res_json.get("prepay_id")
            raw_request = f"appid={merchant_id}&merch_code={merchant_code}&nonce_str={nonce_str}&prepay_id={prepay_id}&sign={signature_val}&sign_type=SHA256WithRSA&timestamp={timestamp}"
            res_json["raw_request"] = raw_request
            
        return res_json
    except Exception as e:
        print("Telebirr Order API Error:", str(e))
        return {"error": str(e)}


def query_telebirr_order(out_trade_no):
    access_token = apply_fabric_token()
    if not access_token:
        return {"error": "Token generation failed"}

    base_gateway = os.environ.get("TELEBIRR_BASE_URL", "https://196.188.120.3:38443/apiaccess/payment/gateway")
    url = f"{base_gateway}/v1/merchant/queryOrder"
    app_id = os.environ.get("FABRIC_APP_ID", "c4182ef8-9249-458a-985e-06d191f4d505")
    
    timestamp = str(int(time.time() * 1000))
    nonce_str = f"query_{int(time.time())}"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": access_token,
        "X-APP-Key": app_id
    }
    
    biz_content = {"merch_order_id": out_trade_no}
    payload_to_sign = {
        "nonce_str": nonce_str,
        "biz_content": biz_content,
        "method": "payment.queryorder",
        "version": "1.0",
        "timestamp": timestamp,
        **biz_content
    }
    
    payload = {
        "nonce_str": nonce_str,
        "biz_content": biz_content,
        "method": "payment.queryorder",
        "version": "1.0",
        "sign_type": "SHA256WithRSA",
        "timestamp": timestamp,
        "sign": generate_rsa_signature(payload_to_sign)
    }
    
    try:
        verify_ssl = os.environ.get('VERIFY_TELEBIRR_SSL', 'False').lower() == 'true'
        response = requests.post(url, json=payload, headers=headers, verify=verify_ssl, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print("Query Order Error:", str(e))
        return {"error": str(e)}


# ==========================================
# Database Models (Fully Synced with Columns)
# ==========================================
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    username = db.Column(db.String(100), nullable=True)
    full_name = db.Column(db.String(150), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    password = db.Column(db.String(255), nullable=True)
    balance = db.Column(db.Float, default=50.00)
    
    is_active = db.Column(db.Boolean, default=True)
    is_suspended = db.Column(db.Boolean, default=False)
    kyc_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AdminUser(db.Model):
    __tablename__ = 'admin_users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    contact = db.Column(db.String(100), nullable=False)
    password = db.Column(db.String(200), nullable=False)


class Deposit(db.Model):
    __tablename__ = 'deposits'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    transaction_ref = db.Column(db.String(100), nullable=True)
    sms_text = db.Column(db.Text, nullable=True)
    method = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), default='Pending')


class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='pending')
    transaction_ref = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SupportTicket(db.Model):
    __tablename__ = 'support_tickets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(150), nullable=True)
    message = db.Column(db.Text, nullable=False)
    attachment = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default='Pending')
    admin_reply = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


with app.app_context():
    db.create_all()
    try:
        with db.engine.connect() as conn:
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN DEFAULT FALSE;'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS kyc_verified BOOLEAN DEFAULT FALSE;'))
            conn.execute(text('ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;'))
            conn.commit()
            print("Successfully verified or added missing columns to database tables.")
    except Exception as migration_err:
        print("Auto migration check note:", migration_err)

taken_cards_global = []
game_timer = 15
game_active = False
sold_cards_in_round = []
drawn_balls = []
available_numbers = list(range(1, 76))


def send_telegram_notification(message, reply_markup=None):
    if TELEGRAM_BOT_TOKEN == '8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM':
        return
    try:
        url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
        payload = {
            'chat_id': TELEGRAM_ADMIN_CHAT_ID,
            'text': message,
            'parse_mode': 'Markdown',
        }
        if reply_markup:
            payload['reply_markup'] = reply_markup
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print('Telegram Notification Error:', e)


@socketio.on('connect')
def handle_connect():
    emit('update_selected_cards', {'taken_cards': taken_cards_global})
    emit('timer_update', {'time_left': game_timer, 'sold_count': len(sold_cards_in_round), 'game_active': game_active})


@socketio.on('login_user')
def handle_login_user(data):
    identifier = str(data.get('identifier') or '').strip()
    password = str(data.get('password') or '').strip()

    if not identifier or not password:
        emit('auth_response', {'success': False, 'msg': 'እባክዎ መግቢያ መረጃዎን ሙሉ በሙሉ ይሙሉ!'}, room=request.sid)
        return

    user = User.query.filter(
        (User.email == identifier) | (User.phone == identifier) | (User.username == identifier) | (User.user_id == identifier)
    ).first()

    if user:
        if user.is_suspended:
            emit('auth_response', {'success': False, 'msg': 'አካውንትዎ ታግዷል! እባክዎ አስተዳዳሪውን ያነጋግሩ።'}, room=request.sid)
            return

        if user.password == password:
            session['user_id'] = user.user_id
            emit('auth_response', {
                'success': True,
                'msg': 'እንኳን ደህና መጡ!',
                'user_id': user.user_id,
                'balance': user.balance,
                'full_name': user.full_name
            }, room=request.sid)
            return

    emit('auth_response', {'success': False, 'msg': 'የተሳሳተ ኢሜይል/ስልክ/ዩዘርኔም ወይም የይለፍ ቃል!'}, room=request.sid)


@socketio.on('register_user')
def handle_register_user(data):
    full_name = data.get('full_name')
    username = data.get('username')
    email = data.get('email')
    phone = data.get('phone')
    password = data.get('password')
    user_id = str(phone or email or username or f'user_{int(time.time())}')

    if not full_name or not password or (not email and not phone):
        emit('auth_response', {'success': False, 'msg': 'እባክዎ ትክክለኛ መረጃ እና የይለፍ ቃል ይሙሉ!'}, room=request.sid)
        return

    try:
        existing = User.query.filter((User.email == email) | (User.phone == phone) | (User.user_id == user_id) | (User.username == username)).first()
        if existing:
            emit('auth_response', {'success': False, 'msg': 'ይህ ኢሜይል፣ ስልክ ቁጥር ወይም ዩዘርኔም አስቀድሞ ተመዝግቧል!'}, room=request.sid)
            return

        user = User(
            user_id=user_id,
            full_name=full_name,
            username=username,
            email=email,
            phone=phone,
            password=password,
            balance=50.00,
            is_active=True,
            is_suspended=False,
            kyc_verified=False
        )
        db.session.add(user)
        db.session.commit()

        session['user_id'] = user.user_id
        emit('auth_response', {
            'success': True,
            'msg': 'ምዝገባው በተሳካ ሁኔታ ተጠናቋል! 50 ብር ቦነስ ተሰጥቶዎታል።',
            'user_id': user.user_id,
            'balance': user.balance,
            'full_name': user.full_name
        }, room=request.sid)

    except Exception as e:
        db.session.rollback()
        emit('auth_response', {'success': False, 'msg': f'ስህተት ተፈጥሯል: {str(e)}'}, room=request.sid)


@socketio.on('select_card')
def handle_select_card(data):
    global game_active, taken_cards_global, sold_cards_in_round
    if game_active:
        emit('error_msg', {'msg': 'ጨዋታው ተጀምሯል! እባክዎ የሚቀጥለውን ዙር ይጠብቁ።'}, room=request.sid)
        return

    user_id = str(data.get('user_id'))
    try:
        card_id = int(data.get('card_id'))
    except:
        emit('error_msg', {'msg': 'ትክክለኛ ያልሆነ የካርቴላ መለያ!'}, room=request.sid)
        return

    if card_id < 1 or card_id > 104:
        emit('error_msg', {'msg': 'የካርቴላ ቁጥር ከ 1 እስከ 104 መሆን አለበት!'}, room=request.sid)
        return

    card_price = 10.00
    user = User.query.filter_by(user_id=user_id).first()
    if not user or user.is_suspended:
        emit('error_msg', {'msg': 'አካውንትዎ ታግዷል ወይም አልተገኘም!'}, room=request.sid)
        return

    if float(user.balance) < card_price:
        emit('error_msg', {'msg': 'በቂ ባላንስ የለዎትም! እባክዎ ሂሳብ ይሙሉ።'}, room=request.sid)
        return

    if card_id in taken_cards_global:
        emit('error_msg', {'msg': 'ይህ ካርቴላ አስቀድሞ በሌላ ተጫዋች ተይዟል!'}, room=request.sid)
        return

    user.balance = float(user.balance) - card_price
    tx_record = Transaction(user_id=user_id, type='game_bet', amount=card_price, status='completed')
    db.session.add(tx_record)
    db.session.commit()

    taken_cards_global.append(card_id)
    sold_cards_in_round.append({'user_id': user_id, 'card_id': card_id})
    matrix = generate_bingo_matrix(card_id)

    emit('balance_update', {'user_id': user_id, 'balance': float(user.balance)}, room=request.sid)
    emit('card_confirmed', {'card_id': card_id, 'matrix': matrix, 'new_balance': float(user.balance)}, room=request.sid)
    
    socketio.emit('update_selected_cards', {'taken_cards': taken_cards_global})
    socketio.emit('timer_update', {'time_left': game_timer, 'sold_count': len(sold_cards_in_round), 'game_active': game_active})


def generate_bingo_matrix(seed_val):
    try:
        random.seed(int(seed_val))
    except:
        random.seed(1)
    b = random.sample(range(1, 16), 5)
    i = random.sample(range(16, 31), 5)
    n = random.sample(range(31, 46), 4)
    n.insert(2, 'FREE')
    g = random.sample(range(46, 61), 5)
    o = random.sample(range(61, 76), 5)

    matrix = []
    for row in range(5):
        matrix.append([b[row], i[row], n[row], g[row], o[row]])
    return matrix


def background_game_loop():
    global game_timer, game_active, taken_cards_global, sold_cards_in_round, drawn_balls, available_numbers
    while True:
        try:
            with app.app_context():
                game_active = False
                game_timer = 15
                taken_cards_global = []
                sold_cards_in_round = []
                drawn_balls = []
                available_numbers = list(range(1, 76))

                socketio.emit('reset_game', {})

                while game_timer > 0:
                    socketio.emit('timer_update', {'time_left': game_timer, 'sold_count': len(sold_cards_in_round), 'game_active': False})
                    socketio.sleep(1)
                    game_timer -= 1

                if len(sold_cards_in_round) == 0:
                    continue

                game_active = True
                total_pool = len(sold_cards_in_round) * 10.00
                derash = total_pool * 0.90

                socketio.emit('game_started', {'derash': derash})
                random.shuffle(available_numbers)

                for ball in available_numbers:
                    if not game_active:
                        break
                    drawn_balls.append(ball)
                    socketio.emit('number_drawn', {'number': ball})
                    socketio.sleep(4)

                socketio.sleep(5)
        except Exception as e:
            print('Background Game Loop Error:', e)
            socketio.sleep(1)


@socketio.on('claim_bingo')
def handle_claim_bingo(data):
    global game_active
    user_id = str(data.get('user_id'))
    card_id = data.get('card_id')
    board = data.get('board')

    if check_bingo_win(board):
        game_active = False
        total_pool = len(sold_cards_in_round) * 10.00
        prize_amount = max(total_pool * 0.90, 8)

        user = User.query.filter_by(user_id=user_id).first()
        if user:
            user.balance = float(user.balance) + float(prize_amount)
            db.session.commit()
            balance = user.balance
            full_name = user.full_name or f'ተጫዋች {user_id}'
        else:
            balance = 50.00 + float(prize_amount)
            full_name = f'ተጫዋች {user_id}'

        send_telegram_notification(f'🏆 *ቢንጎ አሸናፊ ተገኘ!*\n- ተጫዋች ID: `{user_id}`\n- ሽልማት: {prize_amount} ብር')
        matrix = generate_bingo_matrix(card_id)
        
        emit('balance_update', {'user_id': user_id, 'balance': float(balance)}, room=request.sid)
        socketio.emit('winner_announced', {
            'winner_name': full_name,
            'winner_ids': [user_id],
            'prize': prize_amount,
            'card_id': card_id,
            'card_matrix': matrix,
        })
        socketio.sleep(5)
        reset_game_state_completely()
    else:
        emit('error_msg', {'msg': '❌ ቢንጎ አልተሟላም!'}, room=request.sid)


def check_bingo_win(board):
    if not board or not isinstance(board, list):
        return False
    try:
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
    except Exception as e:
        print('Check Bingo Error:', e)
    return False


def reset_game_state_completely():
    global game_timer, game_active, taken_cards_global, sold_cards_in_round, drawn_balls, available_numbers
    taken_cards_global = []
    sold_cards_in_round = []
    drawn_balls = []
    available_numbers = list(range(1, 76))
    game_timer = 15
    game_active = False
    socketio.emit('reset_game', {})


# ==========================================
# Web Routes & Telebirr Callbacks
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/create-telebirr-payment', methods=['POST'])
def create_telebirr_payment():
    data = request.get_json() or {}
    amount = data.get('amount')
    user_phone = data.get('phone') or data.get('user_phone')
    user_id = data.get('user_id') or 'unknown'
    out_trade_no = data.get('out_trade_no') or f"bk_{user_id}_{int(time.time())}_{random.randint(1000, 9999)}"
    
    if not amount or not user_phone:
        return jsonify({"success": False, "msg": "እባክዎ መጠኑን እና ስልክ ቁጥሩን በትክክል ያስገቡ!"}), 400
        
    result = create_telebirr_order(amount, user_phone, out_trade_no)
    return jsonify(result)


@app.route('/check-telebirr-order/<out_trade_no>', methods=['GET'])
def check_telebirr_order_route(out_trade_no):
    result = query_telebirr_order(out_trade_no)
    return jsonify(result)


@app.route('/telebirr-callback', methods=['POST'])
def telebirr_callback():
    try:
        data = request.get_json() or request.form.to_dict()
        biz_content = data.get("biz_content", {})
        if isinstance(biz_content, str):
            try:
                biz_content = json.loads(biz_content)
            except:
                biz_content = {}
                
        merch_order_id = data.get("merch_order_id") or biz_content.get("merch_order_id")
        trade_status = data.get("trade_status") or biz_content.get("trade_status")
        total_amount = float(data.get("total_amount") or biz_content.get("total_amount") or 0)
        
        if merch_order_id and merch_order_id in PROCESSED_TIDS:
            return jsonify({"code": 0, "msg": "Already processed"})

        if trade_status in ["PAY_SUCCESS", "Completed", "SUCCESS"]:
            if merch_order_id:
                PROCESSED_TIDS.add(merch_order_id)
            
            target_user_id = None
            if merch_order_id and merch_order_id.startswith("bk_"):
                parts = merch_order_id.split("_")
                if len(parts) >= 3:
                    target_user_id = parts[1]
            
            if target_user_id:
                user = User.query.filter_by(user_id=target_user_id).first()
                if user and total_amount > 0:
                    user.balance = float(user.balance) + float(total_amount)
                    tx_record = Transaction(
                        user_id=target_user_id,
                        type='deposit',
                        amount=float(total_amount),
                        status='completed',
                        transaction_ref=merch_order_id
                    )
                    db.session.add(tx_record)
                    db.session.commit()
                    socketio.emit('balance_update', {'user_id': target_user_id, 'balance': float(user.balance)})
            
            send_telegram_notification(f"✅ *የቴሌብር ክፍያ ተሳካ!*\n- ትዕዛዝ ID: `{merch_order_id}`\n- ተጠቃሚ ID: `{target_user_id}`\n- መጠን: *{total_amount} ብር*")

        return jsonify({"code": 0, "msg": "success", "data": {}})
    except Exception as e:
        print("Callback Error:", e)
        db.session.rollback()
        return jsonify({"code": -1, "msg": str(e)}), 400


# ==========================================
# Support Ticket Routes
# ==========================================
@app.route('/support', methods=['GET', 'POST'])
def user_support():
    current_user_id = session.get('user_id') or request.args.get('user_id')
    tickets = []
    if current_user_id:
        tickets = SupportTicket.query.filter_by(user_id=current_user_id).order_by(SupportTicket.created_at.desc()).all()
    return render_template('support.html', tickets=tickets)


@app.route('/api/support/submit', methods=['POST'])
def submit_support_ticket():
    user_id = request.form.get('user_id')
    subject = request.form.get('subject', 'የደንበኞች አገልግሎት ጥያቄ')
    message = request.form.get('message')
    
    file = request.files.get('attachment')
    filename = None
    if file:
        upload_folder = os.path.join('static', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        filename = f"{int(time.time())}_{file.filename}"
        file.save(os.path.join(upload_folder, filename))
        
    if not message or not user_id:
        return jsonify({"success": False, "msg": "እባክዎ መልዕክትዎን ይሙሉ!"}), 400
        
    ticket = SupportTicket(
        user_id=user_id,
        subject=subject,
        message=message,
        attachment=filename,
        status='Pending'
    )
    db.session.add(ticket)
    db.session.commit()
    
    send_telegram_notification(f"🎧 *አዲስ የደንበኛ ጥያቄ መጣ!*\n- ተጠቃሚ ID: `{user_id}`\n- መልዕክት: {message}")
    return jsonify({"success": True, "msg": "ጥያቄዎ በተሳካ ሁኔታ ተልኳል። አድሚኑ ምላሽ ይሰጥበታል።"})


@app.route('/api/support/user-tickets', methods=['GET'])
def get_user_tickets():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'msg': 'User ID is required'}), 400
        
    tickets = SupportTicket.query.filter_by(user_id=user_id).order_by(SupportTicket.created_at.desc()).all()
    
    tickets_data = [{
        'id': t.id,
        'subject': t.subject,
        'message': t.message,
        'status': t.status,
        'admin_reply': t.admin_reply,
        'created_at': t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else ''
    } for t in tickets]
    
    return jsonify({'success': True, 'tickets': tickets_data})


# ==========================================
# Admin Support & Dashboard Routes
# ==========================================
@app.route('/admin/support', methods=['GET'])
def admin_support_list():
    if not session.get('is_admin') and not session.get('admin_logged'):
        return redirect(url_for('admin_login'))
    tickets = SupportTicket.query.order_by(SupportTicket.created_at.desc()).all()
    return render_template('admin_support.html', tickets=tickets)


@app.route('/admin/support/<int:ticket_id>/reply', methods=['POST'])
def admin_reply_ticket(ticket_id):
    if not session.get('is_admin') and not session.get('admin_logged'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    ticket = SupportTicket.query.get_or_404(ticket_id)
    reply_text = request.form.get('admin_reply') or request.json.get('admin_reply')
    
    try:
        ticket.admin_reply = reply_text
        ticket.status = 'Answered'
        db.session.commit()
        return jsonify({'success': True, 'message': 'ምላሹ ተልኳል።'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/admin', methods=['GET'])
def admin_dashboard():
    if not session.get('is_admin') and not session.get('admin_logged'):
        return redirect(url_for('admin_login'))
    
    try:
        total_users = User.query.count() or 0
        total_orders = Transaction.query.filter_by(type='game_bet').count() or 0
        
        total_revenue = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.type == 'deposit', 
            Transaction.status == 'completed'
        ).scalar() or 0.0
        
        total_profit = total_revenue * 0.25 
        
        today = datetime.utcnow().date()
        current_month = today.month
        current_year = today.year
        
        daily_revenue = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.type == 'deposit', 
            Transaction.status == 'completed',
            func.date(Transaction.created_at) == today
        ).scalar() or 0.0
        
        monthly_revenue = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.type == 'deposit',
            Transaction.status == 'completed',
            func.extract('month', Transaction.created_at) == current_month,
            func.extract('year', Transaction.created_at) == current_year
        ).scalar() or 0.0

        yearly_revenue = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.type == 'deposit',
            Transaction.status == 'completed',
            func.extract('year', Transaction.created_at) == current_year
        ).scalar() or 0.0

        pending_deposits = Transaction.query.filter_by(type='deposit', status='pending').all() or []
        pending_withdrawals = Transaction.query.filter_by(type='withdrawal', status='pending').all() or []

    except Exception as e:
        print(f"Database Error: {e}")
        total_users = 0
        total_orders = 0
        total_revenue = 0.0
        total_profit = 0.0
        daily_revenue = 0.0
        monthly_revenue = 0.0
        yearly_revenue = 0.0
        pending_deposits = []
        pending_withdrawals = []

    return render_template('admin.html',
                           total_users=total_users,
                           total_orders=total_orders,
                           total_revenue=total_revenue,
                           total_profit=total_profit,
                           daily_revenue=daily_revenue,
                           monthly_revenue=monthly_revenue,
                           yearly_revenue=yearly_revenue,
                           pending_deposits=pending_deposits,
                           pending_withdrawals=pending_withdrawals)


# ==========================================
# Admin Routes for Users Management
# ==========================================
@app.route('/admin/users', methods=['GET'])
def admin_users_management():
    if not session.get('is_admin') and not session.get('admin_logged'):
        return redirect(url_for('admin_login'))
    
    status_filter = request.args.get('status', 'all')
    
    try:
        if status_filter == 'active':
            users_list = User.query.filter_by(is_active=True, is_suspended=False).all()
        elif status_filter == 'suspended':
            users_list = User.query.filter_by(is_suspended=True).all()
        elif status_filter == 'kyc':
            users_list = User.query.filter_by(kyc_verified=True).all()
        else:
            users_list = User.query.all()
    except Exception as e:
        print("Users query filter error:", e)
        users_list = []

    return render_template('admin_users.html', users=users_list, current_filter=status_filter)


@app.route('/admin/users/<int:user_id>/update-status', methods=['POST'])
def admin_update_user_status(user_id):
    if not session.get('is_admin') and not session.get('admin_logged'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    user = User.query.get_or_404(user_id)
    data = request.get_json() or {}
    new_status = data.get('status')
    
    try:
        if new_status == 'suspended':
            user.is_suspended = True
            user.is_active = False
        elif new_status == 'active':
            user.is_suspended = False
            user.is_active = True
        elif new_status == 'kyc_verify':
            user.kyc_verified = True
            
        db.session.commit()
        return jsonify({'success': True, 'message': 'የተጠቃሚው ስታተስ በተሳካ ሁኔታ ተስተካክሏል።'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/admin/transaction/<int:tx_id>/action', methods=['POST'])
def admin_transaction_action(tx_id):
    if not session.get('is_admin') and not session.get('admin_logged'):
        flash("እባክዎ መጀመሪያ እንደ አድሚን ይግቡ!", "error")
        return redirect(url_for('admin_login'))

    action = request.form.get('action')
    tx = Transaction.query.get_or_404(tx_id)
    user = User.query.filter_by(user_id=tx.user_id).first()

    try:
        if tx.type == 'deposit':
            if action == 'approve':
                if tx.status != 'completed':
                    tx.status = 'completed'
                    if user:
                        user.balance = float(user.balance) + float(tx.amount)
                        socketio.emit('balance_update', {'user_id': user.user_id, 'balance': float(user.balance)})
                    flash(f"የዲፖዚት ጥያቄው (ID: {tx.id}) ጸድቋል!", "success")
            elif action == 'reject':
                tx.status = 'rejected'
                flash(f"የዲፖዚት ጥያቄው (ID: {tx.id}) ተሰርዟል!", "info")

        elif tx.type == 'withdrawal':
            if action == 'approve':
                if tx.status != 'completed':
                    tx.status = 'completed'
                    flash(f"የገንዘብ ማውጣት (Withdrawal) ጥያቄው (ID: {tx.id}) ጸድቋል!", "success")
            elif action == 'reject':
                if tx.status != 'rejected':
                    tx.status = 'rejected'
                    if user:
                        user.balance = float(user.balance) + float(tx.amount)
                        socketio.emit('balance_update', {'user_id': user.user_id, 'balance': float(user.balance)})
                    flash(f"የገንዘብ ማውጣት ጥያቄው (ID: {tx.id}) ተሰርዞ ገንዘቡ ተመልሷል!", "info")

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Transaction Action Error: {e}")
        flash(f"ስህተት ተፈጥሯል: {str(e)}", "error")

    return redirect(url_for('admin_dashboard'))


@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    error_msg = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin = AdminUser.query.filter((AdminUser.username == username) | (AdminUser.contact == username)).first()
        
        if admin and admin.password == password:
            session['admin_logged'] = True
            session['is_admin'] = True
            session['admin_name'] = username
            return redirect(url_for('admin_dashboard'))
        
        elif password == ADMIN_SECRET_PASSWORD and (username == 'admin' or username == 'Biruk' or username == 'WolloAdmin2026!'):
            session['admin_logged'] = True
            session['is_admin'] = True
            session['admin_name'] = username
            return redirect(url_for('admin_dashboard'))
        else:
            error_msg = 'የተሳሳተ መግቢያ ስም ወይም የይለፍ ቃል!'
            
    return render_template('admin_login.html', error_msg=error_msg)


if __name__ == '__main__':
    threading.Thread(target=background_game_loop, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port)
