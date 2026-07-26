import os
import re
import logging
from flask import Flask, Response, request, jsonify
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# --- 1. FLASK WEB SERVER ---
app = Flask(__name__)

@app.route('/')
def serve_miniapp():
    if os.path.exists('index.html'):
        with open('index.html', 'r', encoding='utf-8') as f:
            return Response(f.read(), mimetype='text/html')
    return "index.html file not found!", 404

# API to sync balance from WebApp to Telegram Bot
@app.route('/api/sync-balance', methods=['POST'])
def sync_balance():
    data = request.json
    user_id = data.get('user_id')
    new_balance = data.get('balance')
    
    if user_id and new_balance is not None:
        try:
            user_balances[int(user_id)] = float(new_balance)
        except:
            user_balances[str(user_id)] = float(new_balance)
        return jsonify({"status": "success", "balance": new_balance})
    return jsonify({"status": "error"}), 400

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- 2. CONFIG & DATABASE ---
BOT_TOKEN = "8623843462:AAH8Wx0gTOj9Fb6kSm63zTo-SBjwuPJuRUM"  # <-- የቦት ቶከንዎን እዚህ ያስገቡ
WEB_APP_URL = "https://bingo-bot-c90r.onrender.com"  # <-- የ Render URLዎን ያስገቡ

logging.basicConfig(level=logging.INFO)

user_balances = {}
user_states = {}
used_txns = set()

def get_balance(user_id):
    return user_balances.get(user_id, 30.0)

def update_balance(user_id, amount):
    curr = get_balance(user_id)
    user_balances[user_id] = max(0.0, curr + amount)
    return user_balances[user_id]

# --- 3. BOT COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_balances:
        user_balances[user_id] = 30.0

    caption = (
        "🎉 **Ethio Bingo For All** : 💰 **36 ሺህ** 🎉\n\n"
        "📅 ዘወትር ቅዳሜ እና እሁድ ⏰ 10 ሰዓት\n"
        "🎫 ካርቴላ ሳይልቅ ⏳ ቀድመው ይያዙ 🏃\n\n"
        "❓ ማንኛውም ጥያቄ ካለ፦\n"
        "📞 **0914657021**\n"
        "👉 @EthioBingoSupport"
    )
    
    keyboard = [
        [InlineKeyboardButton("🎮 PLAY | ጨዋታ ጀምር", callback_data="btn_play")],
        [InlineKeyboardButton("💳 DEPOSIT | ብር አስገባ", callback_data="btn_deposit")]
    ]
    await update.message.reply_text(caption, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def play_cmd(update_or_query, user_id):
    bal = get_balance(user_id)
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

async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await play_cmd(update, update.effective_user.id)

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = "AWAITING_WITHDRAWAL_AMOUNT"
    text = (
        "📥 *ገንዘብ ያውጡ (Withdraw Funds)*\n"
        "እባክዎ የሚያወጡትን የገንዘብ መጠን ያስገቡ:"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

# --- 4. HANDLERS ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "btn_play":
        await play_cmd(query, query.from_user.id)
    elif query.data == "btn_deposit":
        keyboard = [
            [InlineKeyboardButton("CBE BIRR", callback_data="dep_cbe"), InlineKeyboardButton("TELE BIRR", callback_data="dep_tele")]
        ]
        await query.message.reply_text("💳 **የማስገቢያ መንገድ ይምረጡ፦**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == "dep_cbe":
        await query.message.reply_text("📍 **የ CBE-Birr / ባንክ ቁጥር፦** `0991983522`\nብር ገቢ ካደረጉ በኋላ የደረሰኝ SMS ወይም Txn ID እዚሁ ይላኩት።", parse_mode='Markdown')
    elif query.data == "dep_tele":
        await query.message.reply_text("📲 **የ Telebirr ቁጥር፦** `0991983522`\nብር ገቢ ካደረጉ በኋላ የደረሰኝ SMS Copy አድርገው እዚሁ ይላኩት።", parse_mode='Markdown')

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if user_states.get(user_id) == "AWAITING_WITHDRAWAL_AMOUNT":
        if text.isdigit():
            amt = float(text)
            if amt < 100:
                await update.message.reply_text("❌ **ከፍተኛ/ዝቅተኛ ገደብ፦** አነስተኛው የማውጫ መጠን 100 ብር ነው።", parse_mode='Markdown')
            else:
                bal = get_balance(user_id)
                if amt > bal:
                    await update.message.reply_text("❌ **በቂ ያልሆነ ሂሳብ!**", parse_mode='Markdown')
                else:
                    update_balance(user_id, -amt)
                    user_states[user_id] = None
                    await update.message.reply_text(f"✅ የ {amt:.2f} ETB ማውጣት ጥያቄዎ ተልኳል! ቀሪ ሂሳብ፦ {get_balance(user_id):.2f} ETB", parse_mode='Markdown')
            return

    # Auto-Deposit Logic
    txn_match = re.search(r'Txn ID\s+([A-Z0-9]+)', text, re.IGNORECASE)
    amt_match = re.search(r'paid\s+([\d\.]+)\s*Br', text, re.IGNORECASE)

    if txn_match and amt_match:
        txn_id = txn_match.group(1)
        amount = float(amt_match.group(1))

        if txn_id in used_txns:
            await update.message.reply_text("❌ ይህ ደረሰኝ ቀደም ብሎ ጥቅም ላይ ውሏል!")
            return

        used_txns.add(txn_id)
        new_bal = update_balance(user_id, amount)
        await update.message.reply_text(f"✅ **ክፍያዎ ተረጋግጧል!**\n\n➕ የተጨመረ፦ `{amount:.2f} ETB`\n💰 አዲስ ባላንስ፦ `{new_bal:.2f} ETB`", parse_mode='Markdown')

# --- MAIN ENGINE ---
def main():
    Thread(target=run_flask, daemon=True).start()
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("play", play))
    bot_app.add_handler(CommandHandler("withdraw", withdraw))
    bot_app.add_handler(CallbackQueryHandler(button_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    
    bot_app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
