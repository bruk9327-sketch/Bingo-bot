import os
import logging
from flask import Flask, Response
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

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
BOT_TOKEN = "8623843462:AAH8Wx0gTOj9Fb6kSm63zTo-SBjwuPJuRUM"  # <--- ቦት ቶከንዎን እዚህ ያስገቡ
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
        user_balances[user_id] = 0.0  # አዲስ ተጫዋች ሲመጣ 0.00 ETB መስጠት

    welcome_text = (
        f"ሰላም {update.effective_user.first_name}! 👋\n\n"
        f"እንኳን ወደ **GoodBingo** በሰላም መጡ! 🎉\n\n"
        f"ለመጫወት `/play` የሚለውን ይጫኑ ወይም ከታች ያለውን ሜኑ ይጠቀሙ።"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # የሩሞች መምረጫ ቁልፎች (ለቀጣዩ Mini App)
    keyboard = [
        [InlineKeyboardButton("🎮 PLAY | 10 ብር", web_app=WebAppInfo(url=f"{WEB_APP_URL}?room=10"))],
        [InlineKeyboardButton("🚀 SuperBingo | 50 ብር", web_app=WebAppInfo(url=f"{WEB_APP_URL}?room=50"))],
        [InlineKeyboardButton("⚽ GoodBingo Bonus", web_app=WebAppInfo(url=f"{WEB_APP_URL}?room=bonus"))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "🕹️ **PLAY IN:**\nChoose a room to join the game:"
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_balance(user_id)
    await update.message.reply_text(f"💰 **የእርስዎ አሁናዊ ባላንስ፦** `{bal:.2f} ETB`", parse_mode='Markdown')

async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💳 **ብር ገቢ ማድረጊያ (Deposit)**\n\n"
        "ወደ አካውንትዎ ብር ለማስገባት በቴሌብር/ባንክ ያስገቡና ደረሰኙን ለአድሚን ይላኩ።\n"
        "📞 **አድሚን፦** @GoodBingoSupport"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_balance(user_id)
    text = (
        f"🏧 **ብር ማውጫ (Withdraw)**\n\n"
        f"የእርስዎ ባላንስ፦ `{bal:.2f} ETB`\n"
        f"ማውጣት የሚፈልጉትን መጠን ይፃፉ ወይም አድሚኑን ያነጋግሩ።"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

async def instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 **የጨዋታው ህጎች (Instructions):**\n\n"
        "1. በመጀመሪያ በ `/play` የፈለጉትን የጨዋታ ክፍል ይምረጡ።\n"
        "2. የቦርድ ቁጥር ሲይዙ 5x5 የቢንጎ ካርቴላ ይሰጥዎታል (የካርቴላው ዋጋ ከባላንስዎ ይቆረጣል)።\n"
        "3. ጨዋታው ሲጀምር ቁጥሮች በየሰከንዱ ይጠራሉ፤ የያዟቸው ቁጥሮች ሲወጡ ይነካሉ።\n"
        "4. በቁመት፣ በአግድም ወይም በደቀስ መስመር ሲሞላልዎት **BINGO** ይበሉ!\n"
        "5. አሸናፊ ከሆኑ የጨዋታው ጠቅላላ ሽልማት በቀጥታ ወደ ባላንስዎ ገቢ ይሆናል!"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

# --- 4. MAIN FUNCTION ---
def main():
    # Flask Web Server ን ማስነሳት
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    # Telegram Bot
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("play", play))
    application.add_handler(CommandHandler("balance", balance_cmd))
    application.add_handler(CommandHandler("deposit", deposit))
    application.add_handler(CommandHandler("withdraw", withdraw))
    application.add_handler(CommandHandler("instructions", instructions))
    
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
