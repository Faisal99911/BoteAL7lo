# -*- coding: utf-8 -*-
from telethon import TelegramClient, events, types, Button
from telethon.tl import functions
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
                if "schedules" not in data:
                    data["schedules"] = {}
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
        "schedules": {},
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
bot_id = None

# حالة محادثة جدولة الرسائل: sender_id -> dict بمراحل الإنشاء
scheduling_state = {}
# مهام الجدولة الجارية (asyncio tasks) عشان نقدر نلغيها عند الحذف/التعديل
schedule_tasks = {}

async def get_bot_id():
    global bot_id
    if bot_id is None:
        me = await client.get_me()
        bot_id = me.id
    return bot_id

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
# 8.ب حذف آخر X رسالة بالقروب
# =========================

@client.on(events.NewMessage(pattern=r'^حذف اخر\s+(\d+)\s+رساله$|^حذف اخر\s+(\d+)\s+رسالة$'))
async def delete_last_n_messages(event):
    if not await is_admin(event): return
    if event.is_private:
        return

    count_str = event.pattern_match.group(1) or event.pattern_match.group(2)
    count = int(count_str)

    if count <= 0:
        return await event.reply("⚠️ العدد يجب أن يكون أكبر من صفر.")

    # حد أقصى احترازي عشان ما نضغط على حدود تيليجرام
    count = min(count, 5000)

    chat_id = event.chat_id

    status_msg = await event.reply(f"🗑️ جاري حذف آخر {count} رسالة...")

    # نجمع المعرفات: من رسالة الأمر نفسها للخلف
    ids_to_delete = []
    # نضيف رسالة الأمر نفسها ضمن الحذف
    ids_to_delete.append(event.id)

    async for msg in client.iter_messages(chat_id, offset_id=event.id, limit=count):
        ids_to_delete.append(msg.id)

    deleted_total = 0
    try:
        # الحذف على دفعات (تيليجرام يسمح بحذف عدة رسائل بنفس الاستدعاء، لكن نقسمها احترازاً)
        chunk_size = 100
        for i in range(0, len(ids_to_delete), chunk_size):
            chunk = ids_to_delete[i:i + chunk_size]
            await client.delete_messages(chat_id, chunk)
            deleted_total += len(chunk)
            await asyncio.sleep(0.3)

        await status_msg.delete()
        confirm = await client.send_message(chat_id, f"✅ تم حذف {deleted_total} رسالة بنجاح.")
        await asyncio.sleep(3)
        await confirm.delete()
    except Exception as e:
        try:
            await status_msg.edit(f"❌ حدث خطأ أثناء الحذف: {e}")
        except:
            print(f"Bulk Delete Error: {e}")

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

    reply_msg = await event.get_reply_message()
    user = await reply_msg.get_sender()
    user_id = str(user.id)
    chat_id = event.chat_id
    until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=6)

    try:
        await client(functions.channels.EditBannedRequest(
            chat_id,
            user.id,
            types.ChatBannedRights(until_date=until, send_messages=True)
        ))
        db["muted"][user_id] = str(until)
        save_db()

        await event.reply(
            f"🔇 تم كتم [{user.first_name}](tg://user?id={user.id}) لمدة 6 ساعات.",
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


@client.on(events.NewMessage(pattern=r'^انذار$'))
async def warn_command(event):
    if not await is_admin(event): return
    if not event.is_reply:
        return await event.reply("⚠️ يرجى الرد على رسالة المستخدم المراد إنذاره.")

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
        until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=6)
        try:
            await client(functions.channels.EditBannedRequest(
                chat_id,
                user.id,
                types.ChatBannedRights(until_date=until, send_messages=True)
            ))
            db["muted"][user_id] = str(until)
            db["warnings"][user_id] = 0
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
    if not await is_admin(event): return
    if not event.is_reply:
        return await event.reply("⚠️ يرجى الرد على رسالة المستخدم المراد إلغاء كتمه.")

    reply_msg = await event.get_reply_message()
    chat_id = event.chat_id
    my_bot_id = await get_bot_id()

    target_user_id = None
    target_name = None

    # إذا كانت الرسالة من البوت نستخرج ID من النص
    if reply_msg.sender_id == my_bot_id:
        match = re.search(r'tg://user\?id=(\d+)', reply_msg.text or "")
        if match:
            target_user_id = int(match.group(1))
            target_name = "المستخدم"
        else:
            return await event.reply("❌ لم أتمكن من تحديد المستخدم من رسالة البوت.")
    else:
        sender = await reply_msg.get_sender()
        target_user_id = sender.id
        target_name = sender.first_name

    try:
        await client(functions.channels.EditBannedRequest(
            chat_id,
            target_user_id,
            types.ChatBannedRights(until_date=None, send_messages=False)
        ))
        db["muted"].pop(str(target_user_id), None)
        save_db()

        await event.reply(
            f"✅ تم إلغاء كتم [{target_name}](tg://user?id={target_user_id}) بنجاح.",
            parse_mode='md'
        )
    except Exception as e:
        await event.reply(f"❌ فشل إلغاء الكتم: {e}")


