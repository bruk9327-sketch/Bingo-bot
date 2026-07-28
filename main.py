import os
import random
import time
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
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    server_thread = Thread(target=run_web_server)
    server_thread.daemon = True
    server_thread.start()

# =========================================================
# 2. BOT CONFIGURATION
# =========================================================
API_TOKEN = os.environ.get("BOT_TOKEN", "8623843462:AAG7e74RbOdQF5N4lsT2EsO8XJ0Hy5TYjkM")
bot = telebot.TeleBot(API_TOKEN)

STAKE_AMOUNT = 10        # የመግቢያ ክፍያ
BOT_COMMISSION = 2       # ኮሚሽን
users_db = {}            # የተጠቃሚዎች መረጃ
active_games = {}        # ንቁ ጨዋታዎች {user_id: {"card": [], "marked": [], "status": bool}}

# =========================================================
# BINGO CARD & GAME HELPER FUNCTIONS
# =========================================================
def get_or_create_user(user_id):
    if user_id not in users_db:
        users_db[user_id] = {
            "phone": None,
            "balance": 100,
            "referred_by": None
        }
    return users_db[user_id]

def generate_bingo_card():
    """የ 5x5 የቢንጎ ካርድ ያዘጋጃል (B:1-15, I:16-30, N:31-45, G:46-60, O:61-75)"""
    b = random.sample(range(1, 16), 5)
    i = random.sample(range(16, 31), 5)
    n = random.sample(range(31, 46), 5)
    g = random.sample(range(46, 61), 5)
    o = random.sample(range(61, 76), 5)
    
    # የካርዱ መሃል FREE ነው
    n[2] = "FREE"
    
    card = []
    for row in range(5):
        card.append([b[row], i[row], n[row], g[row], o[row]])
    return card

def format_bingo_card(card, marked_set):
    """የቢንጎ ካርዱን በጥሩ የፅሁፍ ቅርፅ ማሳያ"""
    text = "🟩 **የእርስዎ የቢንጎ ካርድ (B-I-N-G-O)** 🟩\n\n"
    text += "` B   |  I   |  N   |  G   |  O `" + "\n"
    text += "---------------------------------\n"
    
    for row in card:
        row_str = []
        for val in row:
            if val == "FREE" or val in marked_set:
                row_str.append(" ❌ ")
            else:
                row_str.append(f"{val:^4}")
        text += "`" + "|".join(row_str) + "`\n"
    return text

def check_bingo_win(card, marked_set):
    """መስመር መሞላቱን ይፈትሻል (Win Check)"""
    # Grid ማዘጋጀት (True ከሆነ ተነክቷል)
    grid = [[(val == "FREE" or val in marked_set) for val in row] for row in card]
    
    # Horizontal & Vertical checks
    for i in range(5):
        if all(grid[i][j] for j in range(5)): return True # Rows
        if all(grid[j][i] for j in range(5)): return True # Columns
        
    # Diagonal checks
    if all(grid[i][i] for i in range(5)): return True
    if all(grid[i][4 - i] for i in range(5)): return True
    
    return False

# =========================================================
# COMMANDS & HANDLERS
# =========================================================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    get_or_create_user(user_id)
    welcome_msg = (
        f"👋 ሰላም {message.from_user.first_name}!\n\n"
        "ወደ **የቢንጎ (Bingo) ጨዋታ ቦት** እንኳን ደህና መጡ።\n\n"
        "🎮 ለመጫወት: /play ን ይጫኑ\n"
        "💰 የሂሳብ መጠን ለማየት: /balance\n"
    )
    bot.send_message(user_id, welcome_msg, parse_mode="Markdown")

def request_phone_keyboard():
    markup = ReplyKeyboardMarkup(row_width=1, resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton(text="📱 ስልክ ቁጥርዎን ያጋሩ (Share Contact)", request_contact=True))
    return markup

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    user_id = message.from_user.id
    contact = message.contact
    if contact and contact.user_id == user_id:
        user = get_or_create_user(user_id)
        user["phone"] = contact.phone_number
        bot.send_message(
            user_id, 
            f"✅ **ስልክ ቁጥርዎ ተረጋግጧል!** ({contact.phone_number})\n\nአሁን /play በማለት መጫወት ይችላሉ።",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )

