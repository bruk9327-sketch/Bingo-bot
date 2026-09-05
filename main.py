from gevent import monkey
monkey.patch_all(all=True)
from datetime import datetime
import os
import random
import re
import threading
import time
import traceback
from flask import Flask, jsonify, render_template, request, redirect, url_for, session, flash
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from gevent import monkey
import sqlalchemy as sa
from sqlalchemy import func
import requests

monkey.patch_all(all=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'bkbingo_secret_key_2026')

database_url = os.environ.get('DATABASE_URL', 'sqlite:///bkbingo.db')
if database_url.startswith('postgres://'):
  database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='gevent')

TELEGRAM_BOT_TOKEN = os.environ.get(
    'TELEGRAM_BOT_TOKEN', '8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM'
)
TELEGRAM_ADMIN_CHAT_ID = os.environ.get(
    'TELEGRAM_ADMIN_CHAT_ID', '8912812512'
)

# የአድሚን ፓስወርድ ከ Environment Variable (Render) ማንበብ
ADMIN_SECRET_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Biruk@123456')

PROCESSED_TIDS = set()


# ==========================================
# Telebirr Integration Functions (Fixed & Secured)
# ==========================================
def apply_fabric_token():
    url = "https://developerportal.ethiotelecom.et:18443/payment/v1/token"
    
    app_id = os.environ.get("FABRIC_APP_ID")
    app_secret = os.environ.get("APP_SECRET")
    
    headers = {
        "Content-Type": "application/json",
        "X-APP-Key": app_id
    }
    
    payload = {
        "appId": app_id,
        "appSecret": app_secret
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, verify=True, timeout=10)
        print("Telebirr Token Response:", response.status_code, response.text)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print("Telebirr Token API Error:", str(e))
        traceback.print_exc()
        return {"error": str(e)}

def create_telebirr_order(amount, user_phone, out_trade_no):
    token_response = apply_fabric_token()
    
    if isinstance(token_response, dict) and (token_response.get("code") == "0" or token_response.get("code") == 0):
        access_token = token_response.get("data", {}).get("accessToken") or token_response.get("accessToken")
    else:
        return {"error": "Token generation failed", "details": token_response}

    url = "https://developerportal.ethiotelecom.et:18443/payment/v1/order"
    
    merchant_app_id = os.environ.get("MERCHANT_APP_ID")
    short_code = os.environ.get("MERCHANT_SHORT_CODE", "642077")
    
    base_url = request.host_url.rstrip('/')
    
    headers = {
        "Content-Type": "application/json",
        "X-Auth-Token": access_token
    }
    
    payload = {
        "merchantAppId": merchant_app_id,
        "merchCode": short_code,
        "amount": str(amount),
        "outTradeNo": out_trade_no,
        "subject": "BKBINGO PRO Deposit",
        "notifyUrl": f"{base_url}/telebirr-callback",
        "returnUrl": f"https://t.me/{os.environ.get('TELEGRAM_BOT_USERNAME', 'your_telegram_bot')}"
    }
    
    try:
        verify_ssl = os.environ.get('VERIFY_TELEBIRR_SSL', 'False').lower() == 'true'
        response = requests.post(url, json=payload, headers=headers, verify=verify_ssl, timeout=15)
        print("Telebirr Order Response:", response.status_code, response.text)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print("Telebirr Order API Error:", str(e))
        traceback.print_exc()
        return {"error": str(e)}

def create_telebirr_order_with_merchant(amount, user_phone, out_trade_no):
    return create_telebirr_order(amount, user_phone, out_trade_no)


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
  created_at = db.Column(db.DateTime, default=datetime.utcnow)


with app.app_context():
  db.create_all()
  inspector = sa.inspect(db.engine)
  tables = inspector.get_table_names()
  
  if 'users' in tables:
    columns = [col['name'] for col in inspector.get_columns('users')]
    with db.engine.connect() as conn:
      if 'full_name' not in columns:
        conn.execute(sa.text('ALTER TABLE users ADD COLUMN full_name VARCHAR(150);'))
        conn.commit()
      if 'username' not in columns:
        conn.execute(sa.text('ALTER TABLE users ADD COLUMN username VARCHAR(100);'))
        conn.commit()
      if 'email' not in columns:
        conn.execute(sa.text('ALTER TABLE users ADD COLUMN email VARCHAR(120);'))
        conn.commit()
      if 'phone' not in columns:
        conn.execute(sa.text('ALTER TABLE users ADD COLUMN phone VARCHAR(50);'))
        conn.commit()
      if 'password' not in columns:
        conn.execute(sa.text('ALTER TABLE users ADD COLUMN password VARCHAR(255);'))
        conn.commit()
      if 'balance' not in columns:
        conn.execute(sa.text('ALTER TABLE users ADD COLUMN balance FLOAT DEFAULT 50.00;'))
        conn.commit()

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


