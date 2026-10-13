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
from sqlalchemy import func
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

taken_cards_global = []
game_timer = 15
game_active = False
sold_cards_in_round = []
drawn_balls = []
available_numbers = list(range(1, 76))

OTP_STORAGE = {}


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


def start_background_loop():
    t = threading.Thread(target=background_game_loop, daemon=True)
    t.start()

start_background_loop()


class User(db.Model):
  __tablename__ = 'users'
  id = db.Column(db.Integer, primary_key=True)
  user_id = db.Column(db.String(100), unique=True, nullable=False)
  phone = db.Column(db.String(50), nullable=True)
  username = db.Column(db.String(100), nullable=True)
  full_name = db.Column(db.String(150), nullable=True)
  email = db.Column(db.String(120), nullable=True)
  password = db.Column(db.String(255), nullable=True)
  balance = db.Column(db.Float, default=0.00)
  is_active = db.Column(db.Boolean, default=True)
  is_suspended = db.Column(db.Boolean, default=False)
  kyc_verified = db.Column(db.Boolean, default=False)


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
  account = db.Column(db.String(100), nullable=True)
  method = db.Column(db.String(50), nullable=True)
  status = db.Column(db.String(20), default='pending')
  created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PasswordResetRequest(db.Model):
    __tablename__ = 'password_reset_requests'
    id = db.Column(db.Integer, primary_key=True)
    user_identifier = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SupportTicket(db.Model):
    __tablename__ = 'support_tickets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), nullable=True)
    full_name = db.Column(db.String(150), nullable=True)
    username = db.Column(db.String(100), nullable=True)
    subject = db.Column(db.String(200), nullable=True)
    message = db.Column(db.Text, nullable=False)
    attachment = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default='Pending')
    admin_reply = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class VerifiedSMSReceipt(db.Model):
    __tablename__ = 'verified_sms_receipts'
    id = db.Column(db.Integer, primary_key=True)
    transaction_ref = db.Column(db.String(100), unique=True, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    sender_phone = db.Column(db.String(50), nullable=True)
    sms_text = db.Column(db.Text, nullable=False)
    received_at = db.Column(db.DateTime, default=datetime.utcnow)


with app.app_context():
    db.create_all()
    try:
        db.session.execute(sa.text('ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;'))
        db.session.execute(sa.text('ALTER TABLE users ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN DEFAULT FALSE;'))
        db.session.execute(sa.text('ALTER TABLE users ADD COLUMN IF NOT EXISTS kyc_verified BOOLEAN DEFAULT FALSE;'))
        db.session.execute(sa.text('ALTER TABLE transactions ADD COLUMN IF NOT EXISTS account VARCHAR(100);'))
        db.session.execute(sa.text('ALTER TABLE transactions ADD COLUMN IF NOT EXISTS method VARCHAR(50);'))
        
        db.session.execute(sa.text('ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS full_name VARCHAR(150);'))
        db.session.execute(sa.text('ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS username VARCHAR(100);'))
        db.session.execute(sa.text('ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS subject VARCHAR(200);'))
        db.session.execute(sa.text('ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS admin_reply TEXT;'))
        
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print("Column migration notice:", e)


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
  emit(
      'timer_update',
      {'time_left': game_timer, 'sold_count': len(sold_cards_in_round)},
  )
  
  if game_active:
      total_pool = len(sold_cards_in_round) * 10.00
      derash = total_pool * 0.90
      
      emit('game_started', {'derash': derash})
      
      for ball in drawn_balls:
          emit('number_drawn', {'number': ball})
          
      emit('sync_sold_cards', {'sold_cards': sold_cards_in_round})


@socketio.on('login_user')
def handle_login_user(data):
  identifier = str(data.get('identifier') or '').strip()
  password = str(data.get('password') or '').strip()

  if not identifier or not password:
    emit('auth_response', {'success': False, 'msg': 'እባክዎ መግቢያ መረጃዎን ሙሉ በሙሉ ይሙሉ!'}, room=request.sid)
    return

  user = User.query.filter(
      sa.or_(
          User.email == identifier,
          User.phone == identifier,
          User.username == identifier,
          User.user_id == identifier
      )
  ).first()

  if user and user.password == password:
    if user.is_suspended:
      emit('auth_response', {'success': False, 'msg': 'አካውንትዎ ታግዷል!'}, room=request.sid)
      return
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
    existing = User.query.filter(
        sa.or_(
            User.email == email,
            User.phone == phone,
            User.user_id == user_id,
            User.username == username
        )
    ).first()
    
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
        balance=0.00,
        is_active=True,
        is_suspended=False,
        kyc_verified=False
    )
    db.session.add(user)
    db.session.commit()

    emit('auth_response', {
        'success': True,
        'msg': 'ምዝገባው በተሳካ ሁኔታ ተጠናቋል። ለመጫወት እባክዎ ቢያንስ 20 ብር ዲፖዚት ያድርጉ!',
        'user_id': user.user_id,
        'balance': user.balance,
        'full_name': user.full_name
    }, room=request.sid)

  except Exception as e:
    db.session.rollback()
    emit('auth_response', {'success': False, 'msg': f'ስህተት ተፈጥሯል: {str(e)}'}, room=request.sid)


