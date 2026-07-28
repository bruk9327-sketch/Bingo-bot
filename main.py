import os
import random
from threading import Thread
from flask import Flask
import telebot
from telebot.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    ReplyKeyboardRemove, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)

# =========================================================
# 1. WEB SERVER CONFIGURATION (Render Timeout ለመከላከል)
# =========================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bingo Bot is Alive and Running on Render!"

def run_web_server():
    # Render የሚሰጠውን PORT ይጠቀማል፣ ባይኖር በዲፎልት 10000 ያደርገዋል
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()

# =========================================================
# 2. BOT CONFIGURATION
# =========================================================
API_TOKEN = os.environ.get("BOT_TOKEN", "8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM")  # እዚህ ጋር የቦት Tokenዎን ያስገቡ
bot = telebot.TeleBot(API_TOKEN)

# =========================================================
# CONSTANTS & CONFIGURATION
# =========================================================
STAKE_AMOUNT = 10        # የመግቢያ ክፍያ (10 ብር)
BOT_COMMISSION = 2       # ከእያንዳንዱ ተጫዋች የሚወሰድ ኮሚሽን (2 ብር)
NET_PER_PLAYER = STAKE_AMOUNT - BOT_COMMISSION  # 8 ብር
MAX_PLAYERS = 10         # በ1 ዙር የሚጫወቱ ተጫዋቾች ብዛት (10 ሰዎች)

# Mock Data Storage (በእውነተኛ ሲስተም በDatabase የሚተካ)
users_db = {}            # {user_id: {"phone": str, "balance": int, "referred_by": str}}
active_room = []         # አሁን Waiting Room ላይ ያሉ ተጫዋቾች ዝርዝር [user_id_1, user_id_2, ...]

# =========================================================
# HELPER FUNCTIONS
# =========================================================
def get_or_create_user(user_id):
    if user_id not in users_db:
        users_db[user_id] = {
            "phone": None,
            "balance": 100,  # ለሙከራ 100 ብር Initial balance
            "referred_by": None
        }
    return users_db[user_id]

# =========================================================
# 1. COMMAND: /start (WITH REFERRAL LOGIC)
# =========================================================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    user = get_or_create_user(user_id)
    
    # ሪፈራል መኖሩን ማረጋገጥ (የላከውን ሰው መያዝ)
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        referrer_id = int(args[1].replace("ref_", ""))
        
        # ራሱን በራሱ ሪፈር እንዳያደርግና ቀደም ብሎ ከተመዘገበ እንዳይደገም ማድረግ
        if referrer_id != user_id and user["referred_by"] is None:
            user["referred_by"] = referrer_id
            try:
                bot.send_message(referrer_id, f"🎉 **አዲስ ተጠቃሚ!** ተጠቃሚ {user_id} በርስዎ ሼር ሊንክ ገብቷል።")
            except Exception:
                pass

    # የሼር ሊንክ ማዘጋጀት
    bot_username = bot.get_me().username
    share_link = f"https://t.me/share/url?url=https://t.me/{bot_username}?start=ref_{user_id}&text=እጅግ አስደሳች የቢንጎ ጨዋታ በዚህ ቦት ይጫወቱ! 💰🎮"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📤 ቦቱን ለወዳጅዎ ሼር ያድርጉ", url=share_link))

    welcome_msg = (
        f"👋 ሰላም {message.from_user.first_name}!\n\n"
        "ወደ **የቢንጎ (Bingo) ጨዋታ ቦት** እንኳን ደህና መጡ።\n\n"
        "🎮 ለመጫወት: /play ን ይጫኑ\n"
        "💰 የሂሳብ መጠን ለማየት: /balance\n"
        "📤 ቦቱን ለሌሎች ለማጋራት ከታች ያለውን አዝራር ይጫኑ።"
    )
    bot.send_message(user_id, welcome_msg, reply_markup=markup, parse_mode="Markdown")

# =========================================================
# 2. SHARE CONTACT & VERIFICATION
# =========================================================
def request_phone_keyboard():
    markup = ReplyKeyboardMarkup(row_width=1, resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton(text="📱 ስልክ ቁጥርዎን ያጋሩ (Share Contact)", request_contact=True))
    return markup

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    user_id = message.from_user.id
    contact = message.contact
    
    if contact is not None:
        # የላከው ስልክ ቁጥር የራሱ የመለያ አካውንት መሆኑን ማረጋገጥ
        if contact.user_id == user_id:
            user = get_or_create_user(user_id)
            user["phone"] = contact.phone_number
            
            bot.send_message(
                user_id, 
                f"✅ **ስልክ ቁጥርዎ ተረጋግጧል!** ({contact.phone_number})\n\nአሁን /play በማለት መጫወት ይችላሉ።",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="Markdown"
            )
        else:
            bot.send_message(
                user_id, 
                "❌ **ስህተት፦** እባክዎን የራስዎን ስልክ ቁጥር ያጋሩ!",
                reply_markup=request_phone_keyboard()
            )

