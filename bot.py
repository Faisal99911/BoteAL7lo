# -*- coding: utf-8 -*-
from telethon import TelegramClient, events, types
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
# 2. قاعدة البيانات (JSON)
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
        "stats": {},
        "meta": {"created": str(datetime.datetime.now())}
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

if "media" in db:
    del db["media"]

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
# 4. الترحيب (صورة العضو + منشن)
# =========================

@client.on(events.ChatAction)
async def welcome(event):
    if event.user_joined:
        user = await event.get_user()

        welcome_text = (
            f"اهلاً بك [{user.first_name}](tg://user?id={user.id}) 🙋🏻‍♂️\n\n"
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
        except Exception as e:
            print(f"Welcome Error: {e}")
            await event.reply(welcome_text)

# =========================
# 5. إضافة رد نصي
# =========================

@client.on(events.NewMessage(pattern=r'^رد\s+\((.*?)\)\s+\((.*)\)'))
async def add_text_reply(event):
    if not await is_admin(event): return
    
    word = event.pattern_match.group(1).strip()
    reply = event.pattern_match.group(2).strip()
    
    db["responses"][word] = reply
    save_db()
    
    m = await event.reply(f"✅ تمت إضافة الرد بنجاح\nالكلمة: ({word})\nالرد: ({reply})")
    last_actions[m.id] = ("text", word, event.id)

# =========================
# 7. الحذف الذكي
# =========================

@client.on(events.NewMessage(pattern='^حذف$'))
async def delete_action(event):
    if not await is_admin(event): return
    if not event.is_reply:
        return await event.reply("⚠️ يرجى عمل ريبلاي على رسالة تأكيد البوت لحذف العملية.")
    
    reply_msg = await event.get_reply_message()
    
    if reply_msg.id in last_actions:
        action_type, key, original_user_msg_id = last_actions[reply_msg.id]
        
        if action_type == "text":
            db["responses"].pop(key, None)
        save_db()
        
        del last_actions[reply_msg.id]
        
        try:
            await client.delete_messages(event.chat_id, [event.id, reply_msg.id, original_user_msg_id])
            confirm = await event.respond(f"🗑️ تم حذف الرد الخاص بـ ({key}) بنجاح.")
            await asyncio.sleep(3)
            await confirm.delete()
        except:
            pass
    else:
        await event.reply("❌ لم يتم العثور على هذه العملية.")

# =========================
# 8. المنشن الجماعي
# =========================

@client.on(events.NewMessage(pattern=r'(?i)^all(?:\s+(.*))?'))
async def mention_all(event):
    if not await is_admin(event): return
    
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

# =========================
# 9. معالج الرسائل
# =========================

@client.on(events.NewMessage)
async def global_handler(event):
    if not event.text or event.out:
        return
    
    user_id = str(event.sender_id)
    text = event.text.strip()
    
    # تحديث الإحصائيات
    db["stats"][user_id] = db["stats"].get(user_id, 0) + 1
    
    # =========================
    # أمر (ا) - الملف الشخصي
    # =========================
    
    if text == "ا":
        user = await event.get_sender()
        count = db["stats"].get(user_id, 0)

        # الترتيب
        sorted_users = sorted(db["stats"].items(), key=lambda x: x[1], reverse=True)
        rank = next((i+1 for i, u in enumerate(sorted_users) if u[0] == user_id), "غير معروف")

        # تاريخ الانضمام
        try:
            full = await client.get_participant(event.chat_id, event.sender_id)
            join_date = full.date.strftime("%Y-%m-%d")
        except:
            join_date = "غير معروف"

        caption = (
            f"✨ ملفك الشخصي ✨\n\n"
            f"👤 الاسم: {user.first_name}\n"
            f"✉️ عدد رسائلك: {count}\n"
            f"🏆 ترتيبك في المتفاعلين: {rank}\n"
            f"📅 تاريخ انضمامك: {join_date}\n\n"
            f"استمر في التفاعل لرفع ترتيبك! ✨"
        )

        try:
            photo = await client.download_profile_photo(user.id)
            if photo:
                await client.send_file(event.chat_id, photo, caption=caption)
            else:
                await event.reply(caption)
        except:
            await event.reply(caption)

        return

    # الردود التلقائية
    if text in db["responses"]:
        await event.reply(db["responses"][text])
        return

# =========================
# 10. تشغيل البوت
# =========================

print("🚀 البوت يعمل الآن...")
client.run_until_disconnected()