@client.on(events.NewMessage(pattern=r'^الغاء كتم @(\w+)$'))
async def unmute_by_username(event):
    if not await is_admin(event): return

    username = event.pattern_match.group(1)
    chat_id = event.chat_id

    try:
        user = None
        async for participant in client.iter_participants(chat_id):
            if participant.username and participant.username.lower() == username.lower():
                user = participant
                break

        if not user:
            return await event.reply(f"❌ لم يتم العثور على @{username} في المجموعة.")

        await client(functions.channels.EditBannedRequest(
            chat_id,
            user.id,
            types.ChatBannedRights(until_date=None, send_messages=False)
        ))
        db["muted"].pop(str(user.id), None)
        save_db()

        await event.reply(
            f"✅ تم إلغاء كتم [{user.first_name}](tg://user?id={user.id}) بنجاح.",
            parse_mode='md'
        )
    except Exception as e:
        await event.reply(f"❌ فشل إلغاء الكتم: {e}")

# =========================
# 11. جدولة الرسائل (تلقائي يومي)
# =========================
# الفكرة:
#  - أمر "جدولة" يفتح قائمة أزرار: [➕ جدولة جديدة] [📋 عرض الجدولات] [❌ إلغاء جدولة]
#  - عند "جدولة جديدة": يطلب من المشرف يرسل وقت الإرسال اليومي (مثال: 07:00) ثم نص الرسالة.
#  - يتم حفظها بقاعدة البيانات ويشتغل لها مؤقّت (loop) يرسل الرسالة كل يوم بنفس الوقت.
#  - عرض الجدولات يطلع قائمة بأزرار لكل جدولة (تعديل الوقت / حذف).

def schedule_keyboard():
    return [
        [Button.inline("➕ جدولة جديدة", b"sched_new")],
        [Button.inline("📋 عرض الجدولات", b"sched_list")],
    ]

def schedule_item_keyboard(sched_id):
    return [
        [
            Button.inline("✏️ تعديل الوقت", f"sched_edit_{sched_id}".encode()),
            Button.inline("🗑️ حذف", f"sched_del_{sched_id}".encode()),
        ]
    ]

