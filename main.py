import logging
import random
import asyncio
from flask import Flask, send_from_file
from threading import Thread
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- 1. WEB SERVER & MINI APP HOSTING ---
app = Flask(__name__, static_folder='.')

@app.route('/')
def serve_miniapp():
    # index.html ገጻችንን ያስተናግዳል
    return send_from_file('.', 'index.html')

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()

# --- 2. BOT CONFIGURATION ---
BOT_TOKEN = "8623843462:AAH8Wx0gTOj9Fb6kSm63zTo-SBjwuPJuRUM"  # <--- ቦት ቶከንዎን እዚህ ያስገቡ
# የ Render ዌብሳይት ሊንክዎ (መጨረሻው ላይ / ሳይኖረው)
WEB_APP_URL = "https://bingo-bot-c90r.onrender.com" 

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# የጨዋታ ሁኔታዎች
called_numbers = []
is_game_active = False

# --- 3. MAIN MENU WITH WEB APP BUTTON ---
def main_menu_keyboard():
    # Mini App የሚከፍተው ቁልፍ
    web_app_btn = KeyboardButton(
        text="🎮 የቢንጎ ጨዋታ ይክፈቱ",
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
        f"ለመጫወት ከታች ያለውን **'🎮 የቢንጎ ጨዋታ ይክፈቱ'** የሚለውን ቁልፍ ይጫኑ።"
    )
    await update.message.reply_text(
        welcome_text, 
        parse_mode='Markdown', 
        reply_markup=main_menu_keyboard()
    )

# --- 5. MAIN FUNCTION ---
def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.run_polling()

if __name__ == '__main__':
    main()
