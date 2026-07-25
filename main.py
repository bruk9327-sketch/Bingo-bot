import os
import logging
from flask import Flask, Response
from threading import Thread
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- 1. WEB SERVER FOR MINI APP ---
app = Flask(__name__)

@app.route('/')
def serve_miniapp():
    # index.html ገጹን በቀጥታ አንብቦ የሚያስተናግድ አስተማማኝ መንገድ
    if os.path.exists('index.html'):
        with open('index.html', 'r', encoding='utf-8') as f:
            content = f.read()
        return Response(content, mimetype='text/html')
    return "index.html file not found!", 404

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- 2. BOT CONFIGURATION ---
# ⚠️ ቦት ቶከንዎን እዚህ ጋር ያስገቡ
BOT_TOKEN = "8623843462:AAH8Wx0gTOj9Fb6kSm63zTo-SBjwuPJuRUM"

WEB_APP_URL = "https://bingo-bot-c90r.onrender.com"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- 3. MAIN MENU KEYBOARD ---
def main_menu_keyboard():
    web_app_btn = KeyboardButton(
        text="🎮 የቢንጎ ጨዋታ ይክፈቱ (Mini App)",
        web_app=WebAppInfo(url=WEB_APP_URL)
    )
    
    keyboard = [
        [web_app_btn],
        ['💰 ባላንስ', '📋 ደንቦች']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- 4. HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    welcome_text = (
        f"ሰላም {user_name}! 👋\n\n"
        f"እንኳን ወደ **GoodBingo Mini App** በሰላም መጡ! 🎉\n\n"
        f"ለመጫወት ከታች ያለውን **'🎮 የቢንጎ ጨዋታ ይክፈቱ (Mini App)'** የሚለውን ቁልፍ ይጫኑ።"
    )
    await update.message.reply_text(
        welcome_text, 
        parse_mode='Markdown', 
        reply_markup=main_menu_keyboard()
    )

# --- 5. MAIN FUNCTION ---
def main():
    # Flask ን በ background በ Thread ማስነሳት
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    # Telegram Bot ን ማስነሳት
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
