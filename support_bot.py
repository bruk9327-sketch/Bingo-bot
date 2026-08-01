import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# =========================================================
# 1. CONFIGURATION & BOT SETUP
# =========================================================
# የ BkbingosupportBot API Token (የተሰጠውን ቶከን አቀናጅተናል)
SUPPORT_BOT_TOKEN = os.environ.get("SUPPORT_BOT_TOKEN", "8912812512:AAHL9OPDgGNa2QS9YHqY5c6KDKuB7OlF-3M")

# የ BKBINGO Pro አድሚን Telegram User ID
ADMIN_ID = int(os.environ.get("ADMIN_ID", "855985673"))

bot = telebot.TeleBot(SUPPORT_BOT_TOKEN)

# የተጠቃሚዎችን እና የአድሚኑን ሁኔታ (State) በጊዜያዊነት ለመያዝ
user_states = {}

# =========================================================
# 2. PLAYER SIDE HANDLERS (የተጫዋቾች ክፍል)
# =========================================================

@bot.message_handler(commands=['start'])
def handle_start(message):
    """ተጫዋቹ ከ BKBINGO Pro ተነስቶ /start ሲል የሚስተናገድበት"""
    uid = message.from_user.id
    first_name = message.from_user.first_name
    args = message.text.split()
    
    # ከ Main Bot Deep Link ተያይዞ የመጣውን መረጃ መለየት (e.g. USER_855985673_BAL_100)
    bkb_info = ""
    if len(args) > 1 and "USER_" in args[1]:
        try:
            parts = args[1].split('_')
            bkb_user_id = parts[1]
            bkb_bal = parts[3]
            bkb_info = f"\n🆔 **BKBINGO ID:** `{bkb_user_id}`\n💰 **ባላንስ:** `{bkb_bal} ETB`"
        except Exception:
            pass

    # የትእዛዝ ሁኔታውን ማዘጋጀት
    user_states[uid] = "WAITING_FOR_QUESTION"
    
    welcome_text = (
        f"👋 ሰላም **{first_name}**!\n\n"
        f"ወደ **BKBINGO Pro** ኦፊሴላዊ የደንበኞች አገልግሎት እንኳን ደህና መጡ! 🎧\n"
        f"{bkb_info}\n\n"
        f"እባክዎን የገጠመዎትን ችግር፣ የዲፖዚት/ወጪ ጥያቄ ወይም መልእክት አሁን በፅሁፍ ወይም በምስል (Screenshot) ይላኩልን።\n"
        f"የቡድናችን አባል ጥያቄዎን ተቀብሎ በቅርቡ ምላሽ ይሰጥዎታል።"
    )
    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.from_user.id != ADMIN_ID, content_types=['text', 'photo', 'document'])
def handle_user_question(message):
    """ተጫዋቹ የሚልከውን ጥያቄ/መልእክት ተቀብሎ ወደ ADMIN ማስተላለፍ"""
    uid = message.from_user.id
    first_name = message.from_user.first_name
    username = f"@{message.from_user.username}" if message.from_user.username else "የለውም"

    # ለአድሚን ምላሽ መስጫ Inline Button ማዘጋጀት
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text=f"✉️ ለ {first_name} ምላሽ ስጥ", callback_data=f"reply_to_{uid}"))

    # ለአድሚን የሚላክ የተጠቃሚው ጥያቄ አወቃቀር
    admin_msg = (
        f"🎧 **አዲስ የድጋፍ ጥያቄ ደርሷል!**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 ተጫዋች: **{first_name}** ({username})\n"
        f"🆔 Telegram ID: `{uid}`\n\n"
        f"💬 **የተጠየቀው ጥያቄ/መልእክት፦**\n"
        f"{message.text if message.text else (message.caption if message.caption else '📷 [ምስል/ፋይል ተልኳል]')}"
    )

    try:
        # መልእክቱ ምስል ከሆነ
        if message.photo:
            bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=admin_msg, reply_markup=markup, parse_mode="Markdown")
        # መልእክቱ ዶክመንት/ፋይል ከሆነ
        elif message.document:
            bot.send_document(ADMIN_ID, message.document.file_id, caption=admin_msg, reply_markup=markup, parse_mode="Markdown")
        # መልእክቱ ፅሁፍ ብቻ ከሆነ
        else:
            bot.send_message(ADMIN_ID, admin_msg, reply_markup=markup, parse_mode="Markdown")

        # ለተጫዋቹ የደረሰን መሆኑን ማረጋገጫ መስጠት
        bot.send_message(
            message.chat.id,
            "✅ **ጥያቄዎ ለድጋፍ ሰጪዎቻችን ተልኳል!**\n\n"
            "አድሚኑ ጥያቄዎን ተመልክቶ በቅርቡ እዚሁ ምላሽ ይሰጥዎታል። በትዕግስት ይጠብቁ! 🙏",
            parse_mode="Markdown"
        )
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ መልእክቱን መላክ አልተቻለም፦ {e}")


