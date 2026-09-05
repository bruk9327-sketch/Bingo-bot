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
import sqlalchemy as sa
from sqlalchemy import func
import requests

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

ADMIN_SECRET_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Biruk@123456')

PROCESSED_TIDS = set()


# ==========================================
# Telebirr Integration Functions
# ==========================================
def apply_fabric_token():
    base_gateway = os.environ.get("TELEBIRR_BASE_URL", "https://developerportal.ethiotelebr.et:38443/apiaccess/payment/gateway")
    url = f"{base_gateway}/payment/v1/token"
    
    app_id = os.environ.get("FABRIC_APP_ID", "c4182ef8-9249-458a-985e-06d191f4d505")
    app_secret = os.environ.get("APP_SECRET", "fad0f06383c6297f545876694b901639")
    
    headers = {
        "Content-Type": "application/json",
        "X-APP-Key": app_id
    }
    
    payload = {
        "appId": app_id,
        "appSecret": app_secret
    }
    
    try:
        verify_ssl = os.environ.get('VERIFY_TELEBIRR_SSL', 'False').lower() == 'true'
        response = requests.post(url, json=payload, headers=headers, verify=verify_ssl, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print("Telebirr Token API Error:", str(e))
        traceback.print_exc()
        return {"error": str(e)}


def create_telebirr_order(amount, user_phone, out_trade_no):
    token_response = apply_fabric_token()
    
    if isinstance(token_response, dict) and (str(token_response.get("code")) == "0" or token_response.get("code") == 0):
        access_token = token_response.get("data", {}).get("accessToken") or token_response.get("accessToken")
    else:
        return {"error": "Token generation failed", "details": token_response}

    base_gateway = os.environ.get("TELEBIRR_BASE_URL", "https://developerportal.ethiotelebr.et:38443/apiaccess/payment/gateway")
    url = f"{base_gateway}/payment/v1/order"
    
    merchant_app_id = os.environ.get("MERCHANT_APP_ID", "1688972571494400")
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


@socketio.on('select_card')
def handle_select_card(data):
  global game_active, taken_cards_global, sold_cards_in_round
  if game_active:
    emit('error_msg', {'msg': 'ጨዋታው ተጀምሯል! እባክዎ የሚቀጥለውን ዙር ይጠብቁ።'}, room=request.sid)
    return

  user_id = str(data.get('user_id'))
  card_id = data.get('card_id')
  try:
    card_id = int(card_id)
  except:
    pass

  card_price = 10.00
  user = User.query.filter_by(user_id=user_id).first()
  if not user:
    emit('error_msg', {'msg': 'እባክዎ መጀመሪያ ይግቡ (Login)!'}, room=request.sid)
    return

  if float(user.balance) < card_price:
    emit('error_msg', {'msg': 'በቂ ባላንስ የለዎትም! እባክዎ ሂሳብ ይሙሉ።'}, room=request.sid)
    return

  if card_id in taken_cards_global:
    emit('error_msg', {'msg': 'ይህ ካርቴላ አስቀድሞ በሌላ ተጫዋች ተይዟል!'}, room=request.sid)
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

  taken_cards_global.append(card_id)
  sold_cards_in_round.append({'user_id': user_id, 'card_id': card_id})

  matrix = generate_bingo_matrix(card_id)

  emit('balance_update', {'user_id': user_id, 'balance': float(user.balance)}, room=request.sid)
  emit('card_confirmed', {'card_id': card_id, 'matrix': matrix, 'new_balance': float(user.balance)}, room=request.sid)
  socketio.emit('update_selected_cards', {'taken_cards': taken_cards_global})
  socketio.emit('timer_update', {'time_left': game_timer, 'sold_count': len(sold_cards_in_round)})


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
        socketio.emit('timer_update', {'time_left': game_timer, 'sold_count': len(sold_cards_in_round)})
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


@app.route('/')
def index():
  return render_template('index.html')


@app.route('/admin', methods=['GET'])
def admin_dashboard():
    if not session.get('is_admin') and not session.get('admin_logged'):
        return redirect(url_for('admin_login'))
    
    total_users = User.query.count() or 0
    total_orders = Transaction.query.filter_by(type='game_bet').count() or 0
    total_revenue = db.session.query(func.sum(Transaction.amount)).filter(
        Transaction.type == 'deposit', Transaction.status == 'completed'
    ).scalar() or 0.0
    total_profit = total_revenue * 0.25

    return render_template('admin.html',
                           total_users=total_users,
                           total_orders=total_orders,
                           total_revenue=total_revenue,
                           total_profit=total_profit)


@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    error_msg = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if password == ADMIN_SECRET_PASSWORD and (username == 'admin' or username == 'Biruk'):
            session['admin_logged'] = True
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            error_msg = '⚠️ ትክክለኛ ያልሆነ የአስተዳዳሪ ስም ወይም የይለፍ ቃል!'
            
    return render_template('admin_login.html', error=error_msg)


# ==========================================
# Telebirr Payment & Callback Routes
# ==========================================
@app.route('/create-telebirr-payment', methods=['POST'])
def create_telebirr_payment():
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
        
        if payment_response and (str(payment_response.get("code")) == "0" or payment_response.get("code") == 0):
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
            error_msg = payment_response.get("msg") or payment_response.get("message") or "የክፍያ ሊንክ ማመንጨት አልተቻለም።"
            return jsonify({"success": False, "msg": error_msg, "details": payment_response}), 400

    except Exception as e:
        print("[-] UNEXPECTED ERROR IN create_telebirr_payment:")
        traceback.print_exc()
        return jsonify({"success": False, "msg": f"ሰርቨር ስህተት አጋጥሟል: {str(e)}"}), 500


@app.route('/telebirr-callback', methods=['POST'])
def telebirr_callback():
    try:
        callback_data = request.get_json() or request.form.to_dict()
        status = callback_data.get('status') or callback_data.get('tradeStatus')
        out_trade_no = callback_data.get('outTradeNo')

        if status in ['SUCCESS', 'COMPLETED', 'SUCCESSFUL', '3'] and out_trade_no:
            deposit = Deposit.query.filter_by(transaction_ref=out_trade_no, status='Pending').first()
            if deposit:
                deposit.status = 'Completed'
                user_id = deposit.user_id
                numeric_amount = float(deposit.amount)

                user = User.query.filter_by(user_id=user_id).first()
                if user:
                    user.balance = float(user.balance) + numeric_amount
                
                db.session.commit()
                socketio.emit('balance_update', {'user_id': user_id, 'balance': user.balance if user else 0})
                send_telegram_custom_message(user_id, f'🎉 የቴሌብር ክፍያዎ ጸድቋል! {numeric_amount} ብር ተጨምሯል።')

                return jsonify({"code": "0", "message": "success"}), 200

        return jsonify({"code": "1", "msg": "ክፍያው አልተሳካም።"}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"code": "1", "message": str(e)}), 500


socketio.start_background_task(background_game_loop)

if __name__ == '__main__':
  port = int(os.environ.get('PORT', 10000))
  socketio.run(app, host='0.0.0.0', port=port, debug=False)
