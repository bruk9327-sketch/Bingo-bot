import os
import re
import logging
from flask import Flask, Response, request, jsonify
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# --- 1. FLASK WEB SERVER ---
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
            user_balances[int(user_id)] = float(new_balance)
        except:
            user_balances[str(user_id)] = float(new_balance)
        return jsonify({"status": "success", "balance": new_balance})
    return jsonify({"status": "error"}), 400

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- 2. CONFIG & DATABASE ---
BOT_TOKEN = "8623843462:AAH8Wx0gTOj9Fb6kSm63zTo-SBjwuPJuRUM"          # <-- የቦት ቶከንዎን ያስገቡ
BOT_USERNAME = "EthioBingoBot"              # <-- የቦት Username (@ ሳይጨምሩ)
WEB_APP_URL = "https://bingo-bot-c90r.onrender.com"
ADMIN_CHAT_ID = 855985673                  # <-- ⚠️ የራስዎን Telegram User ID እዚህ ያስገቡ

logging.basicConfig(level=logging.INFO)

user_balances = {}      # {user_id: balance} (Default 0.00)
user_referrals = {}     # {user_id: count}
referred_by = {}
pending_deposits = {}   # {txn_id: {'user_id': uid, 'amount': amt}}
used_txns = set()

def get_balance(user_id):
    return user_balances.get(user_id, 0.0)

def get_ref_count(user_id):
    return user_referrals.get(user_id, 0)

def update_balance(user_id, amount):
    curr = get_balance(user_id)
    user_balances[user_id] = max(0.0, curr + amount)
    return user_balances[user_id]

# --- 3. BOT COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    if user_id not in user_balances:
        user_balances[user_id] = 0.0
    if user_id not in user_referrals:
        user_referrals[user_id] = 0

    if args and len(args) > 0:
        ref_payload = args[0]
        if ref_payload.startswith("ref_"):
            try:
                referrer_id = int(ref_payload.replace("ref_", ""))
                if user_id != referrer_id and user_id not in referred_by:
                    referred_by[user_id] = referrer_id
                    user_referrals[referrer_id] = user_referrals.get(referrer_id, 0) + 1
                    
                    invited_count = user_referrals[referrer_id]
                    try:
                        if invited_count >= 10:
                            await context.bot.send_message(
                                chat_id=referrer_id,
                                text="🎉 **እንኳን ደስ አለዎት!** 10 ሰዎችን ስለጋበዙ ጨዋታው ተከፍቶልዎታል። 🎮"
                            )
                        else:
                            await context.bot.send_message(
                                chat_id=referrer_id,
                                text=f"👤 **አዲስ ሰው ተቀላቅሏል!**\n\nየጋበዟቸው ተጫዋቾች፦ `{invited_count}/10`"
                            )
                    except Exception as e:
                        logging.error(f"Failed to notify referrer: {e}")
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

async def send_invite_info(update_or_query, user_id):
    ref_count = get_ref_count(user_id)
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
    ref_count = get_ref_count(user_id)
    
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

