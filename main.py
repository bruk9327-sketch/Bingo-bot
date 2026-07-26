import os
import re
import sqlite3
import logging
from flask import Flask, Response, request, jsonify
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# --- 1. SQLITE DATABASE SETUP (ቋሚ የባላንስ ማከማቻ) ---
DB_FILE = "bingo_data.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0.0,
            referrals INTEGER DEFAULT 0,
            referred_by INTEGER
        )
    ''')
    # Used Txns table (የውሸት ደረሰኝ/ድግግሞሽ መከላከያ)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS used_txns (
            txn_id TEXT PRIMARY KEY
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def db_get_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT balance, referrals FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, balance, referrals) VALUES (?, 0.0, 0)", (user_id,))
        conn.commit()
        conn.close()
        return 0.0, 0
    conn.close()
    return row[0], row[1]

def db_update_balance(user_id, amount):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, balance, referrals) VALUES (?, 0.0, 0)", (user_id,))
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    new_bal = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return new_bal

def db_add_referral(referrer_id, new_user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Check if already referred
    cursor.execute("SELECT referred_by FROM users WHERE user_id = ?", (new_user_id,))
    row = cursor.fetchone()
    
    if not row or row[0] is None:
        cursor.execute("INSERT OR IGNORE INTO users (user_id, balance, referrals) VALUES (?, 0.0, 0)", (new_user_id,))
        cursor.execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer_id, new_user_id))
        cursor.execute("INSERT OR IGNORE INTO users (user_id, balance, referrals) VALUES (?, 0.0, 0)", (referrer_id,))
        cursor.execute("UPDATE users SET referrals = referrals + 1 WHERE user_id = ?", (referrer_id,))
        
        cursor.execute("SELECT referrals FROM users WHERE user_id = ?", (referrer_id,))
        ref_count = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        return True, ref_count
    
    conn.close()
    return False, 0

def db_is_txn_used(txn_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT txn_id FROM used_txns WHERE txn_id = ?", (txn_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def db_mark_txn_used(txn_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO used_txns (txn_id) VALUES (?)", (txn_id,))
    conn.commit()
    conn.close()

# --- 2. FLASK WEB SERVER ---
app = Flask(__name__)

@app.route('/')
def serve_miniapp():
    if os.path.exists('index.html'):
        with open('index.html', 'r', encoding='utf-8') as f:
            return Response(f.read(), mimetype='text/html')
    return "index.html file not found!", 404

@app.route('/api/sync-balance', methods=['POST'])
def sync_balance():
    data = request.json
    user_id = data.get('user_id')
    new_balance = data.get('balance')
    
    if user_id and new_balance is not None:
        try:
            uid = int(user_id)
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (float(new_balance), uid))
            conn.commit()
            conn.close()
            return jsonify({"status": "success", "balance": new_balance})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 400
    return jsonify({"status": "error"}), 400

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- 3. CONFIG ---
BOT_TOKEN = "8623843462:AAH8Wx0gTOj9Fb6kSm63zTo-SBjwuPJuRUM"          # <-- የቦት ቶከንዎን ያስገቡ
BOT_USERNAME = "BKBingoHousebot"           # <-- የቦት Username
WEB_APP_URL = "https://bingo-bot-c90r.onrender.com"
ADMIN_CHAT_ID = 855985673                  # <-- ⚠️ የራስዎን Telegram User ID ያስገቡ

logging.basicConfig(level=logging.INFO)
pending_deposits = {}   # In-memory storage for pending button actions

# --- 4. BOT COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    bal, ref_count = db_get_user(user_id)

    if args and len(args) > 0:
        ref_payload = args[0]
        if ref_payload.startswith("ref_"):
            try:
                referrer_id = int(ref_payload.replace("ref_", ""))
                if user_id != referrer_id:
                    success, count = db_add_referral(referrer_id, user_id)
                    if success:
                        try:
                            if count >= 10:
                                await context.bot.send_message(
                                    chat_id=referrer_id,
                                    text="🎉 **እንኳን ደስ አለዎት!** 10 ሰዎችን ስለጋበዙ ጨዋታው ተከፍቶልዎታል። 🎮"
                                )
                            else:
                                await context.bot.send_message(
                                    chat_id=referrer_id,
                                    text=f"👤 **አዲስ ሰው ተቀላቅሏል!**\n\nየጋበዟቸው ተጫዋቾች፦ `{count}/10`"
                                )
                        except Exception as e:
                            logging.error(f"Failed referrer notify: {e}")
            except ValueError:
                pass

    caption = (
        "🎉 **Ethio Bingo For All** 🎉\n\n"
        "⚠️ **ማሳሰቢያ፦** ጨዋታ ለመጫወት ቢያንስ **10 ሰዎችን** መጋበዝ አለብዎት!\n\n"
        "📞 Support: @EthioBingoSupport"
    )
    
    inline_keyboard = [
        [InlineKeyboardButton("🎮 PLAY | ጨዋታ ጀምር", callback_data="btn_play")],
        [InlineKeyboardButton("🔗 10 ሰው ጋብዝ (Invite)", callback_data="btn_invite")],
        [InlineKeyboardButton("💳 DEPOSIT | ብር አስገባ", callback_data="btn_deposit")]
    ]
    
    reply_keyboard = [
        ["🎮 የቢንጎ ጨዋታ ይክፈቱ (Mini App)"],
        ["💰 ባላንስ", "🔗 የኔ መጋበዣ ሊንክ", "📋 ደንቦች"]
    ]
    reply_markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)

    await update.message.reply_text(caption, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(inline_keyboard))
    await update.message.reply_text("👇 ከታች ያሉትን በተኖች ይጠቀሙ፦", reply_markup=reply_markup)

# 👑 ለአድሚን ብቻ፡ በእጅ ብር መጨምሪያ Command (/addbalance USER_ID AMOUNT)
async def add_balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    
    try:
        target_uid = int(context.args[0])
        amt = float(context.args[1])
        new_bal = db_update_balance(target_uid, amt)
        await update.message.reply_text(f"✅ ለ ተጫዋች `{target_uid}` የ `{amt} ETB` ሂሳብ ተጨምሯል።\nአዲስ ባላንስ፦ `{new_bal:.2f} ETB`", parse_mode='Markdown')
        
        try:
            await context.bot.send_message(
                chat_id=target_uid,
                text=f"🎉 **የሂሳብ ማስተካከያ!**\n\n➕ የተጨመረ፦ `{amt:.2f} ETB`\n💰 አዲስ ባላንስ፦ `{new_bal:.2f} ETB`",
                parse_mode='Markdown'
            )
        except:
            pass
    except Exception as e:
        await update.message.reply_text("❌ አጠቃቀም፦ `/addbalance <USER_ID> <AMOUNT>`\nምሳሌ፦ `/addbalance 987654321 200`", parse_mode='Markdown')

async def send_invite_info(update_or_query, user_id):
    _, ref_count = db_get_user(user_id)
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    status_icon = "✅" if ref_count >= 10 else "⏳"
    
    text = (
        f"🔗 **የመጋበዣ ሊንክዎ (Referral Link)**\n\n"
        f"`{ref_link}`\n\n"
        f"📊 **የእርሶ የግብዣ ሁኔታ፦** `{ref_count}/10` {status_icon}\n"
    )
    
    share_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 ለጓደኞች ሼር አድርግ", url=f"https://t.me/share/url?url={ref_link}&text=ና%20በቴሌግራም%20ቢንጎ%20ተጫውተን%20እንሸልም!")]
    ])

    if hasattr(update_or_query, 'message'):
        await update_or_query.message.reply_text(text, parse_mode='Markdown', reply_markup=share_button)
    else:
        await update_or_query.edit_message_text(text, parse_mode='Markdown', reply_markup=share_button)

async def play_cmd(update_or_query, user_id):
    bal, ref_count = db_get_user(user_id)
    
    if ref_count < 10:
        error_text = (
            f"🔒 **ጨዋታው አልተከፈተም!**\n\n"
            f"ጨዋታ ለመጫወት 10 ሰዎችን መጋበዝ አለብዎት።\n"
            f"እስካሁን የጋበዟቸው፦ `{ref_count}/10`"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 አሁኑኑ ጋብዝ", callback_data="btn_invite")]])
        if hasattr(update_or_query, 'message'):
            await update_or_query.message.reply_text(error_text, parse_mode='Markdown', reply_markup=keyboard)
        else:
            await update_or_query.edit_message_text(error_text, parse_mode='Markdown', reply_markup=keyboard)
        return

    keyboard = [
        [InlineKeyboardButton("🎮 PLAY | 10 ብር", web_app=WebAppInfo(url=f"{WEB_APP_URL}?room=10&bal={bal}&uid={user_id}"))],
        [InlineKeyboardButton("🚀 ሳምንታዊ እድል | 50 ብር", web_app=WebAppInfo(url=f"{WEB_APP_URL}?room=50&bal={bal}&uid={user_id}"))],
        [InlineKeyboardButton("⚽ Ethio Bingo Bonus | 100 ብር", web_app=WebAppInfo(url=f"{WEB_APP_URL}?room=100&bal={bal}&uid={user_id}"))]
    ]
    text = f"Choose a room to join the game:\n\n💰 **ቀሪ ሂሳብዎ፦** `{bal:.2f} ETB`"
    
    if hasattr(update_or_query, 'message'):
        await update_or_query.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update_or_query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

# --- 5. HANDLERS ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "btn_play":
        await play_cmd(query, query.from_user.id)
    elif data == "btn_invite":
        await send_invite_info(query, query.from_user.id)
    elif data == "btn_deposit":
        keyboard = [[InlineKeyboardButton("CBE BIRR", callback_data="dep_cbe"), InlineKeyboardButton("TELE BIRR", callback_data="dep_tele")]]
        await query.message.reply_text("💳 **የማስገቢያ መንገድ ይምረጡ፦**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "dep_cbe":
        await query.message.reply_text("📍 **የ CBE-Birr / ባንክ ቁጥር፦** `0991983522`\nብር ገቢ ካደረጉ በኋላ የደረሰኝ SMS ወይም Txn ID እዚሁ ይላኩት።", parse_mode='Markdown')
    elif data == "dep_tele":
        await query.message.reply_text("📲 **የ Telebirr ቁጥር፦** `0991983522`\nብር ገቢ ካደረጉ በኋላ የደረሰኝ SMS Copy አድርገው እዚሁ ይላኩት።", parse_mode='Markdown')

    # 👨‍ገቢዎች አድሚን ማጽደቂያ (Admin Approval)
    elif data.startswith("app_") or data.startswith("rej_"):
        if query.from_user.id != ADMIN_CHAT_ID:
            await query.answer("❌ ለእርሶ የተፈቀደ አይደለም!", show_alert=True)
            return

        parts = data.split("_")
        action = parts[0]
        txn_id = parts[1]
        target_uid = int(parts[2]) if len(parts) > 2 else None

        dep_info = pending_deposits.get(txn_id, {})
        amount = dep_info.get('amount', 200.0) # Default 200 if not detected

        if action == "app":
            if target_uid:
                new_bal = db_update_balance(target_uid, amount)
                db_mark_txn_used(txn_id)
                if txn_id in pending_deposits:
                    del pending_deposits[txn_id]

                await query.edit_message_text(f"✅ **ጽድቋል!**\n\nለ User `{target_uid}` የ `{amount:.2f} ETB` ሂሳብ በቋሚነት ተጨምሯል።\nአዲስ ባላንስ፦ `{new_bal:.2f} ETB`", parse_mode='Markdown')
                
                try:
                    await context.bot.send_message(
                        chat_id=target_uid,
                        text=f"🎉 **ክፍያዎ ጸድቋል!**\n\n➕ የተጨመረ፦ `{amount:.2f} ETB`\n💰 አዲስ ባላንስ፦ `{new_bal:.2f} ETB`",
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logging.error(f"Failed user notify: {e}")

        elif action == "rej":
            if txn_id in pending_deposits:
                del pending_deposits[txn_id]
            await query.edit_message_text(f"❌ **ውድቅ ተደርጓል!**", parse_mode='Markdown')

            if target_uid:
                try:
                    await context.bot.send_message(
                        chat_id=target_uid,
                        text=f"❌ **ክፍያዎ ውድቅ ተደርጓል!**\n\nየላኩት ደረሰኝ/Txn ID አልተረጋገጠም።",
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logging.error(f"Failed user notify: {e}")

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""
    
    if text in ["💰 ባላንስ", "ባላንስ", "/balance"]:
        bal, ref_count = db_get_user(user_id)
        await update.message.reply_text(f"💳 **የአሁኑ ቀሪ ሂሳብዎ፦** `{bal:.2f} ETB`\n👥 **የተጋበዙ ሰዎች፦** `{ref_count}/10`", parse_mode='Markdown')
        return

    if text in ["🔗 የኔ መጋበዣ ሊንክ", "መጋበዣ ሊንክ", "/invite"]:
        await send_invite_info(update, user_id)
        return

    if text in ["📋 ደንቦች", "ደንቦች"]:
        rules_text = (
            "📋 **የ Ethio Bingo ደንቦች፦**\n\n"
            "1. ጨዋታ ለመጀመር ቢያንስ 10 አዳዲስ ተጫዋቾችን መጋበዝ አለብዎት።\n"
            "2. የመጀመሪያ ባላንስዎ 0.00 ETB ነው።\n"
            "3. የሚያስገቡት ክፍያ በአድሚን ከተረጋገጠ በኋላ ባላንስዎ ላይ ይጨመራል።"
        )
        await update.message.reply_text(rules_text, parse_mode='Markdown')
        return

    if "የቢንጎ ጨዋታ" in text:
        await play_cmd(update, user_id)
        return

    # SMS Regex Detection
    txn_match = re.search(r'Txn\s*ID\s*[:\-]?\s*([A-Z0-9]+)', text, re.IGNORECASE)
    amt_match = re.search(r'([\d\.]+)\s*(?:Br|ETB)', text, re.IGNORECASE)

    txn_id = txn_match.group(1) if txn_match else f"TXN_{user_id}_{int(update.message.date.timestamp())}"
    amount = float(amt_match.group(1)) if amt_match else 200.0

    if db_is_txn_used(txn_id):
        await update.message.reply_text("❌ ይህ ደረሰኝ/Txn ID ቀደም ብሎ ጥቅም ላይ ውሏል!")
        return

    pending_deposits[txn_id] = {'user_id': user_id, 'amount': amount}

    await update.message.reply_text("⏳ **ክፍያዎ ለግምገማ ተልኳል!** አድሚኑ ደረሰኙን አጣርቶ እንደጨረሰ ባላንስዎ ላይ ይጨመራል።", parse_mode='Markdown')

    admin_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ አጽድቅ (Approve)", callback_data=f"app_{txn_id}_{user_id}"),
            InlineKeyboardButton("❌ ውድቅ አድርግ (Reject)", callback_data=f"rej_{txn_id}_{user_id}")
        ]
    ])
    
    user_name = update.effective_user.full_name
    admin_msg = (
        f"🚨 **አዲስ የክፍያ ጥያቄ!**\n\n"
        f"👤 **ተጫዋች:** {user_name} (ID: `{user_id}`)\n"
        f"💰 **የተገመተ መጠን:** `{amount:.2f} ETB`\n"
        f"🧾 **Txn ID:** `{txn_id}`\n\n"
        f"📝 **የላከው መልእክት:**\n_{text}_"
    )
    
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, parse_mode='Markdown', reply_markup=admin_keyboard)
    except Exception as e:
        logging.error(f"Failed to alert admin: {e}")

async def handle_document_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.full_name
    txn_id = f"DOC_{user_id}_{int(update.message.date.timestamp())}"
    
    pending_deposits[txn_id] = {'user_id': user_id, 'amount': 200.0}

    await update.message.reply_text("⏳ **ደረሰኝዎ ለግምገማ ተልኳል!** አድሚኑ አጣርቶ ያጸድቅሎታል።")

    admin_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ አጽድቅ (Approve)", callback_data=f"app_{txn_id}_{user_id}"),
            InlineKeyboardButton("❌ ውድቅ አድርግ (Reject)", callback_data=f"rej_{txn_id}_{user_id}")
        ]
    ])

    admin_msg = f"🚨 **አዲስ የደረሰኝ ፋይል ተልኳል!**\n👤 **ተጫዋች:** {user_name} (ID: `{user_id}`)"

    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg)
        await update.message.forward(chat_id=ADMIN_CHAT_ID)
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text="👇 ማጽደቂያ በተኖች፦", reply_markup=admin_keyboard)
    except Exception as e:
        logging.error(f"Failed to forward doc: {e}")

# --- MAIN ENGINE ---
def main():
    Thread(target=run_flask, daemon=True).start()
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("addbalance", add_balance_cmd)) # Admin Add Balance Command
    bot_app.add_handler(CallbackQueryHandler(button_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    bot_app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document_messages))
    
    bot_app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