def send_telegram_custom_message(chat_id, text):
  if TELEGRAM_BOT_TOKEN == '8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM':
    return
  url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
  payload = {'chat_id': chat_id, 'text': text}
  try:
    requests.post(url, json=payload, timeout=5)
  except Exception as e:
    print('Telegram Custom Message Error:', e)


@socketio.on('connect')
def handle_connect():
  emit('update_selected_cards', {'taken_cards': taken_cards_global})
  emit(
      'timer_update',
      {'time_left': game_timer, 'sold_count': len(sold_cards_in_round)},
  )


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

  if user and user.password == password:
    emit('auth_response', {
        'success': True,
        'msg': 'እንኳን ደህና መጡ!',
        'user_id': user.user_id,
        'balance': user.balance,
        'full_name': user.full_name
    }, room=request.sid)
  else:
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
        balance=50.00
    )
    db.session.add(user)
    db.session.commit()

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


@socketio.on('get_registered_users')
def handle_get_registered_users(data):
  users_list = [
      {
          'user_id': u.user_id,
          'phone': u.phone,
          'username': u.username,
          'full_name': u.full_name,
          'email': u.email,
          'balance': u.balance,
      }
      for u in User.query.all()
  ]
  emit('registered_users_list', {'users': users_list}, room=request.sid)


@socketio.on('get_admin_stats')
def handle_get_admin_stats(data):
  total_users = User.query.count()
  total_revenue = len(sold_cards_in_round) * 10.00
  emit(
      'admin_stats_data',
      {'total_users': total_users, 'total_revenue': total_revenue},
      room=request.sid,
  )


@socketio.on('get_pending_deposits')
def handle_get_pending_deposits(data):
  pending_list = Deposit.query.filter_by(status='Pending').all()
  deposits_data = [
      {
          'id': d.id,
          'user_id': d.user_id,
          'amount': d.amount,
          'transaction_ref': d.transaction_ref,
          'method': d.method,
          'status': d.status,
      }
      for d in pending_list
  ]
  emit('admin_deposits_data', {'deposits': deposits_data}, room=request.sid)


@socketio.on('admin_broadcast')
def handle_admin_broadcast(data):
  message = data.get('message')
  if message:
    socketio.emit('receive_broadcast', {'text': message})


def extract_transaction_info(sms_text):
  try:
    tid_match = re.search(r'TID=([A-Za-z0-9]+)', sms_text)
    if tid_match:
      return tid_match.group(1)
    general_match = re.search(r'\b([A-Z0-9]{10,})\b', sms_text)
    if general_match:
      return general_match.group(1)
    return None
  except Exception as e:
    print(f'Parsing Error: {e}')
    return None


@socketio.on('request_deposit')
def handle_request_deposit(data):
  try:
    user_id = str(data.get('user_id'))
    amount = float(data.get('amount', 0))
    sms_text = data.get('sms_text', '')
    tx_ref = data.get('tx_ref') or data.get('transaction_ref') or ''
    tx_ref = tx_ref.strip()
    
    if not tx_ref and sms_text:
      tx_ref = extract_transaction_info(sms_text) or ''
    
    method = data.get('method', 'CBE Merchant')

    if not user_id or not amount or (not tx_ref and not sms_text):
      emit('error_msg', {'msg': 'እባክዎ የዲፖዚት መረጃውን ሙሉ በሙሉ ይሙሉ።'}, room=request.sid)
      return

    if amount < 10:
      emit('error_msg', {'msg': 'ቢያንስ 10 ብር እና ከዚያ በላይ መጫን ይቻላል!'}, room=request.sid)
      return

    if tx_ref and tx_ref in PROCESSED_TIDS:
      emit('error_msg', {'msg': 'ይህ የክፍያ ደረሰኝ (TID) ከዚህ በፊት ጥቅም ላይ ውሏል!'}, room=request.sid)
      return

    deposit = Deposit(
        user_id=user_id,
        amount=amount,
        transaction_ref=tx_ref or 'N/A',
        sms_text=sms_text,
        method=method,
        status='Pending',
    )
    db.session.add(deposit)
    
    tx_record = Transaction(
        user_id=user_id,
        type='deposit',
        amount=amount,
        status='pending'
    )
    db.session.add(tx_record)
    db.session.commit()

    admin_msg = (
        f'💰 *አዲስ የዲፖዚት ጥያቄ (Socket)*\n\n'
        f'- ጥያቄ ID: `{deposit.id}`\n'
        f'- ተጠቃሚ ID: `{user_id}`\n'
        f'- መጠን: *{amount} ብር*\n'
        f'- ዘዴ: {method}\n'
        f'- Ref/TID: `{tx_ref}`'
    )

    inline_keyboard = {
        'inline_keyboard': [[
            {
                'text': '✅ አረጋግጥ (Approve)',
                'callback_data': f'approve_dep_{deposit.id}',
            },
            {
                'text': '❌ ሰርዝ (Reject)',
                'callback_data': f'reject_dep_{deposit.id}',
            },
        ]]
    }

    send_telegram_notification(admin_msg, reply_markup=inline_keyboard)

    emit(
        'deposit_response',
        {
            'status': 'success',
            'message': 'የዲፖዚት ጥያቄዎ በተሳካ ሁኔታ ተልኳል!',
            'dep_id': deposit.id,
        },
        room=request.sid,
    )

    pending_list = Deposit.query.filter_by(status='Pending').all()
    deposits_data = [
        {
            'id': d.id,
            'user_id': d.user_id,
            'amount': d.amount,
            'transaction_ref': d.transaction_ref,
            'method': d.method,
            'status': d.status,
        }
        for d in pending_list
    ]
    socketio.emit('admin_deposits_data', {'deposits': deposits_data})

  except Exception as e:
    print('Deposit Socket Error:', e)
    emit('error_msg', {'msg': 'የሰርቨር ስህተት አጋጥሟል።'}, room=request.sid)


