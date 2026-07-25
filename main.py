# 1. PLAY (ጨዋታ መጀመር)
async def play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_balance(user_id)
    
    keyboard = [
        [InlineKeyboardButton("🎮 PLAY | 10 ብር", web_app=WebAppInfo(url=f"{WEB_APP_URL}?room=10&bal={bal}"))],
        [InlineKeyboardButton("🚀 SuperBingo | 50 ብር", web_app=WebAppInfo(url=f"{WEB_APP_URL}?room=50&bal={bal}"))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"🕹️ **የጨዋታ ክፍል ይምረጡ፦**\n\n💰 ቀሪ ሂሳብዎ፦ `{bal:.2f} ETB`"
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)

# 2. BALANCE (ቀሪ ሂሳብ)
async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_balance(user_id)
    await update.message.reply_text(f"💰 **የእርስዎ ቀሪ ሂሳብ (Balance)፦** `{bal:.2f} ETB`", parse_mode='Markdown')

# 3. DEPOSIT (Telebirr & CBE Birr)
async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = (
        "💳 **ብር ገቢ ማድረጊያ (Deposit)**\n\n"
        "ወደ አካውንትዎ ብር ለማስገባት በሚከተሉት የክፍያ አማራጮች ገቢ ያድርጉ፦\n\n"
        "📱 **Telebirr:** `0912345678` (GoodBingo)\n"
        "🏦 **CBE Birr / Bank:** `1000123456789` (GoodBingo)\n\n"
        "📌 **ማሳሰቢያ፦** ብር ገቢ ካደረጉ በኋላ ደረሰኙን (Screenshot) እና የእርስዎን User ID ለአጀንት ይላኩ።\n\n"
        f"🆔 **የእርስዎ User ID፦** `{user_id}`\n"
        "👤 **አጀንት (Support):** @GoodBingoSupport"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

# 4. WITHDRAW (Telebirr & CBE Birr)
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bal = get_balance(user_id)
    
    text = (
        "🏧 **ብር ማውጫ (Withdraw)**\n\n"
        f"💰 ቀሪ ሂሳብዎ፦ `{bal:.2f} ETB`\n\n"
        "ብር በ Telebirr ወይም CBE Birr ለማውጣት በሚከተለው ቅጽ ይጻፉልን፦\n"
        "`/request_withdraw <የብር መጠን> <የስልክ ቁጥር/አካውንት> <Telebirr ወይም CBE>`\n\n"
        "**ምሳሌ 1 (Telebirr):** `/request_withdraw 100 0911223344 Telebirr`\n"
        "**ምሳሌ 2 (CBE Birr):** `/request_withdraw 200 10001234567 CBE`"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

# 5. SUPPORT (የደንበኞች አገልግሎት)
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎧 **የደንበኞች አገልግሎት እና አጀንት (Support)**\n\n"
        "ማንኛውም ጥያቄ፣ የክፍያ ችግር ወይም አስተያየት ካለዎት አጀንታችንን ማነጋገር ይችላሉ፦\n\n"
        "👤 **የአጀንት ቴሌግራም አድራሻ፦** @GoodBingoSupport\n"
        "📞 **ስልክ ቁጥር፦** +251912345678\n"
        "⏱ **የስራ ሰዓት፦** 24/7 ዝግጁ ነን!"
    )
    await update.message.reply_text(text, parse_mode='Markdown')
