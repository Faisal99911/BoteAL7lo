Import asyncio
import json
import os
from pyrogram import Client, filters, enums
from pyrogram.types import Message, ChatPermissions, ChatPrivileges
from datetime import datetime, timedelta

# بيانات API الخاصة بك
API_ID = 34257542
API_HASH = "614a1b5c5b712ac6de5530d5c571c42a"
BOT_TOKEN = "7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw"
OWNER_ID = 1486879970

# ملفات لتخزين البيانات
DATA_FILE = "bot_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"responses": {}, "media": {}, "warnings": {}, "stats": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

data = load_data()

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# دالة للتحقق من الصلاحيات (المالك أو المشرفين)
async def is_admin(chat_id, user_id):
    if user_id == OWNER_ID:
        return True
    try:
        member = await app.get_chat_member(chat_id, user_id)
        return member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
    except:
        return False

# --- ميزة الترحيب ---
@app.on_message(filters.new_chat_members)
async def welcome(client, message):
    for member in message.new_chat_members:
        # منشن خفي على شكل إيموجي 🙋🏻‍♂️
        mention_hidden = f"[\u200b](tg://user?id={member.id})🙋🏻‍♂️"
        welcome_text = (
            f"اهلاً بك في فجـر جـديد {mention_hidden}\n\n"
            "خطوة صغيرة اليوم… تصنع فرق كبير غدًا 🌅\n\n"
            "• ممنوع السلبية أو إحباط الآخرين ❌\n"
            "• لا يُسمح بأي محتوى غير لائق 🚫\n"
            "• الاحترام أسلوبنا الدائم 🤝\n"
            "• شارك بما يفيد ويحفّز غيرك 📌\n"
            "• التزامك اليوم هو نجاحك غداً 🌇"
        )
        await message.reply_text(welcome_text)