# =========================================================
# GAME ENGINE (ቀጥታ ጨዋታ ለማየት የሚሰራ)
# =========================================================
@bot.message_handler(commands=['play'])
def play_game(message):
    user_id = message.from_user.id
    user = get_or_create_user(user_id)
    
    if not user["phone"]:
        bot.send_message(user_id, "⚠️ **ለደህንነት ሲባል፦** ለመጫወት አስቀድመው የስልክ ቁጥርዎን ያጋሩ።", reply_markup=request_phone_keyboard())
        return

    if user["balance"] < STAKE_AMOUNT:
        bot.send_message(user_id, f"❌ በቂ ሂሳብ የለዎትም። ለመጫወት {STAKE_AMOUNT} ብር ያስፈልጋል።")
        return

    if user_id in active_games and active_games[user_id]["running"]:
        bot.send_message(user_id, "⏳ አሁን ጨዋታ ላይ ነዎት!")
        return

    # ሂሳብ መቁረጥ
    user["balance"] -= STAKE_AMOUNT
    
    # አዲስ የቢንጎ ካርድ ማዘጋጀት
    card = generate_bingo_card()
    active_games[user_id] = {
        "card": card,
        "marked": set(),
        "running": True
    }

    card_text = format_bingo_card(card, set())
    msg = bot.send_message(
        user_id, 
        f"🎯 **ጨዋታው ተጀምሯል!**\n💵 የመግቢያ ክፍያ: {STAKE_AMOUNT} ብር ተቆርጧል\n\n{card_text}\n\n🎲 **ቁጥሮች መውጣት ሊጀምሩ ነው...**",
        parse_mode="Markdown"
    )

    # ቁጥሮችን በየሰከንዱ የመጥራት ሂደት (በአዲስ Thread)
    Thread(target=run_bingo_loop, args=(user_id, msg.message_id)).start()

def run_bingo_loop(user_id, msg_id):
    """ቁጥሮችን በየሰከንዱ እየጠራ ጨዋታውን የሚያስኬድ"""
    drawn_numbers = list(range(1, 76))
    random.shuffle(drawn_numbers)
    
    game = active_games[user_id]
    card = game["card"]
    marked = game["marked"]

    for num in drawn_numbers:
        if not game["running"]:
            break
            
        time.sleep(3) # በየ 3 ሰከንዱ ቁጥር ይወጣል
        marked.add(num)
        
        # የካርድ ማሳያውን ማደስ
        card_text = format_bingo_card(card, marked)
        
        # አሸናፊ መሆኑን መፈተሽ
        if check_bingo_win(card, marked):
            game["running"] = False
            win_amount = 80 # የአሸናፊነት ሽልማት
            users_db[user_id]["balance"] += win_amount
            
            final_msg = (
                f"🎉🎉 **BINGO! BINGO! BINGO!** 🎉🎉\n\n"
                f"🏆 **እንኳን ደስ አለዎት! አሸንፈዋል!**\n"
                f"💰 የሽልማት መጠን: {win_amount} ብር\n\n"
                f"{card_text}"
            )
            bot.edit_message_text(final_msg, user_id, msg_id, parse_mode="Markdown")
            return

        try:
            bot.edit_message_text(
                f"🎲 **የወጣው ቁጥር:** `{num}`\n\n{card_text}\n\n⏳ ቀጣይ ቁጥር እየተጠበቀ ነው...",
                user_id, 
                msg_id, 
                parse_mode="Markdown"
            )
        except Exception:
            pass

@bot.message_handler(commands=['balance'])
def check_balance(message):
    user_id = message.from_user.id
    user = get_or_create_user(user_id)
    bot.send_message(user_id, f"💳 **የእርስዎ የሂሳብ መጠን:** {user['balance']} ብር", parse_mode="Markdown")

# =========================================================
# MAIN EXECUTION
# =========================================================
if __name__ == "__main__":
    print("🌐 Web Server እየተነሳ ነው...")
    keep_alive()

    print("🤖 ቦቱ ስራ ጀምሯል...")
    bot.infinity_polling()
