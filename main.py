from datetime import datetime
import os
import random
import re
import threading
import time
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from gevent import monkey
import sqlalchemy as sa

monkey.patch_all(all=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'bkbingo_secret_key_2026'

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

PROCESSED_TIDS = set()


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


class Deposit(db.Model):
  __tablename__ = 'deposits'
  id = db.Column(db.Integer, primary_key=True)
  user_id = db.Column(db.String(100), nullable=False)
  amount = db.Column(db.Float, nullable=False)
  transaction_ref = db.Column(db.String(100), nullable=True)
  sms_text = db.Column(db.Text, nullable=True)
  method = db.Column(db.String(50), nullable=True)
  status = db.Column(db.String(20), default='Pending')


with app.app_context():
  db.create_all()
  inspector = sa.inspect(db.engine)
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


@socketio.on('admin_approve_deposit')
def handle_admin_approve_deposit(data):
  deposit_id = int(data.get('deposit_id', 0))
  deposit = Deposit.query.get(deposit_id)
  if deposit and deposit.status == 'Pending':
    deposit.status = 'Approved'
    if deposit.transaction_ref and deposit.transaction_ref != 'N/A':
      PROCESSED_TIDS.add(deposit.transaction_ref)
      
    user_id = deposit.user_id
    amount = deposit.amount

    user = User.query.filter_by(user_id=str(user_id)).first()
    if user:
      user.balance = float(user.balance) + float(amount)
      db.session.commit()
      socketio.emit(
          'balance_update',
          {'user_id': user_id, 'balance': user.balance},
      )
      send_telegram_custom_message(
          user_id,
          f'🎉 ክፍያዎ ጸድቋል! {amount} ብር ተጨምሯል። አዲሱ ባላንስዎ: {user.balance} ብር ነው።',
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


@socketio.on('admin_reject_deposit')
def handle_admin_reject_deposit(data):
  deposit_id = int(data.get('deposit_id', 0))
  deposit = Deposit.query.get(deposit_id)
  if deposit and deposit.status == 'Pending':
    deposit.status = 'Rejected'
    db.session.commit()
    send_telegram_custom_message(
        deposit.user_id,
        f'❌ የዲፖዚት ጥያቄዎ ({deposit.amount} ብር) ውድቅ ተደርጓል።',
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


@app.route('/admin')
def admin_panel():
  return render_template('admin.html')


socketio.start_background_task(background_game_loop)

if __name__ == '__main__':
  port = int(os.environ.get('PORT', 10000))
  socketio.run(app, host='0.0.0.0', port=port, debug=False)