# --- ميزة المنشن الجماعي ---
@app.on_message(filters.command("all", prefixes="") & filters.group)
async def mention_all(client, message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply_text("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
        return

    text = message.text.split(None, 1)[1] if len(message.command) > 1 else ""
    members = []
    async for member in client.get_chat_members(message.chat.id):
        if not member.user.is_bot:
            members.append(member.user.mention)

    for i in range(0, len(members), 5):
        chunk = members[i:i+5]
        mention_text = f"{text}\n" + " ".join(chunk) if text else " ".join(chunk)
        await client.send_message(message.chat.id, mention_text)
        await asyncio.sleep(0.5) # سرعة الإرسال

# --- ميزة الردود النصية (رد (كلمة) (رد)) ---
@app.on_message(filters.regex(r"^رد \((.*)\) \((.*)\)$") & filters.group)
async def add_response(client, message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply_text("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
        return
    
    key, val = message.matches[0].groups()
    data["responses"][key] = val
    save_data(data)
    await message.reply_text("تمت اضافة النص ✅")

# --- ميزة أضف نص ---
text_waiting = {}
@app.on_message(filters.regex(r"^اضف نص$") & filters.group)
async def add_text_request(client, message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply_text("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
        return
    text_waiting[message.from_user.id] = True
    await message.reply_text("اضف النص المطلوب")

@app.on_message(filters.text & filters.group)
async def save_text_response(client, message):
    user_id = message.from_user.id
    if user_id in text_waiting:
        # هنا يمكن تخصيص كيف يتم حفظ "أضف نص" بشكل عام، سنعتبرها رد ثابت أو رسالة ترحيب إضافية
        # ولكن بناءً على طلبك سأجعلها ميزة لإضافة ردود سريعة
        data["responses"]["محتوى"] = message.text # مثال
        save_data(data)
        del text_waiting[user_id]
        await message.reply_text("تمت اضافة النص المطلوب ✅")
    else:
        # استدعاء معالج الردود المحفوظة إذا لم يكن في وضع الانتظار
        await handle_responses(client, message)

# --- ميزة الحذف والتعديل ---
@app.on_message(filters.regex(r"^(حذف|تعديل) (رد|صورة|فيديو) \((.*)\)$") & filters.group)
async def delete_or_edit(client, message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply_text("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
        return
    
    action, m_type, key = message.matches[0].groups()
    
    if action == "حذف":
        if m_type == "رد" and key in data["responses"]:
            del data["responses"][key]
            await message.reply_text(f"تم حذف الرد ({key}) ✅")
        elif m_type in ["صورة", "فيديو"] and key in data["media"]:
            del data["media"][key]
            await message.reply_text(f"تم حذف الـ {m_type} ({key}) ✅")
        else:
            await message.reply_text("هذا العنصر غير موجود ❌")
        save_data(data)
    
    elif action == "تعديل":
        # للتعديل، نوجه المستخدم لاستخدام أمر الإضافة مرة أخرى (نفس الكلمة المفتاحية ستقوم بالتحديث)
        await message.reply_text(f"لتعديل {m_type} ({key})، قم باستعمال أمر الإضافة الخاص به مرة أخرى بنفس الاسم.")

# --- ميزة إضافة الوسائط (صورة/فيديو (نص)) ---
media_waiting = {}

@app.on_message(filters.regex(r"^(صورة|فيديو) \((.*)\)$") & filters.group)
async def add_media_request(client, message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply_text("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
        return
    
    m_type, text = message.matches[0].groups()
    media_waiting[message.from_user.id] = {"type": m_type, "text": text}
    await message.reply_text(f"حسنا ارسل {'الصورة' if m_type == 'صورة' else 'الفيديو'}")

@app.on_message((filters.photo | filters.video) & filters.group)
async def save_media(client, message):
    user_id = message.from_user.id
    if user_id in media_waiting:
        m_info = media_waiting[user_id]
        file_id = message.photo.file_id if message.photo else message.video.file_id
        data["media"][m_info["text"]] = {"type": m_info["type"], "file_id": file_id}
        save_data(data)
        del media_waiting[user_id]
        await message.reply_text("تمت اضافة الوسائط ✅")

# --- ميزة الكتم والإنذار ---
@app.on_message(filters.reply & filters.group)
async def admin_actions(client, message):
    if message.text == "كتم":
        if not await is_admin(message.chat.id, message.from_user.id):
            await message.reply_text("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
            return
        await client.restrict_chat_member(message.chat.id, message.reply_to_message.from_user.id, ChatPermissions(can_send_messages=False), datetime.now() + timedelta(days=1))
        await message.reply_text(f"تم كتم [{message.reply_to_message.from_user.first_name}](tg://user?id={message.reply_to_message.from_user.id}) لمدة 24 ساعة 🔇")

    elif message.text == "الغاء كتم":
        if not await is_admin(message.chat.id, message.from_user.id):
            await message.reply_text("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
            return
        await client.restrict_chat_member(message.chat.id, message.reply_to_message.from_user.id, ChatPermissions(can_send_messages=True))
        await message.reply_text(f"تم الغاء كتم [{message.reply_to_message.from_user.first_name}](tg://user?id={message.reply_to_message.from_user.id}) ✅")

    elif message.text == "انذار":
        if not await is_admin(message.chat.id, message.from_user.id):
            await message.reply_text("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
            return
        u_id = str(message.reply_to_message.from_user.id)
        data["warnings"][u_id] = data["warnings"].get(u_id, 0) + 1
        count = data["warnings"][u_id]
        if count >= 3:
            await client.restrict_chat_member(message.chat.id, int(u_id), ChatPermissions(can_send_messages=False), datetime.now() + timedelta(hours=6))
            await message.reply_text(f"وصل [{message.reply_to_message.from_user.first_name}](tg://user?id={u_id}) لـ 3 انذارات وتم كتمه 6 ساعات 🔇")
            data["warnings"][u_id] = 0
        else:
            await message.reply_text(f"انذار لـ [{message.reply_to_message.from_user.first_name}](tg://user?id={u_id}) ({count}/3) ⚠️")
        save_data(data)

# --- ميزة الإحصائيات (ا) ---
@app.on_message(filters.regex(r"^ا$") & filters.group)
async def user_stats(client, message):
    u_id = str(message.from_user.id)
    # تحديث عدد الرسائل
    chat_stats = data["stats"].get(str(message.chat.id), {})
    user_info = chat_stats.get(u_id, {"count": 0, "joined": str(datetime.now().date())})
    user_info["count"] += 1
    chat_stats[u_id] = user_info
    data["stats"][str(message.chat.id)] = chat_stats
    save_data(data)

    # حساب الترتيب
    sorted_users = sorted(chat_stats.items(), key=lambda x: x[1]["count"], reverse=True)
    rank = next(i for i, (uid, info) in enumerate(sorted_users, 1) if uid == u_id)

    stats_text = (
        f"👤 الإحصائيات الخاصة بك:\n\n"
        f"📝 عدد الرسائل: {user_info['count']}\n"
        f"📅 تاريخ الانضمام: {user_info['joined']}\n"
        f"🏆 ترتيبك في المتفاعلين: {rank}\n\n"
        f"تحياتنا لك! 🌟"
    )
    
    photos = []
    async for photo in client.get_chat_photos("me", limit=1): # سيتم تعديلها لجلب صورة المستخدم
        photos.append(photo)
    
    # جلب صورة المستخدم
    user_photos = []
    async for p in client.get_chat_photos(message.from_user.id, limit=1):
        user_photos.append(p)
    
    if user_photos:
        await message.reply_photo(user_photos[0].file_id, caption=stats_text)
    else:
        await message.reply_text(stats_text)

# --- معالجة الردود المحفوظة والتحقق من الصلاحيات للأوامر ---
@app.on_message(filters.group & ~filters.command(["start", "all"]))
async def handle_responses(client, message):
    if not message.text: return
    
    # قائمة بالأوامر التي تتطلب صلاحيات
    admin_commands = ["رد (", "صورة (", "فيديو (", "اضف نص", "حذف رد", "حذف صورة", "حذف فيديو", "كتم", "الغاء كتم", "انذار"]
    
    is_cmd = any(message.text.startswith(cmd) for cmd in admin_commands)
    if is_cmd:
        if not await is_admin(message.chat.id, message.from_user.id):
            await message.reply_text("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
            return

    # تحديث الإحصائيات تلقائياً لكل رسالة
    u_id = str(message.from_user.id)
    chat_id = str(message.chat.id)
    if chat_id not in data["stats"]: data["stats"][chat_id] = {}
    user_info = data["stats"][chat_id].get(u_id, {"count": 0, "joined": str(datetime.now().date())})
    user_info["count"] += 1
    data["stats"][chat_id][u_id] = user_info
    save_data(data)

    # الردود النصية
    if message.text in data["responses"]:
        await message.reply_text(data["responses"][message.text])
        return
    
    # الردود بالوسائط
    if message.text in data["media"]:
        m = data["media"][message.text]
        if m["type"] == "صورة":
            await message.reply_photo(m["file_id"])
        else:
            await message.reply_video(m["file_id"])
        return

# تشغيل البوت
app.run()
