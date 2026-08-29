from gevent import monkey
monkey.patch_all(all=True)
from datetime import datetime
import os
import random
import re
import threading
import time
import requests
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'bkbingo_secret_key_2026'

socketio = SocketIO(app, cors_allowed_origins='*', async_mode='gevent')

TELEGRAM_BOT_TOKEN = os.environ.get(
    'TELEGRAM_BOT_TOKEN', '8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM'
)
TELEGRAM_ADMIN_CHAT_ID = os.environ.get(
    'TELEGRAM_ADMIN_CHAT_ID', '8912812512'
)

user_balances = {}
taken_cards_global = []
game_timer = 15
game_active = False
sold_cards_in_round = []
drawn_balls = []
available_numbers = list(range(1, 76))
registered_users_db = []
pending_deposits = {}
deposit_id_counter = 1


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


@socketio.on('register_user')
def handle_register_user(data):
  user_id = data.get('user_id') or data.get('phone') or data.get('username')
  if not user_id:
    user_id = data.get('phone', 'unknown_user')

  data['user_id'] = user_id

  existing_user = next(
      (u for u in registered_users_db if u.get('user_id') == user_id), None
  )

  if existing_user:
    existing_user.update(data)
  else:
    registered_users_db.append(data)

  if user_id not in user_balances:
    user_balances[user_id] = data.get('balance', 50.00)

  emit(
      'registration_success',
      {
          'msg': 'ምዝገባዎ በተሳካ ሁኔታ ተጠናቋል! 50 ብር ቦነስ ተሰጥቷል።',
          'user_id': user_id,
      },
      room=request.sid,
  )
  emit(
      'balance_update',
      {'user_id': user_id, 'balance': user_balances[user_id]},
      room=request.sid,
  )
  socketio.emit('registered_users_list', {'users': registered_users_db})


@socketio.on('get_registered_users')
def handle_get_registered_users(data):
  emit('registered_users_list', {'users': registered_users_db}, room=request.sid)


@socketio.on('get_pending_deposits')
def handle_get_pending_deposits(data):
  pending_list = [
      dep for dep in pending_deposits.values() if dep['status'] == 'Pending'
  ]
  emit('admin_pending_deposits', {'deposits': pending_list}, room=request.sid)


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
  global deposit_id_counter
  try:
    user_id = data.get('user_id')
    amount = float(data.get('amount', 0))
    sms_text = data.get('sms_text', '')
    tx_ref = data.get('tx_ref') or data.get('transaction_ref')
    if not tx_ref and sms_text:
      tx_ref = extract_transaction_info(sms_text)
    method = data.get('method', 'CBE Merchant')

    if not user_id or not amount or (not tx_ref and not sms_text):
      emit(
          'error_msg',
          {'msg': 'እባክዎ የዲፖዚት መረጃውን ሙሉ በሙሉ ይሙሉ።'},
          room=request.sid,
      )
      return

    if amount < 10:
      emit(
          'error_msg',
          {'msg': 'ቢያንስ 10 ብር እና ከዚያ በላይ መጫን ይቻላል!'},
          room=request.sid,
      )
      return

    dep_id = deposit_id_counter
    deposit_id_counter += 1

    pending_deposits[dep_id] = {
        'id': dep_id,
        'user_id': user_id,
        'amount': amount,
        'transaction_ref': tx_ref or 'N/A',
        'sms_text': sms_text,
        'method': method,
        'status': 'Pending',
    }

    admin_msg = (
        f'💰 *አዲስ የዲፖዚት ጥያቄ (Socket)*\n\n'
        f'- ጥያቄ ID: `{dep_id}`\n'
        f'- ተጠቃሚ ID: `{user_id}`\n'
        f'- መጠን: *{amount} ብር*\n'
        f'- ዘዴ: {method}\n'
        f'- Ref/TID: `{tx_ref}`'
    )

    inline_keyboard = {
        'inline_keyboard': [[
            {
                'text': '✅ አረጋግጥ (Approve)',
                'callback_data': f'approve_dep_{dep_id}',
            },
            {
                'text': '❌ ሰርዝ (Reject)',
                'callback_data': f'reject_dep_{dep_id}',
            },
        ]]
    }

    send_telegram_notification(admin_msg, reply_markup=inline_keyboard)

    emit(
        'deposit_response',
        {
            'status': 'success',
            'message': 'የዲፖዚት ጥያቄዎ በተሳካ ሁኔታ ተልኳል!',
            'dep_id': dep_id,
        },
        room=request.sid,
    )
  except Exception as e:
    print('Deposit Socket Error:', e)
    emit('error_msg', {'msg': 'የሰርቨር ስህተት አጋጥሟል።'}, room=request.sid)


@socketio.on('approve_deposit')
def handle_approve_deposit(data):
  deposit_id = int(data.get('deposit_id', 0))
  deposit = pending_deposits.get(deposit_id)
  if deposit and deposit['status'] == 'Pending':
    deposit['status'] = 'Approved'
    user_id = deposit['user_id']
    amount = deposit['amount']

    if user_id not in user_balances:
      user_balances[user_id] = 50.00
    user_balances[user_id] += amount

    socketio.emit(
        'balance_update',
        {'user_id': user_id, 'balance': user_balances[user_id]},
    )
    socketio.emit(
        'deposit_success',
        {
            'msg': f'🎉 በሰኬት {amount} ብር አካውንትዎ ተሞልቷል!',
            'new_balance': user_balances[user_id],
        },
    )
    send_telegram_custom_message(
        user_id,
        f'🎉 ክፍያዎ ጸድቋል! {amount} ብር ተጨምሯል። አዲሱ ባላንስዎ: {user_balances[user_id]}'
        ' ብር ነው።',
    )
    pending_list = [
        dep for dep in pending_deposits.values() if dep['status'] == 'Pending'
    ]
    socketio.emit('admin_pending_deposits', {'deposits': pending_list})


