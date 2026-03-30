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
            json.dump(db, f, ensure_ascii=False, indent=4)
    except:
        pass

# =========================
# 3. أدوات مساعدة
# =========================

last_actions = {}
waiting_for_media = {} # {user_id: (word, type)}

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
        except Exception as e:
            print(f"Welcome Error: {e}")
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
    last_actions[m.id] = ("text", word, event.id)

# =========================
# 6. إضافة رد وسائط (صور/فيديو)
# =========================

@client.on(events.NewMessage(pattern=r'^(صورة|فيديو)\s+\((.*?)\)'))
async def add_media_request(event):
    if not await is_admin(event): return
    
    media_type = event.pattern_match.group(1)
    word = event.pattern_match.group(2).strip()
    
    waiting_for_media[event.sender_id] = (word, media_type, event.id)
    
    icon = "🎑" if media_type == "صورة" else "🎬"
    await event.reply(f"حسناً أرسل الـ {media_type} {icon}")

@client.on(events.NewMessage)
async def media_receiver(event):
    if event.sender_id not in waiting_for_media:
        return
    
    word, media_type, original_cmd_id = waiting_for_media[event.sender_id]
    
    is_photo = event.photo and media_type == "صورة"
    is_video = event.video and media_type == "فيديو"
    
    if is_photo or is_video:
        # حفظ الـ file_id أو الـ media object
        # في Telethon يفضل حفظ الـ media object نفسه أو تحويله لـ string إذا لزم الأمر
        # هنا سنقوم بحفظ الـ media للرد به لاحقاً
        db["media"][word] = {"type": media_type, "file": event.media}
        save_db()
        
        del waiting_for_media[event.sender_id]
        m = await event.reply(f"تمت اضافة الـ {media_type} بنجاح ✅")
        last_actions[m.id] = ("media", word, original_cmd_id)

# =========================
# 7. تعديل رسائل
# =========================

@client.on(events.NewMessage(pattern=r'^تعديل رسائل$'))
async def edit_messages_prompt(event):
    if not await is_admin(event): return
    await event.reply("يرجى إرسال المنشن (أو المعرف) متبوعاً بالعدد الجديد.\nمثال: `@username 286` أو قم بالرد على رسالة الشخص واكتب العدد.")

@client.on(events.NewMessage)
async def edit_messages_handler(event):
    if not await is_admin(event): return
    text = event.text.strip() if event.text else ""
    
    match = re.match(r'^(?:@(\w+)|\[.*?\]\(tg://user\?id=(\d+)\))\s+(\d+)$', text)
    
    target_id = None
    new_count = None

    if match:
        username = match.group(1)
        user_id_from_mention = match.group(2)
        new_count = int(match.group(3))
        
        try:
            if username:
                user = await client.get_entity(username)
                target_id = str(user.id)
            else:
                target_id = str(user_id_from_mention)
        except:
            return 

    elif event.is_reply and text.isdigit():
        reply_msg = await event.get_reply_message()
        target_id = str(reply_msg.sender_id)
        new_count = int(text)

    if target_id and new_count is not None:
        db["stats"][target_id] = new_count
        save_db()
        await event.reply(f"✅ تم تحديث عدد رسائل المستخدم إلى: {new_count}")

# =========================
# 8. الحذف الذكي
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
        elif action_type == "media":
            db["media"].pop(key, None)
            
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
        await event.reply("❌ لم يتم العثور على هذه العملية أو انتهت صلاحية الحذف.")

# =========================
# 9. المنشن الجماعي
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
# 10. معالج الرسائل
# =========================

@client.on(events.NewMessage)
async def global_handler(event):
    if not event.text or event.out:
        return
    
    user_id = str(event.sender_id)
    text = event.text.strip()
    
    # تحديث الإحصائيات
    if not text.startswith(('رد ', 'حذف', 'تعديل رسائل', 'all', 'صورة ', 'فيديو ')):
        db["stats"][user_id] = db["stats"].get(user_id, 0) + 1
    
    # أمر (ا) - الملف الشخصي
    if text == "ا":
        count = db["stats"].get(user_id, 0)
        sorted_users = sorted(db["stats"].items(), key=lambda x: x[1], reverse=True)
        rank = next((i+1 for i, u in enumerate(sorted_users) if u[0] == user_id), "غير معروف")

        caption = (
            f"✨ملفك الشخصي✨\n\n"
            f"✉️ عدد رسائلك: {count}\n"
            f"🏆 ترتيبك في المتفاعلين: {rank}\n"
            f"📅 تاريخ انضمامك: قريباً\n\n"
            f"استمر في التفاعل لرفع ترتيبك! ✨"
        )
        await event.reply(caption)
        return

    # الردود التلقائية (نصية)
    if text in db["responses"]:
        await event.reply(db["responses"][text])
        return

    # الردود التلقائية (وسائط)
    if text in db["media"]:
        media_data = db["media"][text]
        # في Telethon، يمكننا إرسال الـ media object مباشرة
        await event.reply(file=media_data["file"])
        return

# =========================
# 11. تشغيل البوت
# =========================

print("🚀 البوت يعمل الآن...")
client.run_until_disconnected()
