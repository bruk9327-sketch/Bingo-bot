import logging
from flask import Flask
from threading import Thread
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- 1. WEB SERVER FOR RENDER (KEEP ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "Bingo Bot is Alive and Running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()

# --- 2. BOT CONFIGURATION ---
BOT_TOKEN = "8623843462:AAH8Wx0gTOj9Fb6kSm63zTo-SBjwuPJuRUM"  # <--- የእርስዎን ቦት ቶከን እዚህ ያስገቡ

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# የተያዙ ቁጥሮችን/ቦርዶችን መመዝገቢያ database (Memory)
taken_boards = {} # {board_number: user_id}

# --- 3. KEYBOARDS (ሜኑዎች) ---
def main_menu_keyboard():
    keyboard = [
        ['🎮 ጨዋታ ጀምር', '💰 ባላንስ'],
        ['📋 የጨዋታ ደንቦች', '📞 እርዳታ']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def generate_board_buttons():
    # ከ 1 እስከ 12 የቦርድ ቁጥሮች አማራጭ (እንደ ፍላጎትዎ ቁጥሩን መጨመር ይቻላል)
    keyboard = []
    row = []
    for i in range(1, 13):
        status = "❌ " if i in taken_boards else "🔢 "
        row.append(InlineKeyboardButton(f"{status}{i}", callback_data=f"select_{i}"))
        if len(row) == 3:  # በየመስመሩ 3 ቁጥሮች
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

# --- 4. HANDLERS (የቦት ምላሾች) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    welcome_text = (
        f"ሰላም {user_name}! 👋\n\n"
        f"እንኳን ወደ **Bingo Bot** በሰላም መጡ! 🎉\n"
        f"ለመጫወት ከታች ካሉት አማራጮች **'🎮 ጨዋታ ጀምር'** የሚለውን ይጫኑ።"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown', reply_markup=main_menu_keyboard())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == '🎮 ጨዋታ ጀምር':
        await update.message.reply_text(
            "የሚፈልጉትን የቢንጎ ቦርድ ቁጥር ይምረጡ፦\n(❌ ማለት ቀድሞ የተያዘ ቁጥር ነው)",
            reply_markup=generate_board_buttons()
        )
    elif text == '💰 ባላንስ':
        await update.message.reply_text("የእርስዎ አሁናዊ ባላንስ፦ **0.00 ETB**", parse_mode='Markdown')
    elif text == '📋 የጨዋታ ደንቦች':
        await update.message.reply_text("📖 **የጨዋታ ደንቦች፦**\n1. ቦርድ ይምረጡ\n2. ቁጥሮች ሲጠሩ ይከታተሉ\n3. መስመር የሞላ 'BINGO' ይላል!", parse_mode='Markdown')
    elif text == '📞 እርዳታ':
        await update.message.reply_text("ለማንኛውም ጥያቄ ወይም እርዳታ አድሚኑን ያነጋግሩ።")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id
    user_name = query.from_user.first_name

    if data.startswith("select_"):
        board_num = int(data.split("_")[1])

        if board_num in taken_boards:
            await query.edit_message_text(
                f"⚠️ **ቁጥር {board_num} ቀድሞ ተይዟል!**\nእባክዎ ሌላ ቁጥር ይምረጡ፦",
                parse_mode='Markdown',
                reply_markup=generate_board_buttons()
            )
        else:
            # ቁጥሩን ለተጫዋቹ መያዝ
            taken_boards[board_num] = user_id
            await query.edit_message_text(
                f"✅ **ቁጥር {board_num} በስኬት ተይዟል!**\n\n"
                f"👤 ተጫዋች፦ {user_name}\n"
                f"🎲 **ጨዋታው አሁን ይጀምራል...**",
                parse_mode='Markdown'
            )

# --- 5. MAIN FUNCTION ---
def main():
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_click))

    application.run_polling()

if __name__ == '__main__':
    main()