@socketio.on('send_otp_request')
def handle_send_otp_request(data):
    identity = str(data.get('identity') or '').strip()
    if not identity:
        emit('otp_sent_response', {'success': False, 'msg': 'እባክዎ ትክክለኛ መለያ ያስገቡ!'}, room=request.sid)
        return

    user = User.query.filter(
        sa.or_(
            User.email == identity,
            User.phone == identity,
            User.username == identity,
            User.user_id == identity
        )
    ).first()

    if not user:
        emit('otp_sent_response', {'success': False, 'msg': 'ይህ መለያ በሲስተሙ ውስጥ አልተገኘም!'}, room=request.sid)
        return

    otp_code = str(random.randint(100000, 999999))
    OTP_STORAGE[identity] = {
        'otp': otp_code,
        'expires': time.time() + 300
    }

    admin_msg = (
        f"🔐 *የይለፍ ቃል ማግኛ OTP ጥያቄ*\n\n"
        f"- ተጠቃሚ: `{identity}`\n"
        f"- የ OTP ኮድ: *`{otp_code}`*\n"
        f"- (ለ 5 ደቂቃ ብቻ ያገለግላል)"
    )
    send_telegram_notification(admin_msg)

    emit('otp_sent_response', {'success': True, 'msg': 'የማረጋገጫ ኮድ (OTP) ተልኳል። እባክዎ ኮዱን ያስገቡ።'}, room=request.sid)


@socketio.on('verify_otp_and_reset')
def handle_verify_otp_and_reset(data):
    identity = str(data.get('identity') or '').strip()
    otp = str(data.get('otp') or '').strip()
    new_password = str(data.get('new_password') or '').strip()

    if not identity or not otp or not new_password:
        emit('password_reset_response', {'success': False, 'msg': 'እባክዎ መረጃውን ሙሉ በሙሉ ይሙሉ!'}, room=request.sid)
        return

    stored_data = OTP_STORAGE.get(identity)
    if not stored_data:
        emit('password_reset_response', {'success': False, 'msg': 'እባክዎ መጀመሪያ የኮድ ጥያቄ ይላኩ!'}, room=request.sid)
        return

    if time.time() > stored_data['expires']:
        emit('password_reset_response', {'success': False, 'msg': 'የ OTP ኮዱ ጊዜው አልፎበታል! እባክዎ እንደገና ይሞክሩ።'}, room=request.sid)
        return

    if stored_data['otp'] != otp:
        emit('password_reset_response', {'success': False, 'msg': 'ያስገቡት የ OTP ኮድ ስህተት ነው!'}, room=request.sid)
        return

    user = User.query.filter(
        sa.or_(
            User.email == identity,
            User.phone == identity,
            User.username == identity,
            User.user_id == identity
        )
    ).first()

    if not user:
        emit('password_reset_response', {'success': False, 'msg': 'ተጠቃሚው አልተገኘም!'}, room=request.sid)
        return

    user.password = new_password
    db.session.commit()
    del OTP_STORAGE[identity]

    emit('password_reset_response', {'success': True, 'msg': 'የይለፍ ቃልዎ በተሳካ ሁኔታ ተቀይሯል! አሁን በአዲሱ የይለፍ ቃልዎ መግባት ይችላሉ።'}, room=request.sid)


