from telethon import TelegramClient, events, functions, types
import asyncio
import datetime
import re

# --- الإعدادات الأساسية ---
# ملاحظة: يفضل استخدام متغيرات البيئة في الإنتاج
api_id = 34257542
api_hash = '614a1b5c5b712ac6de5530d5c571c42a'
bot_token = '7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw'
owner_id = 1486879970

client = TelegramClient('bot_session', api_id, api_hash).start(bot_token=bot_token)

# قواعد بيانات مؤقتة
custom_responses = {}  # للنصوص: {الكلمة: الرد}
custom_media = {}      # للميديا: {الكلمة: (نوع_الميديا, ميديا_اوبجكت)}
last_actions = {}      # لتتبع آخر العمليات للحذف: {رسالة_البوت_id: (نوع_العملية, الكلمة_المفتاحية)}
warns = {}             # الإنذارات
stats = {}             # الإحصائيات

# دالة التحقق من الصلاحيات
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

# --- 2. ميزة المنشن الجماعي (all) ---
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

# --- 3. إضافة رد نصي ---
# الصيغة: رد (كلمة) (رد)
@client.on(events.NewMessage(pattern=r'^رد\s+\((.*?)\)\s+\((.*)\)'))
async def add_text_reply(event):
    if not await is_admin(event): return
    word = event.pattern_match.group(1)
    reply = event.pattern_match.group(2)
    custom_responses[word] = reply
    sent_msg = await event.reply(f"تمت إضافة الرد بنجاح ✅\nالكلمة: {word}\nالرد: {reply}")
    # تخزين العملية لإمكانية الحذف لاحقاً
    last_actions[sent_msg.id] = ('text', word)

# --- 4. إضافة ميديا (صورة/فيديو) ---
# الصيغة: صوره (كلمة) أو فيديو (كلمة)
@client.on(events.NewMessage(pattern=r'^(صوره|فيديو)\s+\((.*)\)'))
async def add_media_reply(event):
    if not await is_admin(event): return
    media_type = event.pattern_match.group(1)
    trigger_text = event.pattern_match.group(2)
    
    async with client.conversation(event.chat_id) as conv:
        prompt = await conv.send_message(f"حسناً، أرسل ال{media_type} الآن.")
        response = await conv.get_response()
        
        if response.media:
            custom_media[trigger_text] = (media_type, response.media)
            success_msg = await response.reply(f"تمت إضافة ال{media_type} بنجاح ✅\nالكلمة: {trigger_text}")
            last_actions[success_msg.id] = ('media', trigger_text)
        else:
            await response.reply("خطأ: لم يتم إرسال ميديا. تم إلغاء العملية.")

# --- 5. ميزة الحذف الذكي ---
@client.on(events.NewMessage(pattern='^حذف$'))
async def smart_delete(event):
    if not await is_admin(event): return
    if not event.is_reply:
        return await event.reply("يرجى عمل ريبلاي على رسالة البوت المتعلقة بالعملية لحذفها.")
    
    reply_msg = await event.get_reply_message()
    
    # التحقق إذا كانت الرسالة مسجلة في العمليات الأخيرة
    if reply_msg.id in last_actions:
        action_type, key = last_actions[reply_msg.id]
        
        if action_type == 'text':
            if key in custom_responses:
                del custom_responses[key]
                await event.reply(f"تم حذف الرد النصي للكلمة: ({key})")
        elif action_type == 'media':
            if key in custom_media:
                del custom_media[key]
                await event.reply(f"تم حذف ميديا الكلمة: ({key})")
        
        # حذف سجل العملية
        del last_actions[reply_msg.id]
        
        # حذف الرسائل المتعلقة (رسالة المستخدم، رسالة البوت، ورسالة طلب الحذف)
        try:
            await client.delete_messages(event.chat_id, [event.id, reply_msg.id, reply_msg.reply_to_msg_id])
        except:
            pass
    else:
        # إذا لم تكن في السجل، فقط احذف الرسالة التي تم عمل ريبلاي عليها ورسالة الحذف
        try:
            await client.delete_messages(event.chat_id, [event.id, reply_msg.id])
        except:
            pass

# --- 6. معالج الردود الذكي ---
@client.on(events.NewMessage)
async def dynamic_replies(event):
    if event.text in custom_responses:
        await event.reply(custom_responses[event.text])
    
    if event.text in custom_media:
        m_type, m_data = custom_media[event.text]
        await client.send_file(event.chat_id, m_data, reply_to=event.id)

# --- 7. ميزات الإشراف والملف الشخصي (مبسطة) ---
@client.on(events.NewMessage)
async def other_features(event):
    # تحديث الإحصائيات
    stats[event.sender_id] = stats.get(event.sender_id, 0) + 1
    
    # ملف شخصي (عند كتابة "ا")
    if event.text == "ا":
        user = await event.get_sender()
        msg_count = stats.get(user.id, 0)
        caption = f"✨ **ملفك الشخصي** ✨\n\n✉️ رسائلك: `{msg_count}`"
        photo = await client.download_profile_photo(user.id)
        if photo:
            await client.send_file(event.chat_id, photo, caption=caption)
        else:
            await event.reply(caption)

print("البوت المحسن يعمل الآن...")
client.run_until_disconnected()
