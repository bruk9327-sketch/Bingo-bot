from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()


from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8623843462:AAH8Wx0gTOj9Fb6kSm63zTo-SBjwuPJuRUM"
WEB_APP_URL = "https://goodbingo-mini-app.vercel.app/"
 # የርስዎ Vercel ሊንክ

# የተጫዋቾች ባላንስ ማስቀመጫ (Temporary Database)
user_balances = {}

# /start ትዕዛዝ
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_balances:
        user_balances[user_id] = 100.0  # ለምሳሌ 100 ETB ነጻ ቦነስ

    keyboard = [
        [InlineKeyboardButton("🎮 GoodBingo ተጫወት (Play)", web_app=WebAppInfo(url=WEB_APP_URL))],
        [InlineKeyboardButton("💰 ባላንስ (Balance)", callback_data="check_balance"), InlineKeyboardButton("📥 ብር ማስገቢያ (Deposit)", callback_data="deposit")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🎉 **እንኳን ወደ GoodBingo በሰላም መጡ {update.effective_user.first_name}!**\n\n"
        f"💵 ያሎት ባላንስ: **{user_balances[user_id]:.2f} ETB**\n\n"
        "ከታች ያለውን ቁልፍ በመጫን ጨዋታውን ይጀምሩ 👇",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# /balance ትዕዛዝ
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = user_balances.get(user_id, 0.0)
    await update.message.reply_text(f"💳 **የእርስዎ አሁናዊ ባላንስ፦** {bal:.2f} ETB")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    
    print("ቦቱ ከባላንስ ሲስተም ጋር መስራት ጀምሯል...")
    app.run_polling()

if __name__ == '__main__':
    main()
