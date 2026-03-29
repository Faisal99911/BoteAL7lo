# -*- coding: utf-8 -*-
from telethon import TelegramClient, events
import asyncio
import json
import os
import datetime

# =========================
# 1. الإعدادات الأساسية
# =========================

api_id = 34257542
api_hash = '614a1b5c5b712ac6de5530d5c571c42a'
bot_token = '7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw'
owner_id = 1486879970

client = TelegramClient('bot_session', api_id, api_hash).start(bot_token=bot_token)

DATA_FILE = 'bot_data.json'

# =========================
# 2. قاعدة البيانات
# =========================

def load_db():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return create_empty_db()
    return create_empty_db()

def create_empty_db():
    return {
        "responses": {},
        "media": {},
        "stats": {},
        "meta": {
            "created": str(datetime.datetime.now())
        }
    }

db = load_db()

def save_db():
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(db, f, ensure_ascii=False, indent=4)
    except:
        pass

# =========================
# 3. أدوات مساعدة
# =========================

last_actions = {}

def clean_text(text):
    if not text:
        return ""
    return text.strip()

def increase_user_stats(uid):
    uid = str(uid)
    if uid not in db["stats"]:
        db["stats"][uid] = 0
    db["stats"][uid] += 1

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

# =========================
# 4. الترحيب
# =========================

@client.on(events.ChatAction)
async def welcome(event):
    if event.user_joined:
        user = await event.get_user()
        msg = (
            f"اهلاً بك في فجـر جـديد [\u200b](tg://user?id={user.id}) 🙋🏻‍♂️\n\n"
            "خطوة صغيرة اليوم… تصنع فرق كبير غدًا 🌅\n\n"
            "• الاحترام أسلوبنا 🤝\n"
            "• شارك بما يفيد 📌"
        )
        await event.reply(msg)

# =========================
# 5. الردود النصية
# =========================

@client.on(events.NewMessage(pattern=r'^رد\s+\((.*?)\)\s+\((.*)\)'))
async def add_text_reply(event):
    if not await is_admin(event):
        return

    word = clean_text(event.pattern_match.group(1))
    reply = clean_text(event.pattern_match.group(2))

    if not word or not reply:
        return await event.reply("❌ بيانات غير صالحة")

    db["responses"][word] = reply
    save_db()

    m = await event.reply(f"✅ تم إضافة رد ({word})")
    last_actions[m.id] = ("text", word)

# =========================
# 6. ردود الميديا
# =========================

@client.on(events.NewMessage(pattern=r'^(صوره|فيديو)\s+\((.*)\)'))
async def add_media_reply(event):
    if not await is_admin(event):
        return

    word = clean_text(event.pattern_match.group(2))

    if not word:
        return await event.reply("❌ اكتب كلمة صحيحة")

    ask = await event.reply("📩 رد على هذه الرسالة بالميديا")

    def check(m):
        return m.sender_id == event.sender_id and m.is_reply

    try:
        msg = await client.wait_for(events.NewMessage(func=check), timeout=60)

        reply_msg = await msg.get_reply_message()

        if not reply_msg or not reply_msg.media:
            return await msg.reply("❌ لازم ترد بميديا")

        file = await client.download_media(reply_msg.media, file=bytes)

        db["media"][word] = file.hex()
        save_db()

        done = await msg.reply(f"✅ تم حفظ ميديا ({word})")
        last_actions[done.id] = ("media", word)

    except asyncio.TimeoutError:
        await event.reply("⌛ انتهى الوقت")

# =========================
# 7. الحذف
# =========================

@client.on(events.NewMessage(pattern='^حذف$'))
async def delete_reply(event):
    if not await is_admin(event):
        return

    if not event.is_reply:
        return

    reply = await event.get_reply_message()

    if reply.id in last_actions:
        t, key = last_actions[reply.id]

        if t == "text":
            db["responses"].pop(key, None)

        if t == "media":
            db["media"].pop(key, None)

        save_db()

        await event.reply(f"🗑️ تم حذف ({key})")

# =========================
# 8. الملف الشخصي
# =========================

async def send_profile(event):
    uid = str(event.sender_id)
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

# =========================
# 9. الردود العامة
# =========================

async def handle_text_reply(event):
    txt = event.text

    if txt in db["responses"]:
        await event.reply(db["responses"][txt])

async def handle_media_reply(event):
    txt = event.text

    if txt in db["media"]:
        try:
            file = bytes.fromhex(db["media"][txt])
            await client.send_file(event.chat_id, file, reply_to=event.id)
        except:
            pass

# =========================
# 10. النظام الرئيسي
# =========================

@client.on(events.NewMessage)
async def main_handler(event):
    if not event.text:
        return

    text = clean_text(event.text)

    increase_user_stats(event.sender_id)

    if text == "ا":
        await send_profile(event)

    await handle_text_reply(event)
    await handle_media_reply(event)

    save_db()

# =========================
# 11. المنشن الجماعي (لم يتم التعديل)
# =========================

@client.on(events.NewMessage(pattern=r'(?i)^all(?:\s+(.*))?'))
async def mention_all(event):
    if not await is_admin(event): return
    extra = event.pattern_match.group(1) or ""
    mentions = [f"[{u.first_name}](tg://user?id={u.id})" async for u in client.iter_participants(event.chat_id) if not u.bot]
    for i in range(0, len(mentions), 5):
        await client.send_message(event.chat_id, f"{extra}\n" + " ".join(mentions[i:i+5]))
        await asyncio.sleep(0.5)

# =========================
# 12. تشغيل البوت
# =========================

print("🚀 البوت شغال بثبات كامل")
client.run_until_disconnected()