@app.route('/api/submit-support', methods=['POST'])
def api_submit_support():
    try:
        data = request.get_json() or request.form
        full_name = data.get('full_name') or data.get('name') or 'ያልታወቀ'
        username = data.get('username') or 'N/A'
        subject = data.get('subject') or data.get('issue_type') or 'የድጋፍ ጥያቄ'
        message = data.get('message') or ''
        user_id = data.get('user_id') or session.get('user_id') or 'guest'

        if not message:
            return jsonify({'success': False, 'message': 'እባክዎ መልዕክትዎን ይጻፉ!'}), 400

        ticket = SupportTicket(
            user_id=str(user_id),
            full_name=full_name,
            username=username,
            subject=subject,
            message=message,
            status='Pending'
        )
        db.session.add(ticket)
        db.session.commit()

        admin_msg = (
            f"🎧 *አዲስ የድጋፍ ጥያቄ (Support Ticket # {ticket.id})*\n\n"
            f"- **ስም:** {full_name}\n"
            f"- **ዩዘርኔም:** `{username}`\n"
            f"- **ርዕስ:** {subject}\n"
            f"- **መልዕክት:** {message}"
        )
        send_telegram_notification(admin_msg)

        return jsonify({'success': True, 'message': 'የድጋፍ ጥያቄዎ በተሳካ ሁኔታ ተልኳል!'}), 200
    except Exception as e:
        db.session.rollback()
        print("Support Submission Error:", e)
        return jsonify({'success': False, 'message': 'የሲስተም ስህተት አጋጥሟል!'}), 500


@socketio.on('submit_support_ticket')
def handle_submit_support_ticket(data):
    try:
        user_id = str(data.get('user_id') or session.get('user_id') or 'guest')
        full_name = data.get('full_name') or 'ያልታወቀ'
        username = data.get('username') or 'N/A'
        issue_type = data.get('issue_type') or 'የድጋፍ ጥያቄ'
        message = data.get('message')

        if not message:
            return

        ticket = SupportTicket(
            user_id=user_id,
            full_name=full_name,
            username=username,
            subject=issue_type,
            message=message,
            status='Pending'
        )
        db.session.add(ticket)
        db.session.commit()

        admin_msg = (
            f"🎧 *አዲስ የድጋፍ ጥያቄ (Support Ticket # {ticket.id})*\n\n"
            f"- **ስም:** {full_name}\n"
            f"- **ዩዘርኔም:** `{username}`\n"
            f"- **ርዕስ:** {issue_type}\n"
            f"- **መልዕክት:** {message}"
        )
        send_telegram_notification(admin_msg)
        emit('support_response', {'success': True, 'msg': 'ጥያቄዎ ገብቷል!'}, room=request.sid)
    except Exception as e:
        db.session.rollback()
        print("Support Ticket Error:", e)


@app.route('/admin/support', methods=['GET'])
def admin_support():
    if not session.get('is_admin') and not session.get('admin_logged'):
        return redirect(url_for('admin_login'))
        
    try:
        tickets = SupportTicket.query.order_by(SupportTicket.id.desc()).all()
    except Exception as e:
        print("Support route error:", e)
        tickets = []
        
    return render_template('admin_support.html', tickets=tickets)


