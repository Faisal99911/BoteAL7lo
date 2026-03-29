# -*- coding: utf-8 -*-
from telethon import TelegramClient, events, functions, types
import asyncio
import datetime
import json
import os

# --- 1. الإعدادات الأساسية ---
api_id = 34257542
api_hash = '614a1b5c5b712ac6de5530d5c571c42a'
bot_token = '7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw'
owner_id = 1486879970

client = TelegramClient('bot_session', api_id, api_hash).start(bot_token=bot_token)

# ملفات حفظ البيانات لضمان عدم ضياعها عند إعادة التشغيل
DATA_FILE = 'bot_data.json'

# تحميل البيانات أو إنشاؤها
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        db = json.load(f)
else:
    db = {"responses": {}, "stats": {}, "report_groups": []}

def save_db():
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

# تخزين مؤقت للميديا (لأن الميديا لا تُحفظ كـ JSON بسهولة)
custom_media = {} 
last_actions = {} 

# --- 2. دالة التحقق من الصلاحيات ---
async def is_admin(event):
    if event.sender_id == owner_id: return True
    if event.is_private: return False
    try:
        permissions = await client.get_permissions(event.chat_id, event.sender_id)
        return permissions.is_admin
    except:
        return False

# --- 3. الترحيب (محسن) ---
@client.on(events.ChatAction)
async def welcome(event):
    if event.user_joined:
        user = await event.get_user()
        welcome_msg = (
            f"اهلاً بك في فجـر جـديد [\u200b](tg://user?id={user.id}) 🙋🏻‍♂️\n\n"
            "خطوة صغيرة اليوم… تصنع فرق كبير غدًا 🌅\n\n"
            "• الاحترام أسلوبنا الدائم 🤝\n"
            "• شارك بما يفيد ويحفّز غيرك 📌"
        )
        await event.reply(welcome_msg)

# --- 4. إضافة رد نصي (محسن) ---
# الصيغة: رد (الكلمة) (الرد)
@client.on(events.NewMessage(pattern=r'^رد\s+\((.*?)\)\s+\((.*)\)'))
async def add_text_reply(event):
    if not await is_admin(event): return
    word, reply = event.pattern_match.group(1), event.pattern_match.group(2)
    db["responses"][word] = reply
    save_db()
    sent = await event.reply(f"✅ تم إضافة الرد النصي لـ: **{word}**")
    last_actions[sent.id] = ('text', word)

# --- 5. إضافة ميديا (محسن جداً) ---
# الصيغة: صوره (الكلمة) أو فيديو (الكلمة)
@client.on(events.NewMessage(pattern=r'^(صوره|فيديو)\s+\((.*)\)'))
async def add_media_reply(event):
    if not await is_admin(event): return
    m_type, word = event.pattern_match.group(1), event.pattern_match.group(2)
    
    async with client.conversation(event.chat_id) as conv:
        await conv.send_message(f"📷 أرسل الـ {m_type} الآن المرتبط بكلمة ({word})")
        msg = await conv.get_response()
        if msg.media:
            custom_media[word] = msg.media
            sent = await msg.reply(f"✅ تم ربط الـ {m_type} بكلمة: **{word}**")
            last_actions[sent.id] = ('media', word)
        else:
            await conv.send_message("❌ خطأ: لم ترسل ميديا. تم الإلغاء.")

# --- 6. الحذف الذكي (محسن) ---
@client.on(events.NewMessage(pattern='^حذف$'))
async def smart_delete(event):
    if not await is_admin(event) or not event.is_reply: return
    reply_msg = await event.get_reply_message()
    
    if reply_msg.id in last_actions:
        a_type, key = last_actions[reply_msg.id]
        if a_type == 'text' and key in db["responses"]:
            del db["responses"][key]
            save_db()
        elif a_type == 'media' and key in custom_media:
            del custom_media[key]
        
        await event.reply(f"🗑️ تم حذف الرد الخاص بـ: ({key})")
        await client.delete_messages(event.chat_id, [event.id, reply_msg.id])
    else:
        # حذف عادي للرسالة إذا لم تكن في السجل
        await client.delete_messages(event.chat_id, [event.id, reply_msg.id])

# --- 7. معالج الردود والملف الشخصي (دمج ذكي) ---
@client.on(events.NewMessage)
async def global_handler(event):
    if not event.text: return
    
    # 1. الإحصائيات (تحديث في الخلفية)
    uid = str(event.sender_id)
    db["stats"][uid] = db["stats"].get(uid, 0) + 1
    
    # 2. أمر الملف الشخصي "ا"
    if event.text == "ا":
        user = await event.get_sender()
        count = db["stats"].get(uid, 0)
        caption = f"👤 **معلوماتك**\n\n📝 عدد رسائلك: `{count}`"
        try:
            photo = await client.download_profile_photo(user.id)
            await client.send_file(event.chat_id, photo, caption=caption) if photo else await event.reply(caption)
        except:
            await event.reply(caption)

    # 3. الردود الذكية
    if event.text in db["responses"]:
        await event.reply(db["responses"][event.text])
    
    if event.text in custom_media:
        await client.send_file(event.chat_id, custom_media[event.text], reply_to=event.id)

# --- المنشن الجماعي (كما هو بناءً على طلبك) ---
@client.on(events.NewMessage(pattern=r'(?i)^all(?:\s+(.*))?'))
async def mention_all(event):
    if not await is_admin(event): return
    extra = event.pattern_match.group(1) or ""
    mentions = [f"[{u.first_name}](tg://user?id={u.id})" async for u in client.iter_participants(event.chat_id) if not u.bot]
    for i in range(0, len(mentions), 5):
        await client.send_message(event.chat_id, f"{extra}\n" + " ".join(mentions[i:i+5]))
        await asyncio.sleep(0.5)

print("🚀 البوت المحسن يعمل الآن واستقرار البيانات مفعل...")
client.run_until_disconnected()