@socketio.on('reject_deposit')
def handle_reject_deposit(data):
  deposit_id = int(data.get('deposit_id', 0))
  deposit = pending_deposits.get(deposit_id)
  if deposit and deposit['status'] == 'Pending':
    deposit['status'] = 'Rejected'
    send_telegram_custom_message(
        deposit['user_id'],
        f'❌ የዲፖዚት ጥያቄዎ ({deposit["amount"]} ብር) ውድቅ ተደርጓል።',
    )
    pending_list = [
        dep for dep in pending_deposits.values() if dep['status'] == 'Pending'
    ]
    socketio.emit('admin_pending_deposits', {'deposits': pending_list})


@socketio.on('send_broadcast')
def handle_send_broadcast(data):
  text = data.get('text')
  media = data.get('media')
  file_type = data.get('type')
  socketio.emit(
      'receive_broadcast', {'text': text, 'media': media, 'type': file_type}
  )


@socketio.on('get_user_balance')
def handle_get_balance(data):
  user_id = data.get('user_id')
  if not user_id:
    return
  if user_id not in user_balances:
    user_balances[user_id] = 50.00
  emit('balance_update', {'user_id': user_id, 'balance': user_balances[user_id]})
  emit('update_selected_cards', {'taken_cards': taken_cards_global})
  emit(
      'timer_update',
      {'time_left': game_timer, 'sold_count': len(sold_cards_in_round)},
  )


@socketio.on('select_card')
def handle_select_card(data):
  global game_active, taken_cards_global, sold_cards_in_round
  if game_active:
    emit(
        'error_msg',
        {'msg': 'ጨዋታው ተጀምሯል! እባክዎ የሚቀጥለውን ዙር ይጠብቁ።'},
    )
    return

  user_id = data.get('user_id')
  card_id = data.get('card_id')
  try:
    card_id = int(card_id)
  except:
    pass

  card_price = 10.00
  if user_id not in user_balances:
    user_balances[user_id] = 50.00

  if user_balances[user_id] < card_price:
    emit('error_msg', {'msg': 'በቂ ባላንስ የለዎትም! እባክዎ ሂሳብ ይሙሉ።'})
    return

  if card_id in taken_cards_global:
    emit(
        'error_msg',
        {'msg': 'ይህ ካርቴላ አስቀድሞ በሌላ ተጫዋች ተይዟል!'},
    )
    return

  user_balances[user_id] -= card_price
  taken_cards_global.append(card_id)
  sold_cards_in_round.append({'user_id': user_id, 'card_id': card_id})

  matrix = generate_bingo_matrix(card_id)

  emit(
      'balance_update',
      {'user_id': user_id, 'balance': user_balances[user_id]},
      room=request.sid,
  )
  emit(
      'card_confirmed',
      {
          'card_id': card_id,
          'matrix': matrix,
          'new_balance': user_balances[user_id],
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

        letter = (
            'B'
            if 1 <= ball <= 15
            else (
                'I'
                if 16 <= ball <= 30
                else (
                    'N'
                    if 31 <= ball <= 45
                    else ('G' if 46 <= ball <= 60 else 'O')
                )
            )
        )
        display_str = f'{letter}-{ball}'

        socketio.emit('new_number', {'ball': ball, 'display': display_str})
        socketio.emit('number_drawn', {'number': ball})
        socketio.sleep(3)

      socketio.sleep(3)
    except Exception as e:
      print('Background Game Loop Error:', e)
      socketio.sleep(1)


@socketio.on('claim_bingo')
def handle_claim_bingo(data):
  global game_active
  user_id = data.get('user_id')
  card_id = data.get('card_id')
  board = data.get('board')

  if check_bingo_win(board):
    game_active = False
    total_pool = len(sold_cards_in_round) * 10.00
    prize = max(total_pool * 0.90, 8)
    user_balances[user_id] = user_balances.get(user_id, 50.00) + prize

    send_telegram_notification(
        f'🏆 *ቢንጎ አሸናፊ ተገኘ!*\n- ተጫዋች ID: `{user_id}`\n- ሽልማት: {prize} ብር'
    )

    matrix = generate_bingo_matrix(card_id)
    socketio.emit(
        'winner_announced',
        {
            'winner_name': f'ተጫዋች {user_id}',
            'winner_ids': [user_id],
            'prize': prize,
            'card_id': card_id,
            'card_matrix': matrix,
        },
    )
    socketio.emit(
        'balance_update', {'user_id': user_id, 'balance': user_balances[user_id]}
    )
    socketio.sleep(6)
    reset_game_state_completely()
  else:
    emit('error_msg', {'msg': '❌ ቢንጎ አልተሟላም!'})


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
  socketio.run(app, host='0.0.0.0', port=port)
