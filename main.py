from datetime import datetime
import os
import random
import threading
import time
import requests
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'bkbingo_secret_key_2026'

# ከፊት ለፊት ካለው (Frontend) ጋር ሙሉ በሙሉ እንዲጣጣም async_mode='threading' እንጠቀማለን
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

# ---------------------------------------------------------
# የቴሌግራም ቦት ማስተካከያ (Telegram Bot Configurations)
# ከ Render ወይም ከ Environment Variables ማንበብ እንዲችል ተደርጓል
# ---------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get(
    'TELEGRAM_BOT_TOKEN', '8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM'
)
TELEGRAM_ADMIN_CHAT_ID = os.environ.get(
    'TELEGRAM_ADMIN_CHAT_ID', '8912812512'
)


def send_telegram_notification(message, reply_markup=None):
  """የቴሌግራም ቦትን ተጠቅሞ መልዕክት ወደ አድሚን ወይም ቻናል ለመላክ (ከነ ቁልፎቹ)"""
  if TELEGRAM_BOT_TOKEN == '8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM':
    return  # ቶክኑ ካልተሞላ ዝም ይላል
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
  """ለተወሰነ ቻት ID የቴሌግራም መልዕክት ለመላክ"""
  if TELEGRAM_BOT_TOKEN == '8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM':
    return
  url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
  payload = {'chat_id': chat_id, 'text': text}
  try:
    requests.post(url, json=payload, timeout=5)
  except Exception as e:
    print('Telegram Custom Message Error:', e)


# ዳታቤዝ እና የጨዋታ ሁኔታዎች (Memory Storage)
user_balances = {}  # {user_id: balance}
taken_cards_global = []  # በወቅቱ የተያዙ ካርቴላዎች
game_timer = 15  # የሰዓት ቆጣሪ (ሰከንድ)
game_active = False  # ጨዋታው እየተካሄደ መሆኑን ማረጋገጫ
sold_cards_in_round = []  # በዚህ ዙር የተሸጡ ካርቴላዎች
drawn_balls = []  # የወጡ ኳሶች/ቁጥሮች
available_numbers = list(range(1, 76))

# የተጠቃሚዎች ምዝገባ እና አድሚን ዳታ መያዣ
registered_users_db = []

# የዲፖዚት ጥያቄዎች ማከማቻ (In-Memory Deposit Requests DB Simulation)
pending_deposits = {}
deposit_id_counter = 1


# ክላይንት ከሶኬት ጋር ሲገናኝ ወዲያውኑ የካርቴላዎችን ሁኔታ መላክ
@socketio.on('connect')
def handle_connect():
  emit('update_selected_cards', {'taken_cards': taken_cards_global})
  emit(
      'timer_update',
      {'time_left': game_timer, 'sold_count': len(sold_cards_in_round)},
  )


# ተጠቃሚዎችን የመመዝገቢያ ሁነት (Register User)
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
    user_balances[user_id] = 50.00

  emit(
      'registration_success',
      {'msg': 'ምዝገባዎ በተሳካ ሁኔታ ተጠናቋል!', 'user_id': user_id},
      room=request.sid,
  )
  socketio.emit('registered_users_list', {'users': registered_users_db})


# የተመዝጋቢዎችን ዝርዝር ለአድሚን ማሳያ
@socketio.on('get_registered_users')
def handle_get_registered_users(data):
  emit('registered_users_list', {'users': registered_users_db}, room=request.sid)


# ---------------------------------------------------------
# የCBE Merchant / የዲፖዚት ጥያቄ ማቀናበሪያ (Socket.io & API Routes)
# ---------------------------------------------------------