@socketio.on('request_withdrawal')
def handle_request_withdrawal(data):
  user_id = str(data.get('user_id'))
  amount = float(data.get('amount', 0))
  account = data.get('account')
  method = data.get('method')

  if not user_id or amount <= 0 or not account:
    return

  user = User.query.filter_by(user_id=user_id).first()
  if not user or float(user.balance) < amount:
    return

  user.balance = float(user.balance) - amount
  
  tx_record = Transaction(
      user_id=user_id,
      type='withdrawal',
      amount=amount,
      status='pending'
  )
  db.session.add(tx_record)
  db.session.commit()

  emit(
      'balance_update',
      {'user_id': user_id, 'balance': user.balance},
      room=request.sid,
  )

  send_telegram_notification(
      f'📤 *የገንዘብ ማውጣት (Withdraw) ጥያቄ*\n\n'
      f'- ተጠቃሚ ID: `{user_id}`\n'
      f'- መጠን: *{amount} ብር*\n'
      f'- ዘዴ: {method}\n'
      f'- አካውንት: `{account}`'
  )


@socketio.on('get_user_balance')
def handle_get_balance(data):
  user_id = str(data.get('user_id'))
  if not user_id or user_id == 'None':
    return
  user = User.query.filter_by(user_id=user_id).first()
  if not user:
    return
    
  balance = user.balance
  emit(
      'balance_update',
      {'user_id': user_id, 'balance': float(balance)},
      room=request.sid,
  )
  emit(
      'update_selected_cards',
      {'taken_cards': taken_cards_global},
      room=request.sid,
  )
  emit(
      'timer_update',
      {'time_left': game_timer, 'sold_count': len(sold_cards_in_round)},
      room=request.sid,
  )