@app.route('/admin/support/<int:ticket_id>/reply', methods=['POST'])
def admin_support_reply(ticket_id):
    if not session.get('is_admin') and not session.get('admin_logged'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
    data = request.get_json() or {}
    reply_text = data.get('admin_reply')
    
    try:
        ticket = SupportTicket.query.get(ticket_id)
        if not ticket:
            return jsonify({'success': False, 'message': 'ጥያቄው አልተገኘም'})
            
        ticket.admin_reply = reply_text
        ticket.status = 'Answered'
        db.session.commit()

        socketio.emit('support_reply_received', {
            'ticket_id': ticket.id,
            'user_id': ticket.user_id,
            'reply': reply_text
        })

        return jsonify({'success': True, 'message': 'ምላሹ በተሳካ ሁኔታ ተልኳል!'})
    except Exception as e:
        db.session.rollback()
        print("Support reply error:", e)
        return jsonify({'success': False, 'message': 'የዳታቤዝ ስህተት አጋጥሟል!'}), 500


@app.route('/api/my-support-tickets', methods=['GET'])
def get_user_support_tickets():
    user_id = request.args.get('user_id') or session.get('user_id')
    if not user_id:
        return jsonify({'tickets': []})

    tickets = SupportTicket.query.filter_by(user_id=str(user_id)).order_by(SupportTicket.id.desc()).all()
    result = [{
        'id': t.id,
        'subject': t.subject,
        'message': t.message,
        'status': t.status,
        'admin_reply': t.admin_reply,
        'created_at': t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else ''
    } for t in tickets]

    return jsonify({'tickets': result})


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
    tid_match = re.search(r'(?:Txn ID|TID)\s*[:=]?\s*([A-Za-z0-9]{8,15})', sms_text, re.IGNORECASE)
    if tid_match:
      return tid_match.group(1).upper()
      
    general_match = re.search(r'\b([A-Z0-9]{10,15})\b', sms_text)
    if general_match:
      return general_match.group(1).upper()
      
    return None
  except Exception as e:
    return None


def extract_amount_from_sms(sms_text):
  try:
    amount_match = re.search(r'([\d,]+\.\d{2})\s*(?:Br|ETB|ብር|Birr)?', sms_text, re.IGNORECASE)
    if amount_match:
      cleaned_amt = amount_match.group(1).replace(',', '')
      return float(cleaned_amt)
    return 0.0
  except:
    return 0.0


def extract_sender_phone(sms_text):
  try:
    phone_match = re.search(r'(09\d{8}|2519\d{8}|2517\d{8})', sms_text)
    if phone_match:
      return phone_match.group(1)
    return None
  except:
    return None


@app.route('/api/receive-sms', methods=['POST'])
def receive_sms():
    try:
        data = request.get_json() or {}
        sender = data.get('sender', '')
        message = data.get('message', '')
        
        print(f"Received SMS from {sender}: {message}")
        
        if "BIRUK RETA" not in message and "BIRUK RETA DARGE" not in message and "you received" not in message.lower():
            print("Ignored SMS: Not a valid merchant transaction receipt.")
            return "ignored - not merchant", 200

        tid = extract_transaction_info(message)
        amount = extract_amount_from_sms(message)
        sender_phone = extract_sender_phone(message)
        
        if tid and amount > 0:
            existing_sms = VerifiedSMSReceipt.query.filter_by(transaction_ref=tid).first()
            if not existing_sms:
                verified_receipt = VerifiedSMSReceipt(
                    transaction_ref=tid,
                    amount=amount,
                    sender_phone=sender_phone,
                    sms_text=message
                )
                db.session.add(verified_receipt)
                db.session.commit()
            
        return "success", 200
    except Exception as e:
        print("Webhook Error:", str(e))
        return "error", 500


@socketio.on('request_deposit')
def handle_request_deposit(data):
  try:
    user_id = str(data.get('user_id'))
    user_entered_amount = float(data.get('amount', 0))
    sms_text = data.get('sms_text', '')
    tx_ref = data.get('tx_ref') or data.get('transaction_ref') or ''
    tx_ref = tx_ref.strip().upper()
    method = data.get('method', 'Telebirr/CBE Merchant')

    if not user_id or user_entered_amount <= 0 or not sms_text:
      emit('deposit_response', {'status': 'error', 'message': '⚠️ እባክዎ ሙሉ መረጃ እና የኤስኤምኤስ ደረሰኝ በትክክል ይሙሉ!'}, room=request.sid)
      return

    extracted_tid = extract_transaction_info(sms_text) or tx_ref
    extracted_amount = extract_amount_from_sms(sms_text)

    if not extracted_tid:
      emit('deposit_response', {'status': 'error', 'message': '❌ የተሳሳተ ወይም ያልተረጋገጠ ደረሰኝ ነው! (TID አልተገኘም)'}, room=request.sid)
      return

    if extracted_tid in PROCESSED_TIDS or Deposit.query.filter_by(transaction_ref=extracted_tid, status='Approved').first():
      emit('deposit_response', {'status': 'error', 'message': '❌ ይህ የክፍያ ደረሰኝ (TID) ከዚህ በፊት ጥቅም ላይ ውሏል! (Duplicate Receipt)'}, room=request.sid)
      return

    verified_sms = VerifiedSMSReceipt.query.filter_by(transaction_ref=extracted_tid).first()
    
    if verified_sms:
      if float(verified_sms.amount) != float(user_entered_amount):
        emit('deposit_response', {'status': 'error', 'message': f'❌ የገባው የብር መጠን ({user_entered_amount} ብር) ከትክክለኛው የደረሰኝ መጠን ({verified_sms.amount} ብር) ጋር አይዛመድም!'}, room=request.sid)
        return
      actual_amount = verified_sms.amount
    else:
      if extracted_amount > 0 and float(extracted_amount) != float(user_entered_amount):
        emit('deposit_response', {'status': 'error', 'message': f'❌ የገባው የብር መጠን ከደረሰኙ መጠን ጋር አይዛመድም!'}, room=request.sid)
        return
      actual_amount = user_entered_amount if user_entered_amount > 0 else extracted_amount

    if actual_amount <= 0:
      emit('deposit_response', {'status': 'error', 'message': '❌ የተሳሳተ የገንዘብ መጠን!'}, room=request.sid)
      return

    PROCESSED_TIDS.add(extracted_tid)

    user = User.query.filter_by(user_id=user_id).first()
    if not user:
      emit('deposit_response', {'status': 'error', 'message': 'ተጠቃሚው አልተገኘም!'}, room=request.sid)
      return

    user.balance = float(user.balance) + float(actual_amount)

    deposit = Deposit(
        user_id=user_id,
        amount=actual_amount,
        transaction_ref=extracted_tid,
        sms_text=sms_text,
        method=method,
        status='Approved',
    )
    db.session.add(deposit)
    
    tx_record = Transaction(
        user_id=user_id,
        type='deposit',
        amount=actual_amount,
        status='completed'
    )
    db.session.add(tx_record)
    db.session.commit()

    send_telegram_notification(f"✅ *አውቶማቲክ ዲፖዚት ጸደቀ*\n- ተጠቃሚ: `{user_id}`\n- መጠን: *{actual_amount} ብር*\n- TID: `{extracted_tid}`")

    emit('balance_update', {'user_id': user_id, 'balance': float(user.balance)}, room=request.sid)
    emit(
        'deposit_response',
        {
            'status': 'success',
            'message': f'🎉 የ {actual_amount} ብር ዲፖዚትዎ በትክክል ተረጋግጦ አካውንትዎ ላይ ተጨምሯል!',
            'dep_id': deposit.id,
        },
        room=request.sid,
    )
  except Exception as e:
    db.session.rollback()
    print('Deposit Validation Error:', e)
    emit('deposit_response', {'status': 'error', 'message': '⚠️ የክፍያ ማረጋገጫ ሲስተም ስህተት አጋጥሟል!'}, room=request.sid)


@socketio.on('request_withdrawal')
def handle_request_withdrawal(data):
  try:
    user_id = str(data.get('user_id'))
    amount = float(data.get('amount', 0))
    account = str(data.get('account') or '').strip()
    method = str(data.get('method') or 'Telebirr').strip()

    if not user_id or not account:
      emit('withdrawal_response', {'success': False, 'msg': '⚠️ እባክዎ የሂሳብ/ስልክ ቁጥር በትክክል ይሙሉ!'}, room=request.sid)
      return

    if amount < 100.00:
      emit('withdrawal_response', {'success': False, 'msg': '⚠️ ዝቅተኛው የማውጣት መጠን 100 ብር እና ከዚያ በላይ መሆን አለበት!'}, room=request.sid)
      return

    user = User.query.filter_by(user_id=user_id).first()
    if not user:
      emit('withdrawal_response', {'success': False, 'msg': '⚠️ ተጠቃሚው አልተገኘም!'}, room=request.sid)
      return

    if float(user.balance) < amount:
      emit('withdrawal_response', {'success': False, 'msg': f'⚠️ በቂ ቀሪ ሂሳብ የለዎትም! (ያሎት: {user.balance} ETB)'}, room=request.sid)
      return

    tx_record = Transaction(
        user_id=user_id,
        type='withdrawal',
        amount=amount,
        account=account,
        method=method,
        status='pending'
    )
    db.session.add(tx_record)
    db.session.commit()

    admin_msg = (
        f"📤 *አዲስ የገንዘብ ማውጣት (Withdrawal) ጥያቄ*\n\n"
        f"- ጥያቄ ID: `{tx_record.id}`\n"
        f"- ተጠቃሚ ID: `{user_id}`\n"
        f"- ስም: {user.full_name or 'N/A'}\n"
        f"- መጠን: *{amount} ብር*\n"
        f"- ዘዴ: {method}\n"
        f"- አካውንት/ስልክ: `{account}`"
    )
    send_telegram_notification(admin_msg)

    emit('withdrawal_response', {
        'success': True, 
        'msg': f'📤 የ {amount} ብር የዊዝድሮ ጥያቄዎ በተሳካ ሁኔታ ተልኳል! አድሚኑ ሲያረጋግጠው አካውንትዎ ይለቀቃል።'
    }, room=request.sid)

  except Exception as e:
    db.session.rollback()
    print("Withdrawal Request Error:", e)
    emit('withdrawal_response', {'success': False, 'msg': '⚠️ የሲስተም ስህተት አጋጥሟል!'}, room=request.sid)


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

  user = User.query.filter_by(user_id=user_id).first()
  if not user:
    emit('error_msg', {'msg': 'ተጠቃሚው አልተገኘም!'}, room=request.sid)
    return

  if float(user.balance) < 20.00:
    emit('error_msg', {'msg': '⚠️ ለመጫወት ቢያንስ 20 ብር እና ከዚያ በላይ ዲፖዚት ማድረግ አለብዎት!'}, room=request.sid)
    return

  card_price = 10.00
  if float(user.balance) < card_price:
    emit('error_msg', {'msg': 'በቂ ባላንስ የለዎትም!'}, room=request.sid)
    return

  if card_id in taken_cards_global:
    emit('error_msg', {'msg': 'ይህ ካርቴላ ተይዟል!'}, room=request.sid)
    return

  user.balance = float(user.balance) - card_price
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
      balance = float(prize_amount)
      full_name = f'ተጫዋች {user_id}'

    send_telegram_notification(f'🏆 *ቢንጎ አሸናፊ ተገኘ!*\n- ተጫዋች ID: `{user_id}`')
    matrix = generate_bingo_matrix(card_id)
    
    emit('balance_update', {'user_id': user_id, 'balance': float(balance)}, room=request.sid)
    socketio.emit('winner_announced', {'winner_name': full_name, 'prize': prize_amount, 'card_id': card_id, 'card_matrix': matrix})


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
  except Exception:
    pass
  return False


@app.route('/')
def index():
  return render_template('index.html')


@app.route('/admin', methods=['GET'])
def admin_dashboard():
    if not session.get('is_admin') and not session.get('admin_logged'):
        return redirect(url_for('admin_login'))
    
    try:
        total_users = User.query.count() or 0
        active_users = User.query.filter_by(is_active=True).count() or 0
        
        revenue_result = db.session.query(func.sum(Transaction.amount)).filter(
            sa.or_(Transaction.type == 'deposit', Transaction.status == 'completed'),
            Transaction.status != 'rejected'
        ).scalar()
        total_revenue = float(revenue_result or 0.0)

        withdrawal_result = db.session.query(func.sum(Transaction.amount)).filter(
            Transaction.type == 'withdrawal',
            Transaction.status == 'completed'
        ).scalar()
        total_withdrawals = float(withdrawal_result or 0.0)
        
        total_profit = total_revenue * 0.25 
        
        pending_deposits = Deposit.query.filter_by(status='Pending').all()
        pending_withdrawals = Transaction.query.filter_by(type='withdrawal', status='pending').all()
        
        password_resets = PasswordResetRequest.query.order_by(PasswordResetRequest.id.desc()).all()
    except Exception as e:
        print("Admin Dashboard Error:", e)
        total_users = 0
        active_users = 0
        total_revenue = 0.0
        total_withdrawals = 0.0
        total_profit = 0.0
        pending_deposits = []
        pending_withdrawals = []
        password_resets = []
    
    return render_template(
        'admin.html', 
        total_users=total_users,
        active_users=active_users,
        total_revenue=total_revenue,
        total_withdrawals=total_withdrawals,
        total_profit=total_profit, 
        pending_deposits=pending_deposits, 
        pending_withdrawals=pending_withdrawals, 
        password_resets=password_resets
    )


@app.route('/admin/users', methods=['GET'])
def admin_users():
    if not session.get('is_admin') and not session.get('admin_logged'):
        return redirect(url_for('admin_login'))
    
    status_filter = request.args.get('status', 'all')
    query = User.query
    
    if status_filter == 'active':
        query = query.filter_by(is_active=True)
    elif status_filter == 'suspended':
        query = query.filter_by(is_suspended=True)
    elif status_filter == 'kyc':
        query = query.filter_by(kyc_verified=True)
        
    users = query.all()
    return render_template('admin_users.html', users=users, current_filter=status_filter)


@app.route('/admin/users/<user_id>/update-status', methods=['POST'])
def admin_update_user_status(user_id):
    if not session.get('is_admin') and not session.get('admin_logged'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
    data = request.get_json() or {}
    new_status = data.get('status')
    
    user = User.query.filter_by(id=user_id).first() or User.query.filter_by(user_id=user_id).first()
    if not user:
        return jsonify({'success': False, 'message': 'ተጠቃሚው አልተገኘም'})
        
    if new_status == 'suspended':
        user.is_suspended = True
        user.is_active = False
    elif new_status == 'active':
        user.is_suspended = False
        user.is_active = True
    elif new_status == 'kyc_verify':
        user.kyc_verified = True
        
    db.session.commit()
    return jsonify({'success': True, 'message': 'የተጠቃሚው ስታተስ ተዘምኗል!'})


@app.route('/admin/password-reset/<int:req_id>/action', methods=['POST'])
def admin_password_reset_action(req_id):
    if not session.get('is_admin') and not session.get('admin_logged'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
    data = request.get_json() or {}
    action = data.get('action')
    
    req_item = PasswordResetRequest.query.get(req_id)
    if not req_item:
        return jsonify({'success': False, 'message': 'ጥያቄው አልተገኘም'})
        
    if action == 'resolve':
        req_item.status = 'Resolved'
        db.session.commit()
        return jsonify({'success': True, 'message': 'ጥያቄው ተጠናቋል!'})
    elif action == 'delete':
        db.session.delete(req_item)
        db.session.commit()
        return jsonify({'success': True, 'message': 'ጥያቄው ተሰርዟል!'})
        
    return jsonify({'success': False, 'message': 'ልክ ያልሆነ እርምጃ'})


@app.route('/admin/transaction/<int:tx_id>/action', methods=['POST'])
def admin_transaction_action(tx_id):
    if not session.get('is_admin') and not session.get('admin_logged'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
    data = request.get_json() or {}
    action = data.get('action') or request.form.get('action')
    
    tx = Transaction.query.get(tx_id)
    if not tx:
        return jsonify({'success': False, 'message': 'ትራንዛክሽኑ አልተገኘም'})
        
    user = User.query.filter_by(user_id=tx.user_id).first()

    if action == 'approve' or action == 'complete':
        if tx.type == 'withdrawal':
            if not user:
                return jsonify({'success': False, 'message': 'ተጠቃሚው አልተገኘም'})
            if float(user.balance) < float(tx.amount):
                return jsonify({'success': False, 'message': 'ተጠቃሚው በቂ ባላንስ የለውም!'})
            
            user.balance = float(user.balance) - float(tx.amount)
            tx.status = 'completed'
            
            socketio.emit('balance_update', {'user_id': user.user_id, 'balance': float(user.balance)})
            send_telegram_notification(f"✅ *ዊዝድሮ ጥያቄ ጸደቀ*\n- ተጠቃሚ: `{user.user_id}`\n- የተወጣው መጠን: *{tx.amount} ብር*")

        elif tx.type == 'deposit':
            tx.status = 'completed'
            if user:
                user.balance = float(user.balance) + float(tx.amount)
                socketio.emit('balance_update', {'user_id': user.user_id, 'balance': float(user.balance)})

        db.session.commit()
        return jsonify({'success': True, 'message': 'ትራንዛክሽኑ ጸድቋል!'})

    elif action == 'reject' or action == 'delete':
        tx.status = 'rejected'
        db.session.commit()
        return jsonify({'success': True, 'message': 'ትራንዛክሽኑ ተሰርዟል!'})
        
    return jsonify({'success': False, 'message': 'ልክ ያልሆነ እርምጃ'})


# ==========================================
# 📢 አድሚን ብሮድካስት እና ፑሽ ኖቲፊኬሽን (Broadcast API Endpoint)
# ==========================================
@app.route('/admin/broadcast', methods=['POST'])
def admin_broadcast_api():
    if not session.get('is_admin') and not session.get('admin_logged'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    message = request.form.get('message')
    media_file = request.files.get('media')

    if not message:
        return jsonify({'success': False, 'message': 'እባክዎ የመልዕክት ጽሁፍ ያስገቡ!'}), 400

    try:
        # ለሁሉም የተገናኙ ዌብሶኬት ተጠቃሚዎች ኖቲፊኬሽን መላክ
        socketio.emit('receive_broadcast', {'text': message})

        # ለቴሌግራም ቦት ተጠቃሚዎች ፎቶ፣ ቪዲዮ ወይም ጽሁፍ በብሮድካስት መልክ መላክ
        if TELEGRAM_BOT_TOKEN != '8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM':
            all_users = User.query.all()
            for u in all_users:
                try:
                    chat_id = u.user_id
                    if media_file:
                        filename = media_file.filename.lower()
                        if filename.endswith(('.mp4', '.mov', '.avi')):
                            requests.post(
                                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo",
                                data={'chat_id': chat_id, 'caption': message, 'parse_mode': 'Markdown'},
                                files={'video': media_file.read()}
                            )
                        else:
                            requests.post(
                                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                                data={'chat_id': chat_id, 'caption': message, 'parse_mode': 'Markdown'},
                                files={'photo': media_file.read()}
                            )
                        media_file.seek(0)
                    else:
                        requests.post(
                            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                            json={'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown'}
                        )
                except Exception as ex:
                    print(f"Telegram broadcast error for user: {ex}")

        return jsonify({'success': True, 'message': 'ብሮድካስቱ በተሳካ ሁኔታ ተልኳል!'}), 200
    except Exception as e:
        print("Broadcast Route Error:", e)
        return jsonify({'success': False, 'message': 'የብሮድካስት ስህተት አጋጥሟል!'}), 500


# ==========================================
# 🚪 አድሚን Sign Out (Logout Route)
# ==========================================
@app.route('/admin/logout', methods=['GET'])
def admin_logout():
    session.pop('admin_logged', None)
    session.pop('is_admin', None)
    flash('ከአድሚን ፓነል ውጣዋል!', 'success')
    return redirect(url_for('admin_login'))


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
            error_msg = 'የተሳሳተ መግቢያ ስም ወይም የይለፍ ቃል!'
            
    render_template_obj = render_template('admin_login.html', error_msg=error_msg)
    return render_template_obj


if __name__ == '__main__':
  port = int(os.environ.get('PORT', 10000))
  socketio.run(app, host='0.0.0.0', port=port)
