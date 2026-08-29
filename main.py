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

socketio = SocketIO(app, cors_allowed_origins='*', async_mode='eventlet')

# ---------------------------------------------------------
# የቴሌግራም ቦት ማስተካከያ (Telegram Bot Configurations)
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get(
    'TELEGRAM_BOT_TOKEN', '8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM'
)
TELEGRAM_ADMIN_CHAT_ID = os.environ.get(
    'TELEGRAM_ADMIN_CHAT_ID', '8912812512'
)


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


# ዳታቤዝ እና የጨዋታ ሁኔታዎች (Memory Storage)
user_balances = {}
taken_cards_global = []
game_timer = 15
game_active = False
sold_cards_in_round = []
user_cards_mapping = {}  # {user_id: [card_ids]}
cards_data_mapping = {}  # {card_id: matrix}
drawn_balls = []
available_numbers = list(range(1, 76))
registered_users_db = []
pending_deposits = {}
deposit_id_counter = 1


@socketio.on('connect')
def handle_connect():
  user_id = request.args.get('user_id')
  my_cards = []
  if user_id:
    try:
      user_id = int(user_id)
    except:
      pass
    my_cards = user_cards_mapping.get(user_id, [])

  emit('update_selected_cards', {
      'taken_cards': taken_cards_global,
      'my_cards': my_cards,
      'cards_data': cards_data_mapping
  })
  emit(
      'timer_update',
      {'time_left': game_timer, 'sold_count': len(sold_cards_in_round)},
  )


@socketio.on('get_taken_cards')
def handle_get_taken_cards():
  # ተጠቃሚው ሲጠይቅ የያዛቸውን ካርቴላዎች እና የተያዙትን ሁሉ መላክ
  user_id = request.args.get('user_id')
  my_cards = []
  emit('update_selected_cards', {
      'taken_cards': taken_cards_global,
      'cards_data': cards_data_mapping
  })


@socketio.on('select_card')
def handle_select_card(data):
  global game_active, taken_cards_global, sold_cards_in_round
  if game_active:
    emit('error_msg', {'msg': 'ጨዋታው ተጀምሯል! እባክዎ የሚቀጥለውን ዙር ይጠብቁ።'})
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
    emit('error_msg', {'msg': 'ይህ ካርቴላ አስቀድሞ በሌላ ተጫዋች ተይዟል!'})
    return

  user_balances[user_id] -= card_price
  taken_cards_global.append(card_id)
  sold_cards_in_round.append({'user_id': user_id, 'card_id': card_id})

  if user_id not in user_cards_mapping:
    user_cards_mapping[user_id] = []
  if card_id not in user_cards_mapping[user_id]:
    user_cards_mapping[user_id].append(card_id)

  matrix = generate_bingo_matrix(card_id)
  cards_data_mapping[card_id] = matrix

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
  socketio.emit('update_selected_cards', {
      'taken_cards': taken_cards_global,
      'cards_data': cards_data_mapping
  })
  socketio.emit(
      'timer_update',
      {'time_left': game_timer, 'sold_count': len(sold_cards_in_round)},
  )