@socketio.on('select_card')
def handle_select_card(data):
  global game_active, taken_cards_global, sold_cards_in_round
  if game_active:
    emit(
        'error_msg',
        {'msg': 'ጨዋታው ተጀምሯል! እባክዎ የሚቀጥለውን ዙር ይጠብቁ።'},
        room=request.sid,
    )
    return

  user_id = str(data.get('user_id'))
  card_id = data.get('card_id')
  try:
    card_id = int(card_id)
  except:
    pass

  card_price = 10.00
  if not user_id or user_id == 'None':
    emit('error_msg', {'msg': 'እባክዎ መጀመሪያ ይመዝገቡ።'}, room=request.sid)
    return

  user = User.query.filter_by(user_id=user_id).first()
  if not user:
    emit('error_msg', {'msg': 'እባክዎ መጀመሪያ ይግቡ (Login)!'}, room=request.sid)
    return

  balance = user.balance

  if float(balance) < card_price:
    emit('error_msg', {'msg': 'በቂ ባላንስ የለዎትም! እባክዎ ሂሳብ ይሙሉ።'}, room=request.sid)
    return

  if card_id in taken_cards_global:
    emit(
        'error_msg',
        {'msg': 'ይህ ካርቴላ አስቀድሞ በሌላ ተጫዋች ተይዟል!'},
        room=request.sid,
    )
    return

  user.balance = float(user.balance) - card_price
  
  tx_record = Transaction(
      user_id=user_id,
      type='game_bet',
      amount=card_price,
      status='completed'
  )
  db.session.add(tx_record)
  db.session.commit()
  balance = user.balance

  taken_cards_global.append(card_id)
  sold_cards_in_round.append({'user_id': user_id, 'card_id': card_id})

  matrix = generate_bingo_matrix(card_id)

  emit(
      'balance_update',
      {'user_id': user_id, 'balance': float(balance)},
      room=request.sid,
  )
  emit(
      'card_confirmed',
      {
          'card_id': card_id,
          'matrix': matrix,
          'new_balance': float(balance),
      },
      room=request.sid,
  )
  socketio.emit('update_selected_cards', {'taken_cards': taken_cards_global})
  socketio.emit(
      'timer_update',
      {'time_left': game_timer, 'sold_count': len(sold_cards_in_round)},
  )


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
      game_active = False
      game_timer = 15
      taken_cards_global = []
      sold_cards_in_round = []
      drawn_balls = []
      available_numbers = list(range(1, 76))

      socketio.emit('reset_game', {})

      while game_timer > 0:
        socketio.emit(
            'timer_update',
            {'time_left': game_timer, 'sold_count': len(sold_cards_in_round)},
        )
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
        socketio.sleep(10)

      socketio.sleep(10)
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

    send_telegram_notification(
        f'🏆 *ቢንጎ አሸናፊ ተገኘ!*\n- ተጫዋች ID: `{user_id}`\n- ሽልማት: {prize_amount} ብር'
    )

    matrix = generate_bingo_matrix(card_id)
    
    emit('balance_update', {'user_id': user_id, 'balance': float(balance)}, room=request.sid)
    socketio.emit(
        'winner_announced',
        {
            'winner_name': full_name,
            'winner_ids': [user_id],
            'prize': prize_amount,
            'card_id': card_id,
            'card_matrix': matrix,
        },
    )
    socketio.sleep(6)
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


@app.route('/')
def index():
  return render_template('index.html')


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
        db.create_all()
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
            session['admin_name'] = admin.username
            return redirect(url_for('admin_dashboard'))
        
        elif password == ADMIN_SECRET_PASSWORD and (username == 'admin' or username == 'Biruk' or username == 'WolloAdmin2026!'):
            session['admin_logged'] = True
            session['is_admin'] = True
            session['admin_name'] = username
            return redirect(url_for('admin_dashboard'))
        else:
            error_msg = '⚠️ ትክክለኛ ያልሆነ የአስተዳዳሪ ስም ወይም የይለፍ ቃል!'
            
    return render_template('admin_login.html', error=error_msg)


@app.route('/admin/transaction/action/<int:tx_id>', methods=['POST'])
def admin_transaction_action(tx_id):
    if not session.get('is_admin') and not session.get('admin_logged'):
        return jsonify({'success': False, 'message': 'እባክዎ መጀመሪያ ይግቡ!'})
    
    action = request.form.get('action')
    tx = Transaction.query.get(tx_id)
    if not tx:
        return jsonify({'success': False, 'message': 'ትራንዛክሽኑ አልተገኘም!'})
    
    if action == 'approve':
        tx.status = 'completed'
        user = User.query.filter_by(user_id=tx.user_id).first()
        if user and tx.type == 'deposit':
            user.balance = float(user.balance) + float(tx.amount)
            send_telegram_custom_message(user.user_id, f'🎉 ክፍያዎ ጸድቋል! {tx.amount} ብር ተጨምሯል።')
        db.session.commit()
        return jsonify({'success': True})
        
    elif action == 'reject':
        tx.status = 'rejected'
        db.session.commit()
        send_telegram_custom_message(tx.user_id, f'❌ የክፍያ ጥያቄዎ ውድቅ ተደርጓል።')
        return jsonify({'success': True})
        
    return jsonify({'success': False, 'message': 'ትክክለኛ ያልሆነ እርምጃ!'})


