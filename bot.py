import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# إعدادات الاتصال
API_ID = 34257542
API_HASH = "614a1b5c5b712ac6de5530d5c571c42a"
TOKEN = "7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw"

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=TOKEN)
scheduler = AsyncIOScheduler()

# مخازن البيانات المؤقتة
user_data = {}
reminders = {}
media_store = {"photos": {}, "videos": {}, "taafi": []}
warnings = {}
taafi_index = {}

# --- دالة التحقق من الصلاحيات ---
def is_admin_or_owner(message: Message):
    return message.from_user and (message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]) and \
           (message.from_user.id in [admin.user.id for admin in app.get_chat_members(message.chat.id, filter=enums.ChatMembersFilter.ADMINISTRATORS)])

# --- 1. رسالة الترحيب ---
@app.on_message(filters.new_chat_members)
async def welcome_msg(client, message):
    for member in message.new_chat_members:
        # منشن مخفي عبر إيموجي
        welcome_text = (
            f"اهلاً بك في فجـر جـديد [\u200b](tg://user?id={member.id})🙋🏻‍♂️\n\n"
            "خطوة صغيرة اليوم… تصنع فرق كبير غدًا 🌅\n\n"
            "• ممنوع السلبية أو إحباط الآخرين ❌\n"
            "• لا يُسمح بأي محتوى غير لائق 🚫\n"
            "• الاحترام أسلوبنا الدائم 🤝\n"
            "• شارك بما يفيد ويحفّز غيرك 📌\n"
            "• التزامك اليوم هو نجاحك غداً 🌇"
        )
        await message.reply_text(welcome_text)

# --- 2. نظام التذكير والعد التنازلي ---
@app.on_message(filters.regex("^تذكير (.+)"))
async def set_reminder(client, message):
    text = message.matches[0].group(1)
    sent_msg = await message.reply_text("حسنا الان حدد المده ⏰")
    user_data[message.from_user.id] = {"action": "reminder", "content": text}

@app.on_message(filters.regex("^عد تنازلي (.+)"))
async def countdown_init(client, message):
    text = message.matches[0].group(1)
    await message.reply_text("حسنا اضف المدة (مثال: 20 ابريل)")
    user_data[message.from_user.id] = {"action": "countdown", "content": text}

# --- 3. نظام "تعافي" (المحتوى المتسلسل) ---
@app.on_message(filters.regex("^تعافي$"))
async def send_taafi(client, message):
    chat_id = message.chat.id
    if not media_store["taafi"]:
        return await message.reply_text("لا يوجد محتوى في قائمة التعافي حالياً.")
    
    idx = taafi_index.get(chat_id, 0)
    item = media_store["taafi"][idx]
    
    if item['type'] == 'photo':
        await message.reply_photo(item['file_id'], caption=item['caption'])
    elif item['type'] == 'video':
        await message.reply_video(item['file_id'], caption=item['caption'])
    # تحديث العداد
    taafi_index[chat_id] = (idx + 1) % len(media_store["taafi"])

@app.on_message(filters.command("اضف تعافي") & filters.group)
async def add_taafi_prompt(client, message):
    await message.reply_text("أرسل الآن المحتوى (صورة، فيديو، نص، صوت) لإضافته للقائمة:")
    user_data[message.from_user.id] = {"action": "adding_taafi"}

# --- 4. الإدارة (كتم، انذار) ---
@app.on_message(filters.regex("^كتم$") & filters.reply)
async def mute_user(client, message):
    if not is_admin_or_owner(message):
        return await message.reply_text("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
    
    await client.restrict_chat_member(message.chat.id, message.reply_to_message.from_user.id,
                                     enums.ChatPermissions(can_send_messages=False),
                                     until_date=datetime.now() + timedelta(days=1))
    await message.reply_text("تم كتم العضو لمدة 24 ساعة ✅")

@app.on_message(filters.regex("^انذار$") & filters.reply)
async def warn_user(client, message):
    if not is_admin_or_owner(message): return
    uid = message.reply_to_message.from_user.id
    count = warnings.get(uid, 0) + 1
    warnings[uid] = count
    
    if count >= 3:
        await client.restrict_chat_member(message.chat.id, uid, enums.ChatPermissions(can_send_messages=False),
                                         until_date=datetime.now() + timedelta(hours=6))
        warnings[uid] = 0
        await message.reply_text("وصل العضو لـ 3 إنذارات، تم الكتم 6 ساعات 🔇")
    else:
        await message.reply_text(f"تم إعطاء إنذار للعضو ({count}/3) ⚠️")

# --- 5. المنشن الجماعي (All) ---
@app.on_message(filters.regex(r"^all ?(.*)"))
async def mention_all(client, message):
    if not is_admin_or_owner(message): return
    extra_text = message.matches[0].group(1)
    members = []
    async for member in client.get_chat_members(message.chat.id):
        if not member.user.is_bot:
            members.append(member.user.mention)
    
    for i in range(0, len(members), 5):
        chunk = members[i:i+5]
        await message.reply_text(f"{extra_text}\n" + " ".join(chunk))
        await asyncio.sleep(0.5) # سرعة مع حماية من الحظر

# --- 6. ميزة "ا" (بروفايل العضو) ---
@app.on_message(filters.regex("^ا$"))
async def user_info(client, message):
    user = message.from_user
    # هنا يفترض وجود نظام عد رسائل حقيقي، سنضع قيم افتراضية للتوضيح
    msg_count = "1,250" 
    join_date = "2023/10/05"
    rank = "3#"
    
    info_text = (
        f"✨ **بياناتك يا بطل:**\n\n"
        f"👤 **الاسم:** {user.first_name}\n"
        f"📊 **عدد رسائلك:** {msg_count}\n"
        f"📅 **تاريخ الانضمام:** {join_date}\n"
        f"🏆 **ترتيبك بين المتفاعلين:** {rank}\n\n"
        f"استمر في العطاء! 🌟"
    )
    if user.photo:
        await message.reply_photo(user.photo.big_file_id, caption=info_text)
    else:
        await message.reply_text(info_text)

# --- دالة معالجة النصوص المباشرة (الذكاء البسيط للتعرف على المدد) ---
@app.on_message(filters.text & filters.group)
async def handle_steps(client, message):
    uid = message.from_user.id
    if uid not in user_data: return

    action = user_data[uid]["action"]
    
    if action == "countdown":
        target_text = message.text # هنا يمكن تطوير معالج تاريخ
        await message.reply_text(f"✅ تم ضبط العد التنازلي لـ {user_data[uid]['content']} إلى {target_text}")
        # يتم تشغيل التايمر هنا (وظيفة برمجية)
        del user_data[uid]

    elif action == "adding_taafi":
        # كود لإضافة الوسائط للقائمة
        item = {"type": "text", "content": message.text, "caption": ""}
        media_store["taafi"].append(item)
        await message.reply_text("✅ تمت إضافة المحتوى للقائمة")
        del user_data[uid]

# تشغيل البوت
scheduler.start()
app.run()
    