# --- 4. HANDLERS ---
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

    # 👨‍ገቢዎች አድሚን ማጽደቂያ (Admin Approval Logic)
    elif data.startswith("app_") or data.startswith("rej_"):
        if query.from_user.id != ADMIN_CHAT_ID:
            await query.answer("❌ ለእርሶ የተፈቀደ አይደለም!", show_alert=True)
            return

        action, txn_id = data.split("_", 1)
        dep_info = pending_deposits.get(txn_id)

        if not dep_info:
            await query.edit_message_text("❌ ይህ ጥያቄ ከዚህ ቀደም ተስተናግዷል ወይም አልተገኘም!")
            return

        target_uid = dep_info['user_id']
        amount = dep_info['amount']

        if action == "app":
            # አድሚኑ ሲያጸድቀው (Approve)
            new_bal = update_balance(target_uid, amount)
            used_txns.add(txn_id)
            del pending_deposits[txn_id]

            await query.edit_message_text(f"✅ **ጽድቋል!**\n\nለ User `{target_uid}` የ `{amount:.2f} ETB` ሂሳብ ተጨምሯል።\nአዲስ ባላንስ፦ `{new_bal:.2f} ETB`", parse_mode='Markdown')
            
            # ለተጫዋቹ ማሳወቅ
            try:
                await context.bot.send_message(
                    chat_id=target_uid,
                    text=f"🎉 **ክፍያዎ ጸድቋል!**\n\n➕ የተጨመረ፦ `{amount:.2f} ETB`\n💰 አዲስ ባላንስ፦ `{new_bal:.2f} ETB`",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logging.error(f"Failed user notify: {e}")

        elif action == "rej":
            # አድሚኑ ውድቅ ሲያደርገው (Reject)
            del pending_deposits[txn_id]
            await query.edit_message_text(f"❌ **ውድቅ ተደርጓል!**\n\nየ Txn ID `{txn_id}` ክፍያ ውድቅ ተደርጓል።", parse_mode='Markdown')

            # ለተጫዋቹ ማሳወቅ
            try:
                await context.bot.send_message(
                    chat_id=target_uid,
                    text=f"❌ **ክፍያዎ ውድቅ ተደርጓል!**\n\nየላኩት ደረሰኝ/Txn ID አልተረጋገጠም። እባክዎ ትክክለኛ ደረሰኝ መላክዎን ያረጋግጡ።",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logging.error(f"Failed user notify: {e}")

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if text in ["💰 ባላንስ", "ባላንስ", "/balance"]:
        bal = get_balance(user_id)
        ref_count = get_ref_count(user_id)
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

    # 📩 ተጫዋቹ የክፍያ ደረሰኝ ሲልክ
    txn_match = re.search(r'Txn ID\s+([A-Z0-9]+)', text, re.IGNORECASE)
    amt_match = re.search(r'paid\s+([\d\.]+)\s*Br', text, re.IGNORECASE)

    if txn_match and amt_match:
        txn_id = txn_match.group(1)
        amount = float(amt_match.group(1))

        if txn_id in used_txns:
            await update.message.reply_text("❌ ይህ ደረሰኝ/Txn ID ቀደም ብሎ ጥቅም ላይ ውሏል!")
            return

        if txn_id in pending_deposits:
            await update.message.reply_text("⏳ ይህ ክፍያ ቀደም ብሎ ተልኮ በአድሚን ማረጋገጫ ላይ ይገኛል!")
            return

        # ጥያቄውን በይ기ዜ መመዝገብ
        pending_deposits[txn_id] = {'user_id': user_id, 'amount': amount}

        # ለተጫዋቹ የሚላክ
        await update.message.reply_text(
            f"⏳ **ክፍያዎ ለግምገማ ተልኳል!**\n\n"
            f"🔹 Txn ID: `{txn_id}`\n"
            f"🔹 መጠን: `{amount:.2f} ETB`\n\n"
            f"አድሚኑ ደረሰኙን አጣርቶ እንደጨረሰ ባላንስዎ ላይ ይጨመራል።",
            parse_mode='Markdown'
        )

        # ለአድሚኑ የሚላክ መልእክት + Approval Buttons
        admin_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ አጽድቅ (Approve)", callback_data=f"app_{txn_id}"),
                InlineKeyboardButton("❌ ውድቅ አድርግ (Reject)", callback_data=f"rej_{txn_id}")
            ]
        ])
        
        user_name = update.effective_user.full_name
        admin_msg = (
            f"🚨 **አዲስ የክፍያ ጥያቄ!**\n\n"
            f"👤 **ተጫዋች:** {user_name} (ID: `{user_id}`)\n"
            f"💰 **መጠን:** `{amount:.2f} ETB`\n"
            f"🧾 **Txn ID:** `{txn_id}`\n\n"
            f"📝 **የላከው መልእክት:**\n_{text}_"
        )
        
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, parse_mode='Markdown', reply_markup=admin_keyboard)
        except Exception as e:
            logging.error(f"Failed to alert admin: {e}")

# --- MAIN ENGINE ---
def main():
    Thread(target=run_flask, daemon=True).start()
    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CallbackQueryHandler(button_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    
    bot_app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
