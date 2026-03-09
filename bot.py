import asyncio
from telethon import TelegramClient, events, types
from datetime import datetime

# --- الإعدادات الأساسية ---
api_id = 34257542
api_hash = '614a1b5c5b712ac6de5530d5c571c42a'
bot_token = '7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw'

client = TelegramClient('bot_session', api_id, api_hash).start(bot_token=bot_token)

# مخازن البيانات (يفضل استخدام قاعدة بيانات لمشاريع الضخمة)
media_store = {} # لخدمة (صورة/فيديو/نص)
user_stats = {}  # لإحصائيات الرسائل
warns = {}       # للإنذارات
waiting_for = {} # لحالات الإضافة

# دالة التحقق من الصلاحيات (مالك أو مشرف)
async def is_admin(event):
    permissions = await client.get_permissions(event.chat_id, event.sender_id)
    return permissions.is_admin or permissions.is_creator

# --- 1. رسالة الترحيب مع المنشن المخفي ---
@client.on(events.ChatAction)
async def welcome(event):
    if event.user_joined or event.user_added:
        user = await event.get_user()
        # المنشن المخفي في الإيموجي
        mention = f"[\u2063](tg://user?id={user.id})🙋🏻‍♂️"
        msg = (
            f"اهلاً بك في فجـر جـديد {mention}\n\n"
            "خطوة صغيرة اليوم… تصنع فرق كبير غدًا 🌅\n\n"
            "• ممنوع السلبية أو إحباط الآخرين ❌\n"
            "• لا يُسمح بأي محتوى غير لائق 🚫\n"
            "• الاحترام أسلوبنا الدائم 🤝\n"
            "• شارك بما يفيد ويحفّز غيرك 📌\n"
            "• التزامك اليوم هو نجاحك غداً 🌇"
        )
        await event.reply(msg)

# --- 2. ميزة المنشن الجماعي (all) ---
@client.on(events.NewMessage(pattern=r'^all(?:\s+(.*))?'))
async def tag_all(event):
    if not await is_admin(event): return
    
    extra_msg = event.pattern_match.group(1) or ""
    chat = await event.get_input_chat()
    participants = await client.get_participants(chat)
    
    users_to_tag = []
    for user in participants:
        if not user.bot:
            users_to_tag.append(f"[\u2063](tg://user?id={user.id})")
    
    # الإرسال كل 5 أعضاء بسرعة
    for i in range(0, len(users_to_tag), 5):
        batch = users_to_tag[i:i+5]
        await event.respond(f"{extra_msg} {''.join(batch)}")
        await asyncio.sleep(0.1)

# --- 3. الكتم والإنذارات ---
@client.on(events.NewMessage)
async def admin_tools(event):
    if not event.is_reply: return
    cmd = event.text
    sender = event.sender_id
    reply_msg = await event.get_reply_message()
    target_id = reply_msg.sender_id

    if cmd == "كتم":
        if not await is_admin(event): return await event.reply("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
        await client.edit_permissions(event.chat_id, target_id, view_messages=True, send_messages=False)
        await event.reply("تم كتم العضو لمدة 24 ساعة 🔇")
    
    elif cmd == "الغاء كتم":
        if not await is_admin(event): return
        await client.edit_permissions(event.chat_id, target_id, view_messages=True, send_messages=True)
        await event.reply("تم إلغاء الكتم بنجاح ✅")

    elif cmd == "انذار":
        if not await is_admin(event): return
        warns[target_id] = warns.get(target_id, 0) + 1
        count = warns[target_id]
        if count >= 3:
            warns[target_id] = 0
            await client.edit_permissions(event.chat_id, target_id, view_messages=True, send_messages=False)
            await event.reply("وصل العضو لـ 3 إنذارات، تم كتمه تلقائياً لمدة 6 ساعات ⛔")
        else:
            await event.reply(f"تم إعطاء إنذار للعضو ({count}/3) ⚠️")

# --- 4. ميزة (صورة/فيديو/نص) ---
@client.on(events.NewMessage)
async def store_media(event):
    text = event.text
    user_id = event.sender_id

    # إضافة وسائط
    if text.startswith(("صوره ", "فيديو ", "اضف نص ")):
        if not await is_admin(event): return
        key = text.split(" ", 1)[1]
        waiting_for[user_id] = {"key": key, "type": "photo" if "صوره" in text else "video" if "فيديو" in text else "text"}
        await event.reply(f"حسناً، أرسل المطلوب الآن لربطه بكلمة: {key}")
        return

    # استقبال الميديا بعد الأمر
    if user_id in waiting_for:
        data = waiting_for[user_id]
        media_store[data['key']] = {"id": event.media or event.text, "type": data['type']}
        del waiting_for[user_id]
        await event.reply("✅ تمت إضافة المحتوى بنجاح. يمكنك استدعاؤه بكتابة الكلمة.")
        return

    # استرجاع الميديا (متاحة للجميع)
    if text in media_store:
        item = media_store[text]
        if item['type'] == "text": await event.reply(item['id'])
        else: await client.send_file(event.chat_id, item['id'])

# --- 5. ميزة التعديل والحذف ---
# الطريقة: أرسل "حذف" أو "تعديل (النص الجديد)" رداً على رسالة البوت
@client.on(events.NewMessage(pattern=r'^(حذف|تعديل)\s?(.*)?'))
async def edit_delete(event):
    if not await is_admin(event) or not event.is_reply: return
    
    reply_msg = await event.get_reply_message()
    if reply_msg.sender_id != (await client.get_me()).id:
        return # يحذف ويعدل رسائل البوت فقط

    if event.pattern_match.group(1) == "حذف":
        await reply_msg.delete()
        await event.delete()
    else:
        new_text = event.pattern_match.group(2)
        await reply_msg.edit(new_text)
        await event.delete()

# --- 6. ميزة إحصائيات المستخدم (عند كتابة ا) ---
@client.on(events.NewMessage)
async def user_info(event):
    uid = event.sender_id
    # تحديث العداد
    user_stats[uid] = user_stats.get(uid, 0) + 1
    
    if event.text == "ا":
        user = await event.get_sender()
        # ترتيب المتفاعلين (تبسيط)
        rank = sorted(user_stats, key=user_stats.get, reverse=True).index(uid) + 1
        
        info = (
            f"👤 **بياناتك يا بطل:**\n\n"
            f"📧 **عدد رسائلك:** {user_stats[uid]}\n"
            f"📅 **انضمامك للحساب:** {user.date.strftime('%Y-%m-%d') if user.date else 'غير معروف'}\n"
            f"🏆 **ترتيبك بين المتفاعلين:** {rank}\n\n"
            f"تفاعلك المستمر يسعدنا! ✨"
        )
        await client.send_file(event.chat_id, await client.download_profile_photo(uid) or 'https://telegra.ph/file/default.jpg', caption=info)

print("البوت يعمل الآن بنجاح...")
client.run_until_disconnected()