# =========================================================
# 3. ADMIN SIDE HANDLERS (የአድሚን ምላሽ መስጫ ክፍል)
# =========================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_to_'))
def handle_reply_button(call):
    """አድሚኑ 'ምላሽ ስጥ' የሚለውን ቁልፍ ሲጫን"""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "ይህ ለአድሚን ብቻ የተፈቀደ ነው!", show_alert=True)
        return
        
    target_uid = call.data.split('_')[2]
    user_states[ADMIN_ID] = f"SENDING_REPLY_TO_{target_uid}"
    
    bot.answer_callback_query(call.id)
    bot.send_message(ADMIN_ID, f"✍️ ለተጫዋች ID `{target_uid}` የሚልኩትን ምላሽ ይፃፉ፦", parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and str(user_states.get(ADMIN_ID, '')).startswith("SENDING_REPLY_TO_"), content_types=['text', 'photo', 'document'])
def send_admin_reply_to_user(message):
    """አድሚኑ የጻፈውን ምላሽ ተቀብሎ ለተጫዋቹ መላክ"""
    target_uid = int(user_states[ADMIN_ID].split('_')[3])
    user_states[ADMIN_ID] = None  # State ማፅዳት

    reply_header = (
        f"🎧 **ከ BKBINGO Pro የደንበኞች አገልግሎት የተሰጠ ምላሽ፦**\n"
        f"━━━━━━━━━━━━━━━\n"
    )

    try:
        # አድሚኑ በምስል ምላሽ ከሰጠ
        if message.photo:
            caption = reply_header + (message.caption if message.caption else "")
            bot.send_photo(target_uid, message.photo[-1].file_id, caption=caption, parse_mode="Markdown")
        # አድሚኑ በፋይል ምላሽ ከሰጠ
        elif message.document:
            caption = reply_header + (message.caption if message.caption else "")
            bot.send_document(target_uid, message.document.file_id, caption=caption, parse_mode="Markdown")
        # አድሚኑ በፅሁፍ ምላሽ ከሰጠ
        else:
            bot.send_message(target_uid, reply_header + message.text, parse_mode="Markdown")

        # ለአድሚኑ ማረጋገጫ መስጠት
        bot.send_message(ADMIN_ID, f"✅ ምላሽዎ ለተጫዋች `{target_uid}` በተሳካ ሁኔታ ተልኳል!", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ ምላሹን ለተጫዋቹ መላክ አልተቻለም፦ {e}", parse_mode="Markdown")

# =========================================================
# 4. BOT EXECUTION
# =========================================================
if __name__ == '__main__':
    print("🚀 BkbingosupportBot በስኬት ተነስቷል! መልእክቶችን ለመቀበል ዝግጁ ነው...")
    bot.infinity_polling(skip_pending=True)