@socketio.on('request_deposit')
def handle_request_deposit(data):
  """ክላይንቱ በሶኬት በኩል የዲፖዚት ጥያቄ ሲልክ የሚቀበል እና ስህተት እንዳይፈጥር (Crash-Free) የሚያደርግ ፋንክሽን"""
  global deposit_id_counter
  try:
    user_id = data.get('user_id')
    amount = float(data.get('amount', 0))
    tx_ref = data.get('tx_ref') or data.get('transaction_ref')
    method = data.get('method', 'CBE Merchant')

    if not user_id or not amount or not tx_ref:
      emit('error_msg', {'msg': 'እባክዎ የዲፖዚት መረጃውን ሙሉ በሙሉ ይሙሉ።'}, room=request.sid)
      return

    if amount < 10:
      emit('error_msg', {'msg': 'ቢያንስ 10 ብር እና ከዚያ በላይ መጫን ይቻላል!'}, room=request.sid)
      return

    # ዲፖዚቱን Pending አድርጎ መመዝገብ
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

    # ለአድሚን በቴሌግራም ማሳወቂያ ከነ አፕሩቭ/ሪጀክት ቁልፎች ጋር መላክ (Consistent callback_data format: approve_dep_ID)
    admin_msg = (
        f'💰 *አዲስ የCBE Merchant ዲፖዚት ጥያቄ (Socket)*\n\n'
        f'- ጥያቄ ID: `{dep_id}`\n'
        f'- ተጠቃሚ ID: `{user_id}`\n'
        f'- መጠን: *{amount} ብር*\n'
        f'- ዘዴ: {method}\n'
        f'- Ref: `{tx_ref}`'
    )

    inline_keyboard = {
        'inline_keyboard': [[
            {'text': '✅ አረጋግጥ (Approve)', 'callback_data': f'approve_dep_{dep_id}'},
            {'text': '❌ ሰርዝ (Reject)', 'callback_data': f'reject_dep_{dep_id}'},
        ]]
    }

    send_telegram_notification(admin_msg, reply_markup=inline_keyboard)

    # ለክላይንት ስኬታማ መሆኑን መላክ
    emit('deposit_pending', {
        'msg': 'የዲፖዚት ጥያቄዎ በተሳካ ሁኔታ ተልኳል! አድሚኑ ሲያረጋግጠው ባላንስዎ ላይ ይጨመራል።',
        'dep_id': dep_id
    }, room=request.sid)

  except Exception as e:
    print(f"Deposit Socket Error: {e}")
    emit('error_msg', {'msg': 'የዲፖዚት ጥያቄውን ማስተናገድ አልተቻለም።'}, room=request.sid)


@app.route('/api/deposit', methods=['POST'])
@app.route('/api/deposit/submit', methods=['POST'])
def api_deposit():
  """የHTTP POST ሪኩዌስት ለሚጠቀሙ ክላይንቶች የዲፖዚት ማስተናገጃ API"""
  global deposit_id_counter
  try:
    data = request.json or request.form or {}
    user_id = data.get('user_id')
    amount = float(data.get('amount', 0))
    tx_ref = data.get('tx_ref') or data.get('transaction_ref')
    method = data.get('method', 'CBE Merchant')

    if not user_id or not amount or not tx_ref:
      return jsonify({'status': 'error', 'msg': 'መረጃው አልተሟላም', 'message': 'መረጃው አልተሟላም'}), 400

    if amount < 10:
      return jsonify({'status': 'error', 'msg': 'ቢያንስ 10 ብር እና ከዚያ በላይ መጫን ይቻላል!', 'message': 'ቢያንስ 10 ብር እና ከዚያ በላይ መጫን ይቻላል!'}), 400

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
        f'💰 *አዲስ የCBE Merchant ዲፖዚት ጥያቄ (API)*\n\n'
        f'- ጥያቄ ID: `{dep_id}`\n'
        f'- ተጠቃሚ ID: `{user_id}`\n'
        f'- መጠን: *{amount} ብር*\n'
        f'- ዘዴ: {method}\n'
        f'- Ref: `{tx_ref}`'
    )

    # አድሚን አપ્રूव ወይም ሪጀክት እንዲያደርግበት የቴሌግራም ኢንላይን ቁልፎች
    inline_keyboard = {
        'inline_keyboard': [[
            {'text': '✅ አረጋግጥ (Approve)', 'callback_data': f'approve_dep_{dep_id}'},
            {'text': '❌ ውድቅ አድርግ (Reject)', 'callback_data': f'reject_dep_{dep_id}'},
        ]]
    }

    send_telegram_notification(admin_msg, reply_markup=inline_keyboard)

    return jsonify({
        'status': 'success',
        'msg': 'የዲፖዚት ጥያቄዎ በተሳካ ሁኔታ ተልኳል!',
        'message': 'የዲፖዚት ጥያቄዎ በተሳካ ሁኔታ ተልኳል!',
        'dep_id': dep_id,
    })
  except Exception as e:
    print('API Deposit Error:', e)
    return jsonify({'status': 'error', 'msg': str(e), 'message': str(e)}), 500