# ==========================================
# Telebirr Payment & Callback Routes
# ==========================================
@app.route('/create-telebirr-payment', methods=['POST'])
def create_telebirr_payment():
    """ተጠቃሚው የሚፈልገውን የብር መጠን ተቀብሎ የክፍያ ሊንክ የሚያመነጭ ራውት ከትክክለኛ የኢረር ሀንድለር እና ሎግ ጋር"""
    try:
        data = request.get_json() or {}
        user_id = data.get('user_id')
        amount = data.get('amount')

        if not user_id or not amount:
            return jsonify({"success": False, "msg": "እባክዎ የተጠቃሚ መታወቂያ እና የብር መጠን ያስገቡ!"}), 400

        user = User.query.filter_by(user_id=user_id).first()
        user_phone = user.phone if user and user.phone else "251900000000"
        out_trade_no = f"BK_{int(time.time())}_{random.randint(1000, 9999)}"

        payment_response = create_telebirr_order_with_merchant(amount=amount, user_phone=user_phone, out_trade_no=out_trade_no)
        
        if payment_response and (payment_response.get("code") == "0" or payment_response.get("code") == 0):
            checkout_url = payment_response.get("data", {}).get("toUrl") or payment_response.get("toUrl")
            
            deposit = Deposit(
                user_id=str(user_id),
                amount=float(amount),
                transaction_ref=out_trade_no,
                method='Telebirr API (642077)',
                status='Pending'
            )
            db.session.add(deposit)
            
            tx_record = Transaction(
                user_id=str(user_id),
                type='deposit',
                amount=float(amount),
                status='pending'
            )
            db.session.add(tx_record)
            db.session.commit()

            return jsonify({"success": True, "checkout_url": checkout_url})
        else:
            print(f"[-] Telebirr Order Failed Response: {payment_response}")
            return jsonify({"success": False, "msg": "የክፍያ ሊንክ ማመንጨት አልተቻለም።", "details": payment_response}), 500

    except ValueError as ve:
        print(f"[-] ValueError detected: {str(ve)}")
        return jsonify({"success": False, "msg": f"የግቤት ስህተት: {str(ve)}"}), 400

    except requests.exceptions.RequestException as re:
        print(f"[-] Network/API Connection Error: {str(re)}")
        return jsonify({"success": False, "msg": "የክፍያ ሰርቨር (Telebirr API) ማግኘት አልተቻለም።"}), 503

    except Exception as e:
        print("[-] UNEXPECTED ERROR OCCURRED IN create_telebirr_payment:")
        traceback.print_exc()
        return jsonify({"success": False, "msg": f"የክፍያ ሊንክ ማመንጨት አልተቻለም። (ሲስተም ስህተት: {str(e)})"}), 500


@app.route('/telebirr-callback', methods=['POST'])
def telebirr_callback():
    """ቴሌብር ክፍያው ሲጠናቀቅ የሚልክለትን ማረጋገጫ ተቀብሎ የተጠቃሚውን ባላንስ በራስ-ሰር የሚያሳድግ ራውት"""
    try:
        callback_data = request.get_json() or request.form.to_dict()
        
        status = callback_data.get('status') or callback_data.get('transaction_status') or callback_data.get('tradeStatus')
        out_trade_no = callback_data.get('outTradeNo') or callback_data.get('transaction_ref')
        amount = callback_data.get('amount') or callback_data.get('total_amount')

        if status in ['SUCCESS', 'COMPLETED', 'SUCCESSFUL', '3'] and out_trade_no:
            deposit = Deposit.query.filter_by(transaction_ref=out_trade_no, status='Pending').first()
            if deposit:
                deposit.status = 'Completed'
                user_id = deposit.user_id
                numeric_amount = float(deposit.amount)

                user = User.query.filter_by(user_id=user_id).first()
                if user:
                    user.balance = float(user.balance) + numeric_amount
                
                tx = Transaction.query.filter_by(user_id=user_id, status='pending', type='deposit').order_by(Transaction.id.desc()).first()
                if tx:
                    tx.status = 'completed'

                db.session.commit()
                
                socketio.emit('balance_update', {'user_id': user_id, 'balance': user.balance if user else 0})
                send_telegram_custom_message(user_id, f'🎉 የቴሌብር ክፍያዎ በተሳካ ሁኔታ ጸድቋል! {numeric_amount} ብር አካውንትዎ ላይ ተጨምሯል።')

                return jsonify({"code": "0", "message": "success"}), 200

        return jsonify({"code": "1", "msg": "ክፍያው አልተሳካም ወይም መረጃው ጎድሏል።"}), 400
    except Exception as e:
        print("[-] Telebirr Callback Error:")
        traceback.print_exc()
        return jsonify({"code": "1", "message": str(e)}), 500


@app.route('/admin-logout')
def admin_logout():
    session.pop('admin_logged', None)
    session.pop('is_admin', None)
    session.pop('admin_name', None)
    return redirect(url_for('admin_login'))


socketio.start_background_task(background_game_loop)

if __name__ == '__main__':
  port = int(os.environ.get('PORT', 10000))
  socketio.run(app, host='0.0.0.0', port=port, debug=False)
