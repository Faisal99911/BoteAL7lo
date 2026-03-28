from telethon import TelegramClient, events, functions, types
import asyncio
import datetime
import json # Added for JSON persistence

# --- الإعدادات الأساسية ---
api_id = 34257542
api_hash = '614a1b5c5b712ac6de5530d5c571c42a'
bot_token = '7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw'
owner_id = 1486879970

# ملفات حفظ البيانات للردود المخصصة
CUSTOM_RESPONSES_FILE = 'custom_responses.json'
CUSTOM_MEDIA_FILE = 'custom_media.json'
LAST_BOT_REPLY_FILE = 'last_bot_reply.json' # لتتبع رسائل البوت للحذف الذكي

# قواعد بيانات مؤقتة (يفضل استخدام SQL في المشاريع الضخمة)
custom_responses = {} # للنصوص
custom_media = {}     # للصور والفيديوهات
last_bot_replies = {} # {bot_message_id: {'trigger': 'text', 'user_msg_id': None, 'type': 'text' or 'media'}}
warns = {}            # الإنذارات
stats = {}            # الإحصائيات (عدد الرسائل)
group_members = {}    # لترتيب المتفاعلين

client = TelegramClient('bot_session', api_id, api_hash)

async def load_custom_data():
    global custom_responses, custom_media, last_bot_replies
    try:
        with open(CUSTOM_RESPONSES_FILE, 'r', encoding='utf-8') as f:
            custom_responses = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        custom_responses = {}
    
    try:
        with open(CUSTOM_MEDIA_FILE, 'r', encoding='utf-8') as f:
            custom_media = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        custom_media = {}

    try:
        with open(LAST_BOT_REPLY_FILE, 'r', encoding='utf-8') as f:
            loaded_replies = json.load(f)
            # Convert keys back to int if they were stored as strings
            last_bot_replies = {int(k): v for k, v in loaded_replies.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        last_bot_replies = {}

    print("تم تحميل بيانات الردود المخصصة بنجاح.")

async def save_custom_data():
    try:
        with open(CUSTOM_RESPONSES_FILE, 'w', encoding='utf-8') as f:
            json.dump(custom_responses, f, ensure_ascii=False, indent=4)
        with open(CUSTOM_MEDIA_FILE, 'w', encoding='utf-8') as f:
            json.dump(custom_media, f, ensure_ascii=False, indent=4)
        with open(LAST_BOT_REPLY_FILE, 'w', encoding='utf-8') as f:
            json.dump(last_bot_replies, f, ensure_ascii=False, indent=4)
        print("تم حفظ بيانات الردود المخصصة بنجاح.")
    except Exception as e:
        print(f"خطأ أثناء حفظ بيانات الردود المخصصة: {e}")

# دالة التحقق من الصلاحيات (مالك أو مشرف)
async def is_admin(event):
    if event.sender_id == owner_id:
        return True
    permissions = await client.get_permissions(event.chat_id, event.sender_id)
    return permissions.is_admin

# --- 1. رسالة الترحيب مع المنشن المخفي ---
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

# --- 2. ميزة المنشن الجماعي (all) ---
@client.on(events.NewMessage(pattern=r'(?i)^(all)(?:\s+(.*))?'))
async def mention_all(event):
    if not await is_admin(event):
        return await event.reply("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
    
    extra_text = event.pattern_match.group(2) or ""
    mentions = []
    async for user in client.iter_participants(event.chat_id):
        if not user.bot:
            mentions.append(f"[{user.first_name}](tg://user?id={user.id})")
    
    for i in range(0, len(mentions), 5):
        chunk = mentions[i:i+5]
        msg = f"{extra_text}\n" + " ".join(chunk)
        await client.send_message(event.chat_id, msg, parse_mode='md') # Added parse_mode for mentions
        await asyncio.sleep(0.5) # سرعة عالية مع تجنب الحظر

# --- 3. ميزة الردود النصية (رد السلام عليكم وعليكم السلام) ---
@client.on(events.NewMessage(pattern=r'^رد \((.*)\) \((.*)\)'))
async def add_text_reply(event):
    if not await is_admin(event): return
    word = event.pattern_match.group(1)
    reply = event.pattern_match.group(2)
    custom_responses[word] = reply
    await save_custom_data()
    await event.reply("تمت اضافة النص ✅")

# --- 4. ميزة الميديا (صورة/فيديو + نص) ---
@client.on(events.NewMessage(pattern=r'^(صوره|فيديو) \((.*)\)'))
async def add_media_step1(event):
    if not await is_admin(event): return
    media_type = event.pattern_match.group(1)
    trigger_text = event.pattern_match.group(2)
    
    async with client.conversation(event.chat_id) as conv:
        await conv.send_message(f"حسنا ارسل ال{media_type}")
        response = await conv.get_response()
        if response.media:
            # Telethon media objects are not directly JSON serializable.
            # We need to store file_id or similar if we want persistence.
            custom_media[trigger_text] = {'media_id': response.media.id, 'media_type': media_type, 'file_reference': response.media.file_reference.decode('utf-8') if response.media.file_reference else None, 'mime_type': response.media.mime_type, 'duration': getattr(response.media, 'duration', None), 'width': getattr(response.media, 'w', None), 'height': getattr(response.media, 'h', None)}
            await save_custom_data()
            await response.reply(f"تمت اضافة ال{media_type} ✅")

# --- 5. ميزة الكتم والإنذار ---
@client.on(events.NewMessage)
async def moderation_tools(event):
    if not event.is_reply: return
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

# --- 6. ميزة الملف الشخصي (عند كتابة "ا") ---
@client.on(events.NewMessage(pattern=r'^[اأإآ]$'))
async def profile_stats(event):
    user = await event.get_sender()
    user_id = user.id
    
    # تحديث الإحصائيات
    msg_count = stats.get(user_id, 0) + 1
    stats[user_id] = msg_count
    
    # الترتيب
    sorted_users = sorted(stats.items(), key=lambda x: x[1], reverse=True)
    rank = next((i + 1 for i, (uid, count) in enumerate(sorted_users) if uid == user_id), 1)
    
    # محاولة الحصول على تاريخ انضمام المستخدم
    try:
        user_entity = await client.get_entity(user_id)
        join_date = user_entity.date.strftime("%Y-%m-%d")
    except Exception:
        join_date = "غير متوفر"
    
    # الصيغة المطلوبة التي حددتها
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

# --- 7. ميزة الحذف الذكي ---
@client.on(events.NewMessage(pattern=r'^(حذف)$', incoming=True))
async def smart_delete_handler(event):
    if not event.is_reply: return
    reply_msg = await event.get_reply_message()

    if reply_msg.sender_id == (await client.get_me()).id: # إذا كان الرد على رسالة البوت
        bot_msg_id = reply_msg.id
        if bot_msg_id in last_bot_replies:
            data_to_delete = last_bot_replies.pop(bot_msg_id)
            trigger_text = data_to_delete['trigger']
            user_msg_id = data_to_delete['user_msg_id']
            response_type = data_to_delete['type']

            # حذف الرد من قاعدة البيانات
            if response_type == 'text' and trigger_text in custom_responses:
                del custom_responses[trigger_text]
            elif response_type == 'media' and trigger_text in custom_media:
                del custom_media[trigger_text]
            await save_custom_data()

            # حذف الرسائل المتعلقة بالعملية
            try:
                await client.delete_messages(event.chat_id, [event.id, reply_msg.id, user_msg_id])
                print(f"تم حذف الرد '{trigger_text}' والرسائل المتعلقة به.")
            except Exception as e:
                print(f"خطأ أثناء حذف الرسائل: {e}")
                await event.reply("حدث خطأ أثناء حذف الرسائل. ❌")
        else:
            await event.reply("لا يمكنني العثور على بيانات هذا الرد للحذف. ℹ️")

# --- 8. معالج الردود الذكي (نصوص + ميديا) ---
@client.on(events.NewMessage)
async def dynamic_replies(event):
    # تحديث العداد لكل رسالة
    stats[event.sender_id] = stats.get(event.sender_id, 0) + 1
    
    # ردود النصوص
    if event.text in custom_responses:
        bot_msg = await event.reply(custom_responses[event.text])
        last_bot_replies[bot_msg.id] = {'trigger': event.text, 'user_msg_id': event.id, 'type': 'text'}
        await save_custom_data()
    
    # ردود الميديا
    if event.text in custom_media:
        media_info = custom_media[event.text]
        # Reconstruct InputMedia based on stored info
        if media_info['media_type'] == 'صوره':
            input_media = types.InputMediaPhoto(id=media_info['media_id'], file_reference=bytes(media_info['file_reference'], 'utf-8') if media_info['file_reference'] else None, ttl_seconds=None)
        elif media_info['media_type'] == 'فيديو':
            input_media = types.InputMediaDocument(id=media_info['media_id'], file_reference=bytes(media_info['file_reference'], 'utf-8') if media_info['file_reference'] else None, mime_type=media_info['mime_type'], duration=media_info['duration'], w=media_info['width'], h=media_info['height'], ttl_seconds=None)
        else:
            input_media = None # Should not happen

        if input_media:
            bot_msg = await client.send_file(event.chat_id, input_media, reply_to=event.id)
            last_bot_replies[bot_msg.id] = {'trigger': event.text, 'user_msg_id': event.id, 'type': 'media'}
            await save_custom_data()


async def main():
    await load_custom_data() # تحميل البيانات عند بدء التشغيل
    await client.start(bot_token=bot_token)
    print("البوت يعمل الآن بنجاح...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
