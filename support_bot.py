import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# የ Support Bot Token እዚህ ጋር አስገባ
SUPPORT_BOT_TOKEN = os.environ.get("SUPPORT_BOT_TOKEN", "የ_SUPPORT_BOT_TOKEN_እዚህ_አስገባ")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "855985673"))

support_bot = telebot.TeleBot(SUPPORT_BOT_TOKEN)

# የተጫዋቾች ጊዜያዊ ሁኔታ መያዣ
user_tickets = {}

@support_bot.message_handler(commands=['start'])
def start_support(message):
    uid = message.from_user.id
    text = message.text

    # ከ Main Bot በ Deep Link የመጣ መረጃ መኖሩን ማረጋገጥ (USER_12345_BAL_100)
    user_info = ""
    if "USER_" in text and "_BAL_" in text:
        try:
            parts = text.split("USER_")[1].split("_BAL_")
            user_id = parts[0]
            balance = parts[1]
            user_info = f"\n\n👤 **የተጫዋች መረጃ፦**\n🆔 ID: `{user_id}`\n💰 ባላንስ: **{balance} ETB**"
        except Exception:
            pass

    welcome_msg = (
        f"👋 ሰላም **{message.from_user.first_name}**!\n"
        f"ወደ **BKBINGO Pro** የደንበኞች አገልግሎት እንኳን ደህና መጡ! 🎧{user_info}\n\n"
        f"ያጋጠመዎትን ችግር፣ የዲፖዚት/ዊዝድሮው ጥያቄ ወይም አስተያየት በአንድ መልእክት ፅፈው ይላኩልን።"
    )
    
    support_bot.send_message(message.chat.id, welcome_msg, parse_mode="Markdown")

@support_bot.message_handler(func=lambda m: m.from_user.id != ADMIN_ID, content_types=['text', 'photo'])
def handle_user_inquiry(message):
    uid = message.from_user.id
    user_tickets[uid] = message.chat.id

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✍️ መልስ ስጥ (Reply)", callback_data=f"reply_{uid}"))

    admin_notification = (
        f"📩 **አዲስ የደንበኞች ጥያቄ!**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 ከ: {message.from_user.first_name} (`{uid}`)\n"
        f"💬 መልእክት: {message.text if message.text else 'Photo Sent'}"
    )

    if message.photo:
        support_bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=admin_notification, reply_markup=markup, parse_mode="Markdown")
    else:
        support_bot.send_message(ADMIN_ID, admin_notification, reply_markup=markup, parse_mode="Markdown")

    support_bot.send_message(message.chat.id, "✅ **መልእክትዎ ለደንበኞች አገልግሎት ደርሷል!**\nአድሚኑ መረጃውን አጣርቶ በቅርቡ ምላሽ ይሰጥዎታል።")

# የአድሚን ምላሽ መስጫ (Admin Reply Handler)
admin_reply_state = {}

@support_bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
def prepare_admin_reply(call):
    target_uid = int(call.data.split('_')[1])
    admin_reply_state[ADMIN_ID] = target_uid
    support_bot.answer_callback_query(call.id)
    support_bot.send_message(ADMIN_ID, f"✍️ ለ ተጫዋች `{target_uid}` የሚላከውን መልስ አሁን ይጻፉ፦", parse_mode="Markdown")

@support_bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and ADMIN_ID in admin_reply_state)
def send_admin_reply(message):
    target_uid = admin_reply_state.pop(ADMIN_ID, None)
    if target_uid:
        try:
            support_bot.send_message(
                target_uid,
                f"🎧 **ከደንበኞች አገልግሎት የተሰጠ መልስ፦**\n━━━━━━━━━━━━━━━\n{message.text}"
            )
            support_bot.send_message(ADMIN_ID, f"✅ መልሱ ለተጫዋች `{target_uid}` ተልኳል!")
        except Exception as e:
            support_bot.send_message(ADMIN_ID, f"❌ መልእክቱን መላክ አልተቻለም፦ {e}")

if __name__ == "__main__":
    print("Support Bot is running...")
    support_bot.infinity_polling(skip_pending=True)
