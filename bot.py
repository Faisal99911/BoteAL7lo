# -*- coding: utf-8 -*-
from telethon import TelegramClient, events, types
import asyncio
import json
import os
import datetime
import re

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
# 2. قاعدة البيانات (JSON)
# =========================

def load_db():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "media" not in data:
                    data["media"] = {}
                return data
        except:
            return create_empty_db()
    return create_empty_db()

def create_empty_db():
    return {
        "responses": {},
        "stats": {},
        "media": {},
        "meta": {"created": str(datetime.datetime.now())}
    }

db = load_db()

def save_db():
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(db, f, ensure_ascii=False, indent=4, default=lambda x: str(x))
    except:
        pass

# =========================
# 3. أدوات مساعدة
# =========================

# 🔥 التعديل هنا (ربط الشات + الرسالة)
last_actions = {}

waiting_for_media = {}

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

        welcome_text = (
            f"اهلاً بك في فجر جديد [{user.first_name}](tg://user?id={user.id}) 🙋🏻‍♂️\n\n"
            "خطوة صغيرة اليوم… تصنع فرق كبير غدًا 🌅\n\n"
            "• ممنوع السلبية أو إحباط الآخرين ❌\n"
            "• لا يُسمح بأي محتوى غير لائق 🚫\n"
            "• الاحترام أسلوبنا الدائم 🤝\n"
            "• شارك بما يفيد ويحفّز غيرك 📌\n"
            "• التزامك اليوم هو نجاحك غداً 🌇"
        )

        try:
            photo = await client.download_profile_photo(user.id)
            if photo:
                await client.send_file(event.chat_id, photo, caption=welcome_text)
            else:
                await event.reply(welcome_text)
        except:
            await event.reply(welcome_text)

# =========================
# 5. إضافة رد نصي
# =========================

@client.on(events.NewMessage(pattern=r'(?s)^رد\s+\((.*?)\)\s+\((.*)\)'))
async def add_text_reply(event):
    if not await is_admin(event): return
    
    word = event.pattern_match.group(1).strip()
    reply = event.pattern_match.group(2).strip()
    
    db["responses"][word] = reply
    save_db()
    
    m = await event.reply(f"✅ تمت إضافة الرد بنجاح\nالكلمة: ({word})\nالرد: ({reply})")
    
    # 🔥 التعديل هنا
    last_actions[(event.chat_id, m.id)] = ("text", word, event.id)

# =========================
# 6. إضافة وسائط
# =========================

@client.on(events.NewMessage(pattern=r'^(صورة|فيديو)\s+\((.*?)\)'))
async def add_media_request(event):
    if not await is_admin(event): return
    
    media_type = event.pattern_match.group(1)
    word = event.pattern_match.group(2).strip()
    
    waiting_for_media[event.sender_id] = (word, media_type, event.id)
    
    await event.reply(f"أرسل الـ {media_type}")

@client.on(events.NewMessage)
async def media_receiver(event):
    if event.sender_id not in waiting_for_media:
        return
    
    if not (event.photo or event.video):
        return

    word, media_type, original_cmd_id = waiting_for_media[event.sender_id]
    
    if (event.photo and media_type == "صورة") or (event.video and media_type == "فيديو"):
        db["media"][word] = {"type": media_type, "file": event.media}
        save_db()
        
        del waiting_for_media[event.sender_id]
        
        m = await event.reply(f"تمت إضافة {media_type} ✅")
        
        # 🔥 التعديل هنا
        last_actions[(event.chat_id, m.id)] = ("media", word, original_cmd_id)

# =========================
# 7. تعديل الرسائل
# =========================

@client.on(events.NewMessage(pattern=r'^تعديل رسائل$'))
async def edit_messages_prompt(event):
    if not await is_admin(event): return
    await event.reply("أرسل المنشن + العدد")

@client.on(events.NewMessage)
async def edit_messages_handler(event):
    if not await is_admin(event): return
    
    text = event.text.strip() if event.text else ""
    match = re.match(r'^(?:@(\w+)|\[.*?\]\(tg://user\?id=(\d+)\))\s+(\d+)$', text)
    
    if match:
        new_count = int(match.group(3))
        db["stats"]["test"] = new_count
        save_db()
        await event.reply("تم التعديل")

# =========================
# 8. الحذف الذكي (🔥 تم إصلاحه)
# =========================

@client.on(events.NewMessage(pattern='^حذف$'))
async def delete_action(event):
    if not await is_admin(event): return
    
    if not event.is_reply:
        return await event.reply("⚠️ سوِّ ريبلاي على رسالة البوت")
    
    reply_msg = await event.get_reply_message()
    
    # 🔥 التعديل هنا
    key_id = (event.chat_id, reply_msg.id)

    if key_id in last_actions:
        action_type, key, original_user_msg_id = last_actions[key_id]
        
        if action_type == "text":
            db["responses"].pop(key, None)
        elif action_type == "media":
            db["media"].pop(key, None)
            
        save_db()
        
        # 🔥 التعديل هنا
        del last_actions[key_id]
        
        try:
            await client.delete_messages(event.chat_id, [event.id, reply_msg.id, original_user_msg_id])
            confirm = await event.respond(f"🗑️ تم حذف ({key})")
            await asyncio.sleep(3)
            await confirm.delete()
        except Exception as e:
            print(e)
    else:
        await event.reply("❌ لم يتم العثور على العملية أو انتهت صلاحيتها")

# =========================
# 9. المنشن الجماعي
# =========================

@client.on(events.NewMessage(pattern=r'(?i)^all(?:\s+(.*))?'))
async def mention_all(event):
    if not await is_admin(event): return
    
    extra = event.pattern_match.group(1) or ""
    users = []
    
    async for u in client.iter_participants(event.chat_id):
        if not u.bot:
            users.append(f"[{u.first_name}](tg://user?id={u.id})")
    
    for i in range(0, len(users), 5):
        await client.send_message(event.chat_id, extra + "\n" + " ".join(users[i:i+5]))
        await asyncio.sleep(0.5)

# =========================
# 10. التشغيل
# =========================

print("🚀 البوت يعمل...")
client.run_until_disconnected()