@app.route('/api/admin/action-deposit', methods=['POST'])
def admin_action_deposit():
  """አድሚኑ ከዳሽቦርድ ወይም ሲስተም ክፍያውን ሲያጸድቅ"""
  data = request.json or {}
  deposit_id = int(data.get('deposit_id', 0))
  action = data.get('action')  # 'approve' ወይም 'reject'

  deposit = pending_deposits.get(deposit_id)
  if not deposit:
    return jsonify({'status': 'error', 'message': 'ጥያቄው አልተገኘም'}), 404

  if deposit['status'] != 'Pending':
    return (
        jsonify({
            'status': 'error',
            'message': 'ይህ ጥያቄ ቀድሞ ተስተናግዷል!',
        }),
        400,
    )

  user_id = deposit['user_id']
  amount = deposit['amount']

  if action == 'approve':
    deposit['status'] = 'Approved'
    if user_id not in user_balances:
      user_balances[user_id] = 50.00
    user_balances[user_id] += amount

    # ለተጠቃሚው በሶኬት በኩል ማሳወቅ
    socketio.emit(
        'balance_update',
        {'user_id': user_id, 'balance': user_balances[user_id]},
    )
    socketio.emit(
        'deposit_approved',
        {
            'dep_id': deposit_id,
            'amount': amount,
            'new_balance': user_balances[user_id],
        },
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
        f'🎉 የCBE Merchant ክፍያዎ ጸድቋል! {amount} ብር ወደ አካውንትዎ ተጨምሯል። አዲሱ ባላንስዎ: {user_balances[user_id]} ብር ነው።',
    )

    return (
        jsonify({
            'status': 'success',
            'message': 'ክፍያው ጸድቋል፣ የተጫዋቹ አካውንት ተሞልቷል።',
        }),
        200,
    )

  elif action == 'reject':
    deposit['status'] = 'Rejected'
    send_telegram_custom_message(
        user_id,
        f'❌ የዲፖዚት ጥያቄዎ ({amount} ብር) በአድሚን ውድቅ ተደርጓል። እባክዎን ትክክለኛ መረጃ መላክዎን ያረጋግጡ።',
    )
    return (
        jsonify({'status': 'success', 'message': 'የዲፖዚት ጥያቄው ተሰርዟል።'}),
        200,
    )

  return jsonify({'status': 'error', 'message': 'ትክክለኛው እርምጃ አልተመረጣም'}), 400


# አድሚን ከዳሽቦርድ የሚልካቸውን ማስታወቂያዎች (Broadcast) ለሁሉም ተጫዋቾች ማስተላለፊያ
@socketio.on('send_broadcast')
def handle_send_broadcast(data):
  text = data.get('text')
  media = data.get('media')
  file_type = data.get('type')
  socketio.emit(
      'receive_broadcast', {'text': text, 'media': media, 'type': file_type}
  )


# ተጠቃሚ ሲገባ ባላንስ እና ወቅታዊ ሁኔታዎችን መላክ
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
  emit('update_selected_cards', {'taken_cards': taken_cards_global})
  emit(
      'timer_update',
      {'time_left': game_timer, 'sold_count': len(sold_cards_in_round)},
  )


# ካርቴላ መምረጫ
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


# የሰዓት ቆጣሪ እና የጨዋታ ሉፕ (Background Thread)
def background_game_loop():
  global game_timer, game_active, taken_cards_global, sold_cards_in_round, drawn_balls, available_numbers
  while True:
    try:
      # 1. የሰዓት ቆጣሪ (Countdown phase)
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
        time.sleep(1)
        game_timer -= 1

      # ካርቴላ ካልተገዛ ጨዋታው አይጀምርም, ሰዓቱ እንደገና 15 ሰከንድ ይሆናል
      if len(sold_cards_in_round) == 0:
        continue

      # 2. ጨዋታው ተጀመረ (Playing phase)
      game_active = True
      total_pool = len(sold_cards_in_round) * 10.00
      derash = total_pool * 0.90  # 10% ለቦቱ ኮሚሽን ተቀናሽ ይደረጋል

      socketio.emit('game_started', {'derash': derash})

      random.shuffle(available_numbers)

      for ball in available_numbers:
        if not game_active:
          break

        drawn_balls.append(ball)

        # ኳስ የማውጣት ፎርማት (B-5, I-20 ወዘተ)
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

        socketio.emit('new_number', {'ball': ball, 'display': display_str})
        socketio.emit('number_drawn', {'number': ball})

        time.sleep(4)  # በየ 4 ሰከንዱ አዲስ ኳስ ይወጣል

      time.sleep(5)
    except Exception as e:
      print('Background Game Loop Error:', e)
      time.sleep(1)


# አሸናፊ ማረጋገጫ (Claim Bingo)
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


@app.route('/')
def index():
  return render_template('index.html')


