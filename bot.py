from telethon import TelegramClient, events, functions, types
import asyncio
import datetime
import re

# --- الإعدادات الأساسية ---
api_id = 34257542
api_hash = '614a1b5c5b712ac6de5530d5c571c42a'
bot_token = '7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw'
owner_id = 1486879970

client = TelegramClient('bot_session', api_id, api_hash).start(bot_token=bot_token)

custom_responses = {} 
custom_media = {}     
warns = {}            
stats = {}            

async def is_admin(event):
    if event.sender_id == owner_id:
        return True
    try:
        permissions = await client.get_permissions(event.chat_id, event.sender_id)
        return permissions.is_admin
    except:
        return False

# --- 1. رسالة الترحيب ---
@client.on(events.ChatAction)
async def welcome(event):
    if event.user_joined:
        user = await event.get_user()
        welcome_msg = (
            f"اهلاً بك في فجـر جـديد [\u200b](tg://user?id={user.id}) 🙋🏻‍♂️\n\n"
            "خطوة صغيرة اليوم… تصنع فرق كبير غدًا 🌅\n\n"
            "• ممنوع السلبية أو إحباط الآخرين ❌\n"
            "• لا يُسمح بأي محتوى غير لائق 🚫\n"
            "• الاحترام أسلوبنا الدائم 🤝\n"
            "• شارك بما يفيد ويحفّز غيرك 📌\n"
            "• التزامك اليوم هو نجاحك غداً 🌇"
        )
        await event.reply(welcome_msg)

# --- 2. ميزة المنشن الجماعي ---
@client.on(events.NewMessage(pattern=r'(?i)^all(?:\s+(.*))?'))
async def mention_all(event):
    if not await is_admin(event):
        return await event.reply("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
    
    extra_text = event.pattern_match.group(1) or ""
    mentions = []
    async for user in client.iter_participants(event.chat_id):
        if not user.bot:
            mentions.append(f"[{user.first_name}](tg://user?id={user.id})")
    
    for i in range(0, len(mentions), 5):
        chunk = mentions[i:i+5]
        msg = f"{extra_text}\n" + " ".join(chunk)
        await client.send_message(event.chat_id, msg)
        await asyncio.sleep(0.5)

# --- 3. ميزة الردود النصية (تم التعديل لحل مشكلة المسافات) ---
@client.on(events.NewMessage(pattern=r'^رد\s*\((.*)\)\s*\((.*)\)'))
async def add_text_reply(event):
    if not await is_admin(event): return
    # استخدام .strip() لإزالة المسافات الزائدة من البداية والنهاية
    word = event.pattern_match.group(1).strip()
    reply = event.pattern_match.group(2).strip()
    custom_responses[word] = reply
    await event.reply(f"تمت اضافة الرد للكلمة: **{word}** ✅")

# --- 4. ميزة الميديا ---
@client.on(events.NewMessage(pattern=r'^(صوره|فيديو)\s+(.*)'))
async def add_media_step1(event):
    if not await is_admin(event): return
    media_type = event.pattern_match.group(1)
    trigger_text = event.pattern_match.group(2).strip()
    
    async with client.conversation(event.chat_id) as conv:
        await conv.send_message(f"حسنا ارسل ال{media_type}")
        response = await conv.get_response()
        if response.media:
            custom_media[trigger_text] = response.media
            await response.reply(f"تمت اضافة ال{media_type} للكلمة: **{trigger_text}** ✅")

# --- 5. ميزة الكتم والإنذار ---
@client.on(events.NewMessage)
async def moderation_tools(event):
    if not event.is_reply or not event.text: return
    reply_msg = await event.get_reply_message()
    user_id = reply_msg.sender_id

    if event.text == "كتم":
        if not await is_admin(event): return
        await client.edit_permissions(event.chat_id, user_id, until_date=datetime.timedelta(days=1), send_messages=False)
        await event.reply("تم كتم العضو لمدة 24 ساعة 🔇")
    
    elif event.text == "الغاء كتم":
        if not await is_admin(event): return
        await client.edit_permissions(event.chat_id, user_id, send_messages=True)
        await event.reply("تم الغاء الكتم ✅")

    elif event.text == "انذار":
        if not await is_admin(event): return
        warns[user_id] = warns.get(user_id, 0) + 1
        count = warns[user_id]
        if count >= 3:
            await client.edit_permissions(event.chat_id, user_id, until_date=datetime.timedelta(hours=6), send_messages=False)
            await event.reply(f"الإنذار 3/3.. تم كتمك 6 ساعات تلقائياً ⚠️")
            warns[user_id] = 0
        else:
            await event.reply(f"تم إعطاء انذار للعضو ({count}/3) ⚠️")

# --- 6. ميزة الملف الشخصي (بالصيغة المطلوبة) ---
@client.on(events.NewMessage(pattern=r'^[اأإآ]$'))
async def profile_stats(event):
    user = await event.get_sender()
    user_id = user.id
    msg_count = stats.get(user_id, 0) + 1
    stats[user_id] = msg_count
    
    sorted_users = sorted(stats.items(), key=lambda x: x[1], reverse=True)
    rank = next((i + 1 for i, (uid, count) in enumerate(sorted_users) if uid == user_id), 1)
    
    try:
        user_entity = await client.get_entity(user_id)
        join_date = user_entity.date.strftime("%Y-%m-%d")
    except:
        join_date = "غير متوفر"
    
    caption = (
        f"✨ **ملفك الشخصي في فجـر جـديد** ✨\n\n"
        f"**إحصائياتك:**\n"
        f"  ✉️ عدد رسائلك: `{msg_count}`\n"
        f"  🏆 ترتيبك في المتفاعلين: `{rank}`\n"
        f"  📅 تاريخ انضمامك: `{join_date}`\n\n"
        f"استمر في التفاعل والمشاركة لتصنع فرقاً وتزيد من ترتيبك! 🚀"
    )
    
    photo = await client.download_profile_photo(user_id)
    if photo:
        await client.send_file(event.chat_id, photo, caption=caption)
    else:
        await event.reply(caption)

# --- 7. ميزة الحذف والتعديل ---
@client.on(events.NewMessage(pattern='^كيف احذف$'))
async def help_edit(event):
    help_text = (
        "💡 **طريقة الحذف والتعديل:**\n\n"
        "1️⃣ **للتعديل:** اضغط مطولاً على رسالتك واختر (Edit) أو (تعديل).\n"
        "2️⃣ **للحذف:** اضغط مطولاً على الرسالة واختر (Delete) ثم حدد 'حذف للكل'.\n\n"
        "ملاحظة: يمكنك تعديل رسائلك خلال 48 ساعة فقط."
    )
    await event.reply(help_text)

# --- معالج الردود الذكي (تم تحسينه ليتجاهل المسافات) ---
@client.on(events.NewMessage)
async def dynamic_replies(event):
    if not event.text: return
    
    # تحديث العداد
    stats[event.sender_id] = stats.get(event.sender_id, 0) + 1
    
    # تنظيف النص المدخل من المسافات للمقارنة
    input_text = event.text.strip()
    
    # ردود النصوص
    if input_text in custom_responses:
        await event.reply(custom_responses[input_text])
    
    # ردود الميديا
    if input_text in custom_media:
        await client.send_file(event.chat_id, custom_media[input_text], reply_to=event.id)

print("البوت يعمل الآن بنجاح...")
client.run_until_disconnected()