@socketio.on('deselect_card')
def handle_deselect_card(data):
  global game_active, taken_cards_global, sold_cards_in_round
  if game_active:
    emit('error_msg', {'msg': 'ጨዋታው ተጀምሯል! ካርቴላ መሰረዝ አይቻልም።'})
    return

  user_id = data.get('user_id')
  card_id = data.get('card_id')
  try:
    card_id = int(card_id)
  except:
    pass

  if user_id in user_cards_mapping and card_id in user_cards_mapping[user_id]:
    user_cards_mapping[user_id].remove(card_id)
    if card_id in taken_cards_global:
      taken_cards_global.remove(card_id)
    
    # 10 ብር ተመላሽ ማድረግ
    user_balances[user_id] = user_balances.get(user_id, 50.00) + 10.00
    
    # ከsold_cards_in_round ማስወገድ
    sold_cards_in_round[:] = [s for s in sold_cards_in_round if not (s['user_id'] == user_id and s['card_id'] == card_id)]

    emit('balance_update', {'user_id': user_id, 'balance': user_balances[user_id]})
    socketio.emit('update_selected_cards', {
        'taken_cards': taken_cards_global,
        'cards_data': cards_data_mapping
    })
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
  global game_timer, game_active, taken_cards_global, sold_cards_in_round, drawn_balls, available_numbers, user_cards_mapping, cards_data_mapping
  while True:
    try:
      game_active = False
      game_timer = 15
      taken_cards_global = []
      sold_cards_in_round = []
      user_cards_mapping = {}
      cards_data_mapping = {}
      drawn_balls = []
      available_numbers = list(range(1, 76))

      socketio.emit('reset_game', {})

      while game_timer > 0:
        socketio.emit(
            'timer_update',
            {'time_left': game_timer, 'sold_count': len(sold_cards_in_round)},
        )
        time.sleep(1)
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

        letter = ''
        if 1 <= ball <= 15:
          letter = 'B'
        elif 16 <= ball <= 30:
          letter = 'I'
        elif 31 <= ball <= 45:
          letter = 'N'
        elif 46 <= ball <= 60:
          letter = 'G'
        elif 61 <= ball <= 75:
          letter = 'O'

        display_str = f'{letter}-{ball}'
        # ሁለቱንም የኢቨንት ስሞች ለፍሮንትኤንድ እንልካለን
        socketio.emit('new_number', {'ball': ball, 'display': display_str})
        socketio.emit('number_drawn', {'number': ball})
        time.sleep(4)

      time.sleep(5)
    except Exception as e:
      print('Background Game Loop Error:', e)
      time.sleep(1)


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
        f'🏆 *ቢንጎ አሸናፊ ተገኘ!*\n- ተጫዋች ID: `{user_id}`\n- ያሸነፈው ሽልማት: {prize}'
        f' ብር\n- ካርቴላ ቁጥር: {card_id}'
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

    threading.Thread(target=reset_game_state_delayed, daemon=True).start()
    emit(
        'balance_update', {'user_id': user_id, 'balance': user_balances[user_id]}
    )
  else:
    emit(
        'error_msg',
        {'msg': '❌ ቢንጎ አልተሟላም! እባክዎ በትክክል የተጠሩትን ቁጥሮች ይጫኑ።'},
    )


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


def reset_game_state_delayed():
  time.sleep(6)
  reset_game_state_completely()


def reset_game_state_completely():
  global game_timer, game_active, taken_cards_global, sold_cards_in_round, drawn_balls, available_numbers
  taken_cards_global = []
  sold_cards_in_round = []
  drawn_balls = []
  available_numbers = list(range(1, 76))
  game_timer = 15
  game_active = False
  socketio.emit('reset_game', {})


@socketio.on('get_user_balance')
def handle_get_balance(data):
  user_id = data.get('user_id')
  if not user_id:
    return
  if user_id not in user_balances:
    user_balances[user_id] = 50.00
  emit(
      'balance_update', {'user_id': user_id, 'balance': user_balances[user_id]}
  )


@socketio.on('request_deposit')
def handle_request_deposit(data):
  global deposit_id_counter
  try:
    user_id = data.get('user_id')
    amount = float(data.get('amount', 0))
    tx_ref = data.get('tx_ref')
    method = data.get('method', 'CBE Merchant')

    if not user_id or not amount or not tx_ref:
      emit('error_msg', {'msg': 'እባክዎ የዲፖዚት መረጃውን ሙሉ በሙሉ ይሙሉ።'}, room=request.sid)
      return

    dep_id = deposit_id_counter
    deposit_id_counter += 1

    pending_deposits[dep_id] = {
        'id': dep_id,
        'user_id': user_id,
        'amount': amount,
        'transaction_ref': tx_ref,
        'method': method,
        'status': 'Pending',
    }

    admin_msg = (
        f'💰 *አዲስ የCBE Merchant ዲፖዚት ጥያቄ*\n\n'
        f'- ጥያቄ ID: `{dep_id}`\n'
        f'- ተጠቃሚ ID: `{user_id}`\n'
        f'- መጠን: *{amount} ብር*\n'
        f'- Ref/TID: `{tx_ref}`'
    )

    inline_keyboard = {
        'inline_keyboard': [[
            {'text': '✅ አረጋግጥ (Approve)', 'callback_data': f'approve_dep_{dep_id}'},
            {'text': '❌ ሰርዝ (Reject)', 'callback_data': f'reject_dep_{dep_id}'},
        ]]
    }

    send_telegram_notification(admin_msg, reply_markup=inline_keyboard)
    emit('deposit_success', {'msg': 'የዲፖዚት ጥያቄዎ በተሳካ ሁኔታ ተልኳል!', 'new_balance': user_balances.get(user_id, 50)}, room=request.sid)
  except Exception as e:
    print('Deposit Error:', e)


@app.route('/')
def index():
  return render_template('index.html')


@app.route('/admin')
def admin_panel():
  return render_template('admin.html')


if __name__ == '__main__':
  t = threading.Thread(target=background_game_loop, daemon=True)
  t.start()

  port = int(os.environ.get('PORT', 10000))
  socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
