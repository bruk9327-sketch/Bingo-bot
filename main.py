import os
import logging
from flask import Flask, Response
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# --- 1. WEB SERVER FOR MINI APP ---
app = Flask(__name__)

@app.route('/')
def serve_miniapp():
    if os.path.exists('index.html'):
        with open('index.html', 'r', encoding='utf-8') as f:
            content = f.read()
        return Response(content, mimetype='text/html')
    return "index.html file not found!", 404

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- 2. CONFIGURATION & DATABASE ---
BOT_TOKEN = "8623843462:AAH8Wx0gTOj9Fb6kSm63zTo-SBjwuPJuRUM"  # <--- የቦት ቶከንዎን እዚህ ያስገቡ
ADMIN_ID =855985673          # <--- የእርስዎን Telegram User ID እዚህ ያስገቡ
WEB_APP_URL = "https://bingo-bot-c90r.onrender.com"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# የተጫዋቾች ባላንስ መመዝገቢያ (Memory Database)
user_balances = {} # {user_id: balance}

def get_balance(user_id):
    return user_balances.get(user_id, 0.0)

def update_balance(user_id, amount):
    current = get_balance(user_id)
    user_balances[user_id] = max(0.0, current + amount)
    return user_balances[user_id]

# --- 3. COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_balances:
        user_balances[user_id] = 0.0

    welcome_text = (
        f"ሰላም {update.effective_user.first_name}! 👋\n\n"
        f"እንኳን ወደ **GoodBingo** በሰላም መጡ! 🎉\n\n"
        f"💰 **የእርስዎ አሁናዊ ባላንስ፦** `{get_balance(user_id):.2f} ETB`\n\n"
        f"ለመጫወት ከታች ያለውን `/play` ይጫኑ።"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_balance(user_id)
    
    keyboard = [
        [InlineKeyboardButton("🎮 PLAY | 10 ብር", web_app=WebAppInfo(url=f"{WEB_APP_URL}?room=10&bal={bal}"))],
        [InlineKeyboardButton("🚀 SuperBingo | 50 ብር", web_app=WebAppInfo(url=f"{WEB_APP_URL}?room=50&bal={bal}"))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"🕹️ **የጨዋታ ክፍል ይምረጡ፦**\n\n"
        f"💰 የእርስዎ ባላንስ፦ `{bal:.2f} ETB`"
    )
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_balance(user_id)
    await update.message.reply_text(f"💰 **የእርስዎ አሁናዊ ባላንስ፦** `{bal:.2f} ETB`", parse_mode='Markdown')

async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = (
        "💳 **ብር ገቢ ማድረጊያ (Deposit)**\n\n"
        "ወደ አካውንትዎ ብር ለማስገባት በሚከተሉት የከፈያ አማራጮች ገቢ ያድርጉ፦\n\n"
        "📱 **Telebirr:** `0912345678` (GoodBingo)\n"
        "🏦 **CBE Bank:** `1000123456789` (GoodBingo)\n\n"
        "📌 **ማሳሰቢያ፦** ብር ገቢ ካደረጉ በኋላ ደረሰኙን (Transaction Screenshot/ID) እና የእርስዎን ID ከታች ለተጠቀሰው አድሚን ይላኩ።\n\n"
        f"🆔 **የእርስዎ User ID፦** `{user_id}`\n"
        "👤 **አድሚን፦** @GoodBingoSupport"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_balance(user_id)
    
    if bal < 50:
        await update.message.reply_text("⚠️ **ዝቅተኛው ማውጣት የሚችሉት መጠን 50 ETB ነው!**", parse_mode='Markdown')
        return

    text = (
        "🏧 **ብር ማውጫ (Withdraw)**\n\n"
        f"💰 የሚወጣው ባላንስ፦ `{bal:.2f} ETB`\n\n"
        "ብር ለማውጣት በሚከተለው ቅርጸት ይጻፉልን፦\n"
        "`/request_withdraw <የብር መጠን> <የቴሌብር ቁጥር>`\n\n"
        "**ምሳሌ፦** `/request_withdraw 100 0911223344`"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

async def request_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_balance(user_id)

    try:
        amount = float(context.args[0])
        phone = context.args[1]

        if amount > bal:
            await update.message.reply_text("❌ **በቂ ባላንስ የለዎትም!**", parse_mode='Markdown')
            return
        if amount < 50:
            await update.message.reply_text("❌ **ዝቅተኛው የማውጫ መጠን 50 ETB ነው!**", parse_mode='Markdown')
            return

        # ባላንሱን ጊዜያዊ መቀነስ
        update_balance(user_id, -amount)

        # ለአድሚኑ ማስታወቂያ መላክ
        admin_msg = (
            "🚨 **አዲስ የብር ማውጫ ጥያቄ!**\n\n"
            f"👤 **ተጫዋች፦** {update.effective_user.first_name} (@{update.effective_user.username})\n"
            f"🆔 **User ID፦** `{user_id}`\n"
            f"💵 **መጠን፦** `{amount} ETB`\n"
            f"📱 **የቴሌብር ቁጥር፦** `{phone}`"
        )
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode='Markdown')

        await update.message.reply_text("✅ **የማውጣት ጥያቄዎ ለአድሚን ተልኳል። በቅርብ ጊዜ ገቢ ይደረግልዎታል።**", parse_mode='Markdown')

    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ **እባክዎ በትክክለኛው ቅጽ ይጻፉ!**\nምሳሌ፦ `/request_withdraw 100 0911223344`", parse_mode='Markdown')

# --- 4. ADMIN COMMANDS ---
async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return

    try:
        target_user_id = int(context.args[0])
        amount = float(context.args[1])

        new_bal = update_balance(target_user_id, amount)

        # ለተጫዋቹ ማስታወቅያ መላክ
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"🎉 **አካውንትዎ ላይ `{amount} ETB` ገቢ ሆኗል!**\n💰 አሁናዊ ባላንስ፦ `{new_bal:.2f} ETB`",
            parse_mode='Markdown'
        )
        await update.message.reply_text(f"✅ ለተጫዋች ID `{target_user_id}` መጠን `{amount} ETB` ገቢ ተደርጓል።", parse_mode='Markdown')

    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ **የአጠቃቀም ስህተት!**\nቅጽ፦ `/addbalance <user_id> <amount>`", parse_mode='Markdown')

# --- 5. MAIN FUNCTION ---
def main():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("play", play))
    application.add_handler(CommandHandler("balance", balance_cmd))
    application.add_handler(CommandHandler("deposit", deposit))
    application.add_handler(CommandHandler("withdraw", withdraw))
    application.add_handler(CommandHandler("request_withdraw", request_withdraw))
    
    # Admin commands
    application.add_handler(CommandHandler("addbalance", add_balance))
    
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
