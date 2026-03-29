# -*- coding: utf-8 -*-
from telethon import TelegramClient, events
import asyncio
import json
import os

# --- 1. الإعدادات الأساسية ---
api_id = 34257542
api_hash = '614a1b5c5b712ac6de5530d5c571c42a'
bot_token = '7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw'
owner_id = 1486879970

client = TelegramClient('bot_session', api_id, api_hash).start(bot_token=bot_token)

DATA_FILE = 'bot_data.json'

# تحميل البيانات
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        db = json.load(f)
else:
    db = {"responses": {}, "media": {}, "stats": {}}

def save_db():
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=4)

last_actions = {}

# --- 2. التحقق من الأدمن ---
async def is_admin(event):
    if event.sender_id == owner_id:
        return True
    if event.is_private:
        return False
    try:
        perms = await client.get_permissions(event.chat_id, event.sender_id)
        return perms.is_admin
    except:
        return False

# --- 3. الترحيب ---
@client.on(events.ChatAction)
async def welcome(event):
    if event.user_joined:
        user = await event.get_user()
        await event.reply(
            f"اهلاً بك في فجـر جـديد [\u200b](tg://user?id={user.id}) 🙋🏻‍♂️\n\n"
            "خطوة صغيرة اليوم… تصنع فرق كبير غدًا 🌅\n\n"
            "• الاحترام أسلوبنا 🤝\n"
            "• شارك بما يفيد 📌"
        )

# --- 4. إضافة رد نصي ---
@client.on(events.NewMessage(pattern=r'^رد\s+\((.*?)\)\s+\((.*)\)'))
async def add_text_reply(event):
    if not await is_admin(event): return
    
    word = event.pattern_match.group(1).strip()
    reply = event.pattern_match.group(2).strip()

    db["responses"][word] = reply
    save_db()

    msg = await event.reply(f"✅ تم إضافة رد: ({word})")
    last_actions[msg.id] = ("text", word)

# --- 5. إضافة ميديا (FIXED) ---
@client.on(events.NewMessage(pattern=r'^(صوره|فيديو)\s+\((.*)\)'))
async def add_media_reply(event):
    if not await is_admin(event): return
    
    word = event.pattern_match.group(2).strip()

    await event.reply("📩 رد على هذه الرسالة بالميديا المطلوبة")

    def check(m):
        return m.sender_id == event.sender_id and m.is_reply

    try:
        msg = await client.wait_for(events.NewMessage(func=check), timeout=60)

        reply_msg = await msg.get_reply_message()

        if not reply_msg or not reply_msg.media:
            await msg.reply("❌ لازم ترد بميديا")
            return

        file = await client.download_media(reply_msg.media, file=bytes)

        db["media"][word] = file.hex()
        save_db()

        done = await msg.reply(f"✅ تم ربط الميديا بـ ({word})")
        last_actions[done.id] = ("media", word)

    except asyncio.TimeoutError:
        await event.reply("⌛ انتهى الوقت")

# --- 6. حذف ---
@client.on(events.NewMessage(pattern='^حذف$'))
async def delete_reply(event):
    if not await is_admin(event) or not event.is_reply:
        return

    reply = await event.get_reply_message()

    if reply.id in last_actions:
        t, key = last_actions[reply.id]

        if t == "text" and key in db["responses"]:
            del db["responses"][key]

        if t == "media" and key in db["media"]:
            del db["media"][key]

        save_db()
        await event.reply(f"🗑️ تم حذف ({key})")

# --- 7. النظام الأساسي ---
@client.on(events.NewMessage)
async def handler(event):
    if not event.text:
        return

    uid = str(event.sender_id)
    db["stats"][uid] = db["stats"].get(uid, 0) + 1

    # --- ميزة ا (FIXED + أسرع) ---
    if event.text.strip() == "ا":
        user = await event.get_sender()
        count = db["stats"].get(uid, 0)

        text = f"👤 معلوماتك:\n\n📨 عدد رسائلك: {count}"

        try:
            photo = await client.download_profile_photo(user.id)
            if photo:
                await client.send_file(event.chat_id, photo, caption=text)
            else:
                await event.reply(text)
        except:
            await event.reply(text)

    # --- الرد النصي ---
    if event.text in db["responses"]:
        await event.reply(db["responses"][event.text])

    # --- الرد الميديا ---
    if event.text in db["media"]:
        file = bytes.fromhex(db["media"][event.text])
        await client.send_file(event.chat_id, file, reply_to=event.id)

    save_db()

# --- المنشن الجماعي (لم يتم التعديل عليه) ---
@client.on(events.NewMessage(pattern=r'(?i)^all(?:\s+(.*))?'))
async def mention_all(event):
    if not await is_admin(event): return
    extra = event.pattern_match.group(1) or ""
    mentions = [f"[{u.first_name}](tg://user?id={u.id})" async for u in client.iter_participants(event.chat_id) if not u.bot]
    for i in range(0, len(mentions), 5):
        await client.send_message(event.chat_id, f"{extra}\n" + " ".join(mentions[i:i+5]))
        await asyncio.sleep(0.5)

print("🚀 البوت شغال 100% بدون تعليق")
client.run_until_disconnected()