# የአድሚን ዳሽቦርድ ገጽ (Admin Panel Route)
@app.route('/admin')
def admin_panel():
  return render_template('admin.html')


# የቴሌግራም ትዕዛዞችን ለመቀበል የሚረዳ ሩት (Webhook Endpoint)
@app.route('/telegram-webhook', methods=['POST'])
def telegram_webhook():
  global pending_deposits, user_balances
  try:
    data = request.get_json() or {}

    # 1. አድሚኑ በቴሌግራም የቁልፍ ሰሌዳ (Inline Buttons) ሲጫን (Callback Query)
    if 'callback_query' in data:
      query = data['callback_query']
      callback_data = query.get('data', '')
      chat_id = query['message']['chat']['id']
      message_id = query['message']['message_id']

      # Support both approve_dep_ID and approve_ID formats
      if callback_data.startswith('approve_dep_') or callback_data.startswith('reject_dep_') or callback_data.startswith('approve_') or callback_data.startswith('reject_'):
        parts = callback_data.split('_')
        # Handle approve_dep_ID vs approve_ID
        if 'dep' in callback_data:
          action = parts[0]
          dep_id = int(parts[2])
        else:
          action = parts[0]
          dep_id = int(parts[1])

        deposit = pending_deposits.get(dep_id)
        if deposit and deposit['status'] == 'Pending':
          user_id = deposit['user_id']
          amount = deposit['amount']

          if action == 'approve':
            deposit['status'] = 'Approved'
            if user_id not in user_balances:
              user_balances[user_id] = 50.00
            user_balances[user_id] += amount

            # ለተጠቃሚው ማሳወቅ
            socketio.emit(
                'balance_update',
                {'user_id': user_id, 'balance': user_balances[user_id]},
            )
            socketio.emit(
                'deposit_approved',
                {
                    'dep_id': dep_id,
                    'amount': amount,
                    'new_balance': user_balances[user_id],
                },
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
                f'🎉 የCBE Merchant ክፍያዎ ጸድቋል! {amount} ብር ወደ አካውንትዎ ተጨምሯል። አዲሱ ባላንስዎ: {user_balances[user_id]} ብር ነው።',
            )

            response_text = (
                f'✅ *ዲፖዚት ጸድቋል (Approved)*\n- ጥያቄ ID: `{dep_id}`\n- ተጠቃሚ: `{user_id}`\n- መጠን: *{amount} ብር*'
            )
          else:
            deposit['status'] = 'Rejected'
            send_telegram_custom_message(
                user_id,
                f'❌ የዲፖዚት ጥያቄዎ ({amount} ብር) በአድሚን ውድቅ ተደርጓል። እባክዎን ትክክለኛ መረጃ መላክዎን ያረጋግጡ።',
            )
            response_text = (
                f'❌ *ዲፖዚት ውድቅ ተደርጓል (Rejected)*\n- ጥያቄ ID: `{dep_id}`\n- ተጠቃሚ: `{user_id}`\n- መጠን: *{amount} ብር*'
            )

          # በቴሌግራም ላይ የነበረውን መልዕክት ማስተካከል
          try:
            url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText'
            requests.post(
                url,
                json={
                    'chat_id': chat_id,
                    'message_id': message_id,
                    'text': response_text,
                    'parse_mode': 'Markdown',
                },
                timeout=5,
            )
          except Exception as e:
            print('Edit Message Error:', e)

      return jsonify({'status': 'ok'})

    # 2. መደበኛ የጽሁፍ መልዕክቶች ሲመጡ
    if 'message' in data:
      message = data['message']
      chat_id = message['chat']['id']
      text = message.get('text', '')
      user_id = str(message['from']['id'])

      if text.strip() in ['/admin', '/Admin']:
        admin_url = 'https://bingo-bot-c90r.onrender.com/admin'
        send_telegram_custom_message(
            chat_id,
            f'👋 እንኳን ደህና መጡ! (የእርስዎ Telegram ID: {user_id})\nየአድሚን ዳሽቦርዱን ለመክፈት ይህንን ሊንክ ይጠቀሙ:\n{admin_url}',
        )

    return jsonify({'status': 'ok'})
  except Exception as e:
    print('Webhook General Error:', e)
    return jsonify({'status': 'error'}), 500


if __name__ == '__main__':
  # የጀርባ ጨዋታ ሎፔን በሰሬድ ማስጀመር
  t = threading.Thread(target=background_game_loop, daemon=True)
  t.start()

  port = int(os.environ.get('PORT', 10000))
  socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
