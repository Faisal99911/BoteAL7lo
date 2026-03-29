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
        "media": {}, # {word: file_id}
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

last_actions = {} # {bot_msg_id: (type, key, user_msg_id)}

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
# 4. الترحيب المطور (منشن + صورة المجموعة)
# =========================

@client.on(events.ChatAction)
async def welcome(event):
    if event.user_joined:
        user = await event.get_user()
        # رسالة الترحيب مع المنشن المخفي
        welcome_text = (
            f"اهلاً بك في فجـر جـديد [\u200b](tg://user?id={user.id}) 🙋🏻‍♂️\n\n"
            "خطوة صغيرة اليوم… تصنع فرق كبير غدًا 🌅\n\n"
            "• ممنوع السلبية أو إحباط الآخرين ❌\n"
            "• لا يُسمح بأي محتوى غير لائق 🚫\n"
            "• الاحترام أسلوبنا الدائم 🤝\n"
            "• شارك بما يفيد ويحفّز غيرك 📌\n"
            "• التزامك اليوم هو نجاحك غداً 🌇"
        )
        
        try:
            # محاولة الحصول على صورة المجموعة
            chat = await event.get_chat()
            photo = await client.download_profile_photo(chat, file=bytes)
            
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
# 6. إضافة رد ميديا (صورة/فيديو) - إصلاح المشكلة
# =========================

@client.on(events.NewMessage(pattern=r'^(صوره|فيديو)\s+\((.*)\)'))
async def add_media_reply(event):
    if not await is_admin(event): return
    
    media_type = event.pattern_match.group(1)
    word = event.pattern_match.group(2).strip()
    
    # إرسال رسالة الطلب
    ask_msg = await event.reply(f"📩 حسناً، أرسل ال{media_type} الآن (أو قم بعمل ريبلاي عليه) لحفظه للكلمة: ({word})")
    
    # دالة التحقق: يجب أن تكون الرسالة من نفس المستخدم وفي نفس الدردشة
    def check(m):
        return m.sender_id == event.sender_id and m.chat_id == event.chat_id and (m.media or (m.is_reply and m.reply_to_msg_id))

    try:
        # انتظار الرد لمدة دقيقة
        response = await client.wait_for(events.NewMessage(func=check), timeout=60)
        
        target_msg = response
        # إذا قام المستخدم بعمل ريبلاي على ميديا قديمة بدلاً من إرسال واحدة جديدة
        if response.is_reply and not response.media:
            target_msg = await response.get_reply_message()
            
        if target_msg and target_msg.media:
            # حفظ الميديا (نستخدم الـ file_id أو نحفظها كـ bytes في الـ JSON إذا كانت صغيرة، 
            # لكن الأفضل في Telethon هو حفظ الـ media object نفسه أو الـ file_id)
            # للتبسيط وضمان العمل سنستخدم الـ media object مباشرة في الذاكرة ونحدث الـ JSON
            # ملاحظة: في Telethon، الـ media object يمكن حفظه وإعادة إرساله
            
            # سنقوم بتحميل الميديا وحفظها كـ bytes في ملف منفصل أو داخل الـ JSON (كـ hex)
            # لضمان استمرارية العمل بعد إعادة التشغيل:
            file_data = await client.download_media(target_msg.media, file=bytes)
            db["media"][word] = file_data.hex()
            save_db()
            
            done = await response.reply(f"✅ تم حفظ ال{media_type} بنجاح للكلمة: ({word})")
            last_actions[done.id] = ("media", word, event.id)
        else:
            await response.reply("❌ خطأ: الرسالة لا تحتوي على ميديا.")
            
    except asyncio.TimeoutError:
        await event.reply("⌛ انتهى الوقت، يرجى المحاولة مرة أخرى.")
    except Exception as e:
        print(f"Media Add Error: {e}")
        await event.reply(f"❌ حدث خطأ أثناء الحفظ: {e}")

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
        elif action_type == "media":
            db["media"].pop(key, None)
        
        save_db()
        
        # حذف السجل
        del last_actions[reply_msg.id]
        
        # حذف الرسائل (رسالة الحذف، رسالة تأكيد البوت، رسالة المستخدم الأصلية)
        try:
            await client.delete_messages(event.chat_id, [event.id, reply_msg.id, original_user_msg_id])
            # إرسال تأكيد مؤقت ثم حذفه
            confirm = await event.respond(f"🗑️ تم حذف الرد الخاص بـ ({key}) بنجاح.")
            await asyncio.sleep(3)
            await confirm.delete()
        except:
            pass
    else:
        await event.reply("❌ لم يتم العثور على هذه العملية في السجلات الأخيرة أو أنها حذفت بالفعل.")

# =========================
# 8. المنشن الجماعي (all)
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
# 9. معالج الرسائل العام (الردود + الإحصائيات)
# =========================

@client.on(events.NewMessage)
async def global_handler(event):
    if not event.text or event.out: return
    
    user_id = str(event.sender_id)
    text = event.text.strip()
    
    # تحديث الإحصائيات
    db["stats"][user_id] = db["stats"].get(user_id, 0) + 1
    # حفظ دوري (اختياري، هنا نحفظ عند كل رسالة لضمان عدم الضياع)
    # save_db() 
    
    # ميزة الملف الشخصي (ا)
    if text == "ا":
        count = db["stats"].get(user_id, 0)
        caption = f"✨ **ملفك الشخصي** ✨\n\n✉️ عدد رسائلك: `{count}`"
        try:
            photo = await client.download_profile_photo(event.sender_id, file=bytes)
            if photo:
                await client.send_file(event.chat_id, photo, caption=caption)
            else:
                await event.reply(caption)
        except:
            await event.reply(caption)
        return

    # الردود النصية
    if text in db["responses"]:
        await event.reply(db["responses"][text])
        return

    # ردود الميديا
    if text in db["media"]:
        try:
            file_data = bytes.fromhex(db["media"][text])
            await client.send_file(event.chat_id, file_data, reply_to=event.id)
        except Exception as e:
            print(f"Send Media Error: {e}")

# =========================
# 10. تشغيل البوت
# =========================

print("🚀 البوت النهائي يعمل الآن بنجاح وبثبات...")
client.run_until_disconnected()
