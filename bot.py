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
                if "warnings" not in data:
                    data["warnings"] = {}
                if "muted" not in data:
                    data["muted"] = {}
                return data
        except:
            return create_empty_db()
    return create_empty_db()

def create_empty_db():
    return {
        "responses": {},
        "stats": {},
        "media": {},
        "warnings": {},
        "muted": {},
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

async def mute_user(chat_id, user_id, hours=6):
    """كتم مستخدم لمدة محددة بالساعات"""
    until = datetime.datetime.now() + datetime.timedelta(hours=hours)
    try:
        await client(functions.EditBannedRequest(
            chat_id,
            user_id,
            types.ChatBannedRights(
                until_date=until,
                send_messages=True
            )
        ))
        return until
    except Exception as e:
        print(f"Mute Error: {e}")
        return None

async def unmute_user(chat_id, user_id):
    """إلغاء كتم مستخدم"""
    try:
        await client(functions.EditBannedRequest(
            chat_id,
            user_id,
            types.ChatBannedRights(
                until_date=None,
                send_messages=False
            )
        ))
        return True
    except Exception as e:
        print(f"Unmute Error: {e}")
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
    last_actions[(event.chat_id, m.id)] = ("text", word, event.id)

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
    
    if not (event.photo or event.video):
        return

    word, media_type, original_cmd_id = waiting_for_media[event.sender_id]
    
    is_photo = event.photo and media_type == "صورة"
    is_video = event.video and media_type == "فيديو"
    
    if is_photo or is_video:
        db["media"][word] = {"type": media_type, "file": event.media}
        save_db()
        
        del waiting_for_media[event.sender_id]
        
        m = await event.reply(f"تمت اضافة الـ {media_type} بنجاح ✅")
        last_actions[(event.chat_id, m.id)] = ("media", word, original_cmd_id, event.id)

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
# 8. الحذف الذكي (نصوص ووسائط)
# =========================

@client.on(events.NewMessage(pattern='^حذف$'))
async def delete_action(event):
    if not await is_admin(event): return
    if not event.is_reply:
        return await event.reply("⚠️ يرجى عمل ريبلاي على رسالة تأكيد البوت لحذف العملية.")
    
    reply_msg = await event.get_reply_message()
    
    key_id = (event.chat_id, reply_msg.id)

    if key_id in last_actions:
        data = last_actions[key_id]
        
        action_type = data[0]
        key = data[1]
        original_user_msg_id = data[2]
        media_msg_id = data[3] if len(data) > 3 else None
        
        if action_type == "text":
            db["responses"].pop(key, None)
        elif action_type == "media":
            db["media"].pop(key, None)
            
        save_db()
        del last_actions[key_id]
        
        try:
            to_delete = [event.id, reply_msg.id, original_user_msg_id]
            
            if media_msg_id:
                to_delete.append(media_msg_id)
                
            await client.delete_messages(event.chat_id, to_delete)
            
            confirm = await event.respond(f"🗑️ تم حذف الرد الخاص بـ ({key}) بنجاح.")
            await asyncio.sleep(3)
            await confirm.delete()
        except Exception as e:
            print(f"Delete Error: {e}")
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
# 10. الكتم والإنذار
# =========================

@client.on(events.NewMessage(pattern=r'^كتم$'))
async def mute_command(event):
    if not await is_admin(event): return
    if not event.is_reply:
        return await event.reply("⚠️ يرجى الرد على رسالة المستخدم المراد كتمه.")

    from telethon.tl import functions
    reply_msg = await event.get_reply_message()
    user = await reply_msg.get_sender()
    user_id = str(user.id)
    chat_id = event.chat_id

    until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=6)

    try:
        await client(functions.channels.EditBannedRequest(
            chat_id,
            user.id,
            types.ChatBannedRights(
                until_date=until,
                send_messages=True
            )
        ))

        db["muted"][user_id] = str(until)
        save_db()

        await event.reply(
            f"🔇 تم كتم [{user.first_name}](tg://user?id={user.id}) لمدة 6 ساعات.",
            parse_mode='md'
        )

        await asyncio.sleep(6 * 3600)

        # رفع الكتم تلقائياً بعد 6 ساعات إذا لم يُرفع يدوياً
        if user_id in db["muted"]:
            await client(functions.channels.EditBannedRequest(
                chat_id,
                user.id,
                types.ChatBannedRights(until_date=None, send_messages=False)
            ))
            db["muted"].pop(user_id, None)
            save_db()

    except Exception as e:
        await event.reply(f"❌ فشل الكتم: {e}")