# =========================================================
# 3. GAME ROOM MATCHING & 10-PLAYER POOL LOGIC
# =========================================================
@bot.message_handler(commands=['play'])
def join_game(message):
    user_id = message.from_user.id
    user = get_or_create_user(user_id)
    
    # 1. ስልክ ቁጥር ማረጋገጥ
    if not user["phone"]:
        bot.send_message(
            user_id, 
            "⚠️ **ለደህንነት ሲባል፦** ለመጫወት አስቀድመው የስልክ ቁጥርዎን ማረጋገጥ አለብዎት።",
            reply_markup=request_phone_keyboard()
        )
        return

    # 2. የሂሳብ መጠን (Balance) ማረጋገጥ
    if user["balance"] < STAKE_AMOUNT:
        bot.send_message(user_id, f"❌ ለጨዋታው በቂ ሂሳብ የለዎትም። የመግቢያ ክፍያ {STAKE_AMOUNT} ብር ያስፈልጋል።")
        return

    # 3. ቀደም ብሎ ጨዋታ ውስጥ መኖሩን ማረጋገጥ
    if user_id in active_room:
        bot.send_message(user_id, "⏳ አሁን በጨዋታ ተመዝግበዋል፤ ሌሎች ተጫዋቾች እስኪሞሉ ይጠብቁ...")
        return

    # ተጫዋቹን ወደ ጨዋታ ክፍሉ ማስገባት
    user["balance"] -= STAKE_AMOUNT  # 10 ብር መቁረጥ
    active_room.append(user_id)
    
    current_count = len(active_room)
    bot.send_message(
        user_id, 
        f"✅ **ወደ ጨዋታው ተቀላቅለዋል!**\n"
        f"💵 የመግቢያ ክፍያ: {STAKE_AMOUNT} ብር ተቆርጧል\n"
        f"👥 አሁን ያሉ ተጫዋቾች: {current_count}/{MAX_PLAYERS}"
    )

    # ለሌሎች ተጫዋቾች መልእክት መላክ (Optional)
    for p_id in active_room:
        if p_id != user_id:
            try:
                bot.send_message(p_id, f"📢 አዲስ ተጫዋች ተቀላቅሏል! ({current_count}/{MAX_PLAYERS})")
            except Exception:
                pass

    # 4. ተጫዋቾች 10 ሲሞሉ ጨዋታውን ማስጀመር
    if current_count == MAX_PLAYERS:
        start_bingo_round()

def start_bingo_round():
    global active_room
    
    # 10 ተጫዋች ሲሞላ የሚሰራ ስሌት
    total_players = len(active_room)
    total_pool = total_players * STAKE_AMOUNT             # 10 * 10 = 100 ብር
    house_commission = total_players * BOT_COMMISSION      # 10 * 2 = 20 ብር
    winner_payout = total_players * NET_PER_PLAYER        # 10 * 8 = 80 ብር

    # ለአብነት ያህል ከ10ሩ ተጫዋቾች አንዱን የመጀመሪያ ተጫዋች አሸናፊ እናድርገው
    winner_id = random.choice(active_room)
    
    # የኪስ ቦርሳ ማደስ (ለአሸናፊው 80 ብር ገቢ ማድረግ)
    users_db[winner_id]["balance"] += winner_payout

    # ለሁሉም ተጫዋቾች ውጤቱን ማሳወቅ
    for p_id in active_room:
        if p_id == winner_id:
            msg = (
                "🎉 **እንኳን ደስ አለዎት! አሸናፊ ሆነዋል!** 🎉\n\n"
                f"💰 ጠቅላላ የተሰበሰበ: {total_pool} ብር\n"
                f"🏢 የቦት ኮሚሽን (20%): {house_commission} ብር\n"
                f"🏆 **የእርስዎ የተጣራ ሽልማት: {winner_payout} ብር**"
            )
        else:
            msg = (
                "🏁 **ጨዋታው ተጠናቋል!**\n\n"
                f"🏆 የአሸናፊው ሽልማት: {winner_payout} ብር\n"
                "እድልዎን በሌላ ዙር ይሞክሩ! /play"
            )
        try:
            bot.send_message(p_id, msg, parse_mode="Markdown")
        except Exception:
            pass

    # የጨዋታ ክፍሉን ለአዲስ ዙር ባዶ ማድረግ
    active_room = []

# =========================================================
# 4. CHECK BALANCE
# =========================================================
@bot.message_handler(commands=['balance'])
def check_balance(message):
    user_id = message.from_user.id
    user = get_or_create_user(user_id)
    bot.send_message(user_id, f"💳 **የእርስዎ የሂሳብ መጠን:** {user['balance']} ብር", parse_mode="Markdown")

# =========================================================
# RUN BOT & SERVER
# =========================================================
if __name__ == "__main__":
    # 1. መጀመሪያ Web Serverሩን ከበስተጀርባ ማስነሳት
    print("🌐 Web Server እየተነሳ ነው...")
    keep_alive()

    # 2. በመቀጠል የቴሌግራም ቦቱን ማስነሳት
    print("🤖 ቦቱ ስራ ጀምሯል...")
    bot.infinity_polling()