async def schedule_loop(sched_id):
    """يرسل الرسالة المجدولة يومياً بنفس الوقت المحدد."""
    while True:
        sched = db["schedules"].get(sched_id)
        if not sched:
            return  # تم حذفها

        now = datetime.datetime.now()
        hour, minute = sched["hour"], sched["minute"]
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)

        wait_seconds = (target - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        # إعادة التأكد إنها ما انحذفت أثناء الانتظار
        sched = db["schedules"].get(sched_id)
        if not sched:
            return

        try:
            await client.send_message(int(sched["chat_id"]), sched["text"])
        except Exception as e:
            print(f"Schedule Send Error ({sched_id}): {e}")

        # نكمل اللوب لليوم التالي

def start_schedule_task(sched_id):
    if sched_id in schedule_tasks:
        schedule_tasks[sched_id].cancel()
    task = asyncio.create_task(schedule_loop(sched_id))
    schedule_tasks[sched_id] = task

def stop_schedule_task(sched_id):
    task = schedule_tasks.pop(sched_id, None)
    if task:
        task.cancel()

def restart_all_schedules():
    for sched_id in list(db["schedules"].keys()):
        start_schedule_task(sched_id)


@client.on(events.NewMessage(pattern=r'^جدولة$'))
async def schedule_menu(event):
    if not await is_admin(event): return
    await event.reply("⏰ قائمة جدولة الرسائل التلقائية:", buttons=schedule_keyboard())


@client.on(events.CallbackQuery(data=b"sched_new"))
async def schedule_new(event):
    if not await is_admin(event):
        return await event.answer("ليس لديك صلاحية.", alert=True)

    scheduling_state[event.sender_id] = {
        "step": "time",
        "chat_id": event.chat_id,
    }
    await event.edit("🕖 أرسل الوقت اليومي للإرسال بصيغة HH:MM (مثال: 07:00)")


@client.on(events.CallbackQuery(data=b"sched_list"))
async def schedule_list(event):
    if not await is_admin(event):
        return await event.answer("ليس لديك صلاحية.", alert=True)

    chat_schedules = {
        sid: s for sid, s in db["schedules"].items()
        if str(s["chat_id"]) == str(event.chat_id)
    }

    if not chat_schedules:
        return await event.edit("لا توجد جدولات حالياً في هذه المجموعة.", buttons=schedule_keyboard())

    await event.edit("📋 الجدولات الحالية:", buttons=schedule_keyboard())
    for sid, s in chat_schedules.items():
        preview = s["text"] if len(s["text"]) <= 80 else s["text"][:77] + "..."
        msg = f"⏰ الوقت: {s['hour']:02d}:{s['minute']:02d}\n📝 الرسالة: {preview}"
        await client.send_message(
            event.chat_id, msg, buttons=schedule_item_keyboard(sid)
        )


@client.on(events.CallbackQuery(pattern=rb"^sched_del_(.+)$"))
async def schedule_delete(event):
    if not await is_admin(event):
        return await event.answer("ليس لديك صلاحية.", alert=True)

    sched_id = event.pattern_match.group(1).decode()
    if sched_id in db["schedules"]:
        db["schedules"].pop(sched_id, None)
        save_db()
        stop_schedule_task(sched_id)
        await event.edit("🗑️ تم حذف الجدولة بنجاح.")
    else:
        await event.edit("❌ لم يتم العثور على هذه الجدولة (ربما حُذفت مسبقاً).")


@client.on(events.CallbackQuery(pattern=rb"^sched_edit_(.+)$"))
async def schedule_edit(event):
    if not await is_admin(event):
        return await event.answer("ليس لديك صلاحية.", alert=True)

    sched_id = event.pattern_match.group(1).decode()
    if sched_id not in db["schedules"]:
        return await event.edit("❌ لم يتم العثور على هذه الجدولة.")

    scheduling_state[event.sender_id] = {
        "step": "edit_time",
        "chat_id": event.chat_id,
        "sched_id": sched_id,
    }
    await event.edit("🕖 أرسل الوقت الجديد بصيغة HH:MM (مثال: 19:30)")


@client.on(events.NewMessage)
async def schedule_conversation_handler(event):
    """يلتقط الرسائل أثناء عملية إنشاء/تعديل الجدولة (وقت ثم نص)."""
    if event.sender_id not in scheduling_state:
        return
    if not await is_admin(event):
        return

    state = scheduling_state[event.sender_id]
    text = event.text.strip() if event.text else ""

    time_match = re.match(r'^([0-2]?\d):([0-5]\d)$', text)

    if state["step"] == "time":
        if not time_match:
            return await event.reply("⚠️ صيغة الوقت غير صحيحة. أرسل بصيغة HH:MM مثل 07:00")
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        if hour > 23:
            return await event.reply("⚠️ الساعة يجب أن تكون بين 00 و 23.")
        state["hour"] = hour
        state["minute"] = minute
        state["step"] = "text"
        return await event.reply("📝 الآن أرسل نص الرسالة التي تريد جدولتها.")

    elif state["step"] == "text":
        sched_id = f"s{len(db['schedules']) + 1}_{int(datetime.datetime.now().timestamp())}"
        db["schedules"][sched_id] = {
            "chat_id": state["chat_id"],
            "hour": state["hour"],
            "minute": state["minute"],
            "text": text,
        }
        save_db()
        start_schedule_task(sched_id)
        del scheduling_state[event.sender_id]
        return await event.reply(
            f"✅ تم جدولة الرسالة بنجاح، ستُرسل يومياً الساعة {state['hour']:02d}:{state['minute']:02d}."
        )

    elif state["step"] == "edit_time":
        if not time_match:
            return await event.reply("⚠️ صيغة الوقت غير صحيحة. أرسل بصيغة HH:MM مثل 19:30")
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        if hour > 23:
            return await event.reply("⚠️ الساعة يجب أن تكون بين 00 و 23.")

        sched_id = state["sched_id"]
        if sched_id in db["schedules"]:
            db["schedules"][sched_id]["hour"] = hour
            db["schedules"][sched_id]["minute"] = minute
            save_db()
            start_schedule_task(sched_id)  # إعادة تشغيل المؤقت بالوقت الجديد
            await event.reply(f"✅ تم تحديث وقت الجدولة إلى {hour:02d}:{minute:02d}.")
        else:
            await event.reply("❌ لم يتم العثور على هذه الجدولة (ربما حُذفت).")

        del scheduling_state[event.sender_id]
        return

# =========================
# 12. معالج الرسائل
# =========================

@client.on(events.NewMessage)
async def global_handler(event):
    if not event.text or event.out:
        return
    
    user_id = str(event.sender_id)
    text = event.text.strip()

    ignored_prefixes = (
        'رد ', 'حذف', 'تعديل رسائل', 'all', 'صورة ', 'فيديو ',
        'كتم', 'انذار', 'الغاء كتم', 'جدولة'
    )
    if not text.startswith(ignored_prefixes):
        db["stats"][user_id] = db["stats"].get(user_id, 0) + 1
    
    if text == "ا":
        count = db["stats"].get(user_id, 0)
        sorted_users = sorted(db["stats"].items(), key=lambda x: x[1], reverse=True)
        rank = next((i+1 for i, u in enumerate(sorted_users) if u[0] == user_id), "غير معروف")

        sender = await event.get_sender()
        first_name = sender.first_name if sender and sender.first_name else "بدون اسم"

        caption = (
            "┏━━━━━━━━━━━━━━━┓\n"
            "      ✨ الملف الشخصي ✨\n"
            "┗━━━━━━━━━━━━━━━┛\n\n"
            f"👤 الاسم: {first_name}\n"
            f"✉️ عدد الرسائل: {count}\n"
            f"🏆 الترتيب بالمتفاعلين: {rank}\n"
            f"📅 تاريخ الانضمام: قريباً\n\n"
            "🌟 استمر في التفاعل لرفع ترتيبك!"
        )

        try:
            photo = await client.download_profile_photo(event.sender_id)
            if photo:
                await client.send_file(event.chat_id, photo, caption=caption, reply_to=event.id)
            else:
                await event.reply(caption)
        except Exception as e:
            print(f"Profile Photo Error: {e}")
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
# 13. تشغيل البوت
# =========================

print("🚀 البوت يعمل الآن...")
restart_all_schedules()
client.run_until_disconnected()