@client.on(events.NewMessage(pattern=r'^انذار$'))
async def warn_command(event):
    if not await is_admin(event): return
    if not event.is_reply:
        return await event.reply("⚠️ يرجى الرد على رسالة المستخدم المراد إنذاره.")

    from telethon.tl import functions
    reply_msg = await event.get_reply_message()
    user = await reply_msg.get_sender()
    user_id = str(user.id)
    chat_id = event.chat_id

    current_warnings = db["warnings"].get(user_id, 0) + 1
    db["warnings"][user_id] = current_warnings
    save_db()

    if current_warnings == 1:
        await event.reply(
            f"⚠️ إنذار 1/2 لـ [{user.first_name}](tg://user?id={user.id})\n"
            f"تحذير: إنذار آخر سيؤدي إلى كتمك 6 ساعات!",
            parse_mode='md'
        )

    elif current_warnings >= 2:
        # كتم المستخدم
        until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=6)
        try:
            await client(functions.channels.EditBannedRequest(
                chat_id,
                user.id,
                types.ChatBannedRights(
                    until_date=until,
                    send_messages=True
                )
            ))

            db["muted"][user_id] = str(until)
            db["warnings"][user_id] = 0  # إعادة تصفير الإنذارات بعد الكتم
            save_db()

            await event.reply(
                f"🔇 [{user.first_name}](tg://user?id={user.id}) وصل إلى إنذار 2/2\n"
                f"تم كتمه تلقائياً لمدة 6 ساعات! 🚫",
                parse_mode='md'
            )

            await asyncio.sleep(6 * 3600)

            if user_id in db["muted"]:
                await client(functions.channels.EditBannedRequest(
                    chat_id,
                    user.id,
                    types.ChatBannedRights(until_date=None, send_messages=False)
                ))
                db["muted"].pop(user_id, None)
                save_db()

        except Exception as e:
            await event.reply(f"❌ فشل الكتم: {e}")


@client.on(events.NewMessage(pattern=r'^الغاء كتم$'))
async def unmute_by_reply(event):
    """إلغاء الكتم بالرد على رسالة الشخص المكتوم"""
    if not await is_admin(event): return
    if not event.is_reply:
        return await event.reply("⚠️ يرجى الرد على رسالة المستخدم المراد إلغاء كتمه.")

    from telethon.tl import functions
    reply_msg = await event.get_reply_message()
    user = await reply_msg.get_sender()
    user_id = str(user.id)
    chat_id = event.chat_id

    try:
        await client(functions.channels.EditBannedRequest(
            chat_id,
            user.id,
            types.ChatBannedRights(until_date=None, send_messages=False)
        ))

        db["muted"].pop(user_id, None)
        save_db()

        await event.reply(
            f"✅ تم إلغاء كتم [{user.first_name}](tg://user?id={user.id}) بنجاح.",
            parse_mode='md'
        )
    except Exception as e:
        await event.reply(f"❌ فشل إلغاء الكتم: {e}")


@client.on(events.NewMessage(pattern=r'^الغاء كتم @(\w+)$'))
async def unmute_by_username(event):
    """إلغاء الكتم عبر اليوزر مباشرة"""
    if not await is_admin(event): return

    from telethon.tl import functions
    username = event.pattern_match.group(1)
    chat_id = event.chat_id

    try:
        user = await client.get_entity(username)
        user_id = str(user.id)

        await client(functions.channels.EditBannedRequest(
            chat_id,
            user.id,
            types.ChatBannedRights(until_date=None, send_messages=False)
        ))

        db["muted"].pop(user_id, None)
        save_db()

        await event.reply(
            f"✅ تم إلغاء كتم [{user.first_name}](tg://user?id={user.id}) بنجاح.",
            parse_mode='md'
        )
    except Exception as e:
        await event.reply(f"❌ فشل إلغاء الكتم: {e}")

# =========================
# 11. معالج الرسائل
# =========================

@client.on(events.NewMessage)
async def global_handler(event):
    if not event.text or event.out:
        return
    
    user_id = str(event.sender_id)
    text = event.text.strip()
    
    if not text.startswith(('رد ', 'حذف', 'تعديل رسائل', 'all', 'صورة ', 'فيديو ', 'كتم', 'انذار', 'الغاء كتم')):
        db["stats"][user_id] = db["stats"].get(user_id, 0) + 1
    
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

    if text in db["responses"]:
        await event.reply(db["responses"][text])
        return

    if text in db["media"]:
        media_data = db["media"][text]
        await event.reply(file=media_data["file"])
        return

# =========================
# 12. تشغيل البوت
# =========================

print("🚀 البوت يعمل الآن...")
client.run_until_disconnected()
