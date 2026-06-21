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
# المفتاح: f"{sched_id}_{time_index}"
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
# 11. جدولة الرسائل (محلل وقت + تكرار مرن، نص/صورة/فيديو)
# =========================

ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')

WEEKDAY_NAMES = {
    "السبت": 5, "الأحد": 6, "الاحد": 6, "الإثنين": 0, "الاثنين": 0,
    "الثلاثاء": 1, "الثلاثا": 1, "الأربعاء": 2, "الاربعاء": 2, "الاربعا": 2,
    "الخميس": 3, "الجمعة": 4, "الجمعه": 4,
}
# ملاحظة: Python weekday(): الإثنين=0 ... الأحد=6

def normalize_text(s):
    s = s.translate(ARABIC_DIGITS)
    s = s.replace('ـ', '')
    return s


def parse_times(raw_text):
    """
    يحاول استخراج وقت أو وقتين (صباحاً/مساءً) من نص حر.
    يدعم: '7 صباحا', '٧ صباحا', '7:30', '7:30 مساء', '19:30',
          '7 صباحا و7 مساء', '7 و 19:30', 'الساعة 7 مساء' ... إلخ.
    يرجع list من dict {hour, minute} أو [] إذا فشل.
    """
    text = normalize_text(raw_text).strip()
    text = text.replace("الساعة", "").replace("الساعه", "").replace("ساعة", "").replace("ساعه", "")

    # نقسم على "و" عشان نمسك حالة وقتين بنفس الرسالة (يغطي "7 و7" و"7و 7" و"7و7")
    parts = re.split(r'\s+و(?=\s*\d)|\s*و(?=\d)|\s*&\s*|\s*,\s*', text)

    results = []
    time_pattern = re.compile(
        r'(\d{1,2})(?:[:٫.](\d{2}))?\s*(صباحا|صباحاً|ص\b|am|AM|مساءا|مساءاً|مساء|مساءً|م\b|pm|PM|ظهرا|ظهراً|ظهر|عصرا|عصراً|عصر)?'
    )

    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = time_pattern.search(part)
        if not m:
            continue

        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        period = (m.group(3) or "").strip()

        is_pm = period in ("مساءا", "مساءاً", "مساء", "مساءً", "م", "pm", "PM", "عصرا", "عصراً", "عصر")
        is_am = period in ("صباحا", "صباحاً", "ص", "am", "AM")
        is_noon = period in ("ظهرا", "ظهراً", "ظهر")

        if hour > 23 or minute > 59:
            continue

        if is_noon:
            if hour < 12:
                hour += 12 if hour != 12 else 0
        elif is_pm:
            if hour < 12:
                hour += 12
        elif is_am:
            if hour == 12:
                hour = 0
        else:
            pass

        results.append({"hour": hour, "minute": minute})

    return results


def parse_recurrence(raw_text):
    """
    يحاول استخراج نوع التكرار من نص حر. يرجع dict بالشكل:
      {"type": "daily"}
      {"type": "weekly", "weekday": 4}
      {"type": "interval_days", "days": 2}
      {"type": "monthly", "day": 15}
      {"type": "monthly_count", "times": 2}
    إذا ما لقى شي واضح يرجع {"type": "daily"} كافتراضي.
    """
    text = normalize_text(raw_text).strip()

    m = re.search(r'كل\s*(\d+)\s*(?:يوم|أيام|ايام)', text)
    if m:
        return {"type": "interval_days", "days": int(m.group(1))}
    if "كل يومين" in text or "يوم بعد يوم" in text or "يوم وبعد يوم" in text:
        return {"type": "interval_days", "days": 2}
    if "كل ثلاث ايام" in text or "كل ثلاثة ايام" in text or "كل ثلاثة أيام" in text:
        return {"type": "interval_days", "days": 3}

    for name, wd in WEEKDAY_NAMES.items():
        if name in text:
            return {"type": "weekly", "weekday": wd}
    if "اسبوعي" in text or "أسبوعي" in text or "كل اسبوع" in text or "كل أسبوع" in text or "بالاسبوع مره" in text or "بالاسبوع مرة" in text or "مرة بالاسبوع" in text or "مره بالاسبوع" in text:
        return {"type": "weekly", "weekday": None}  # None = نفس يوم الإنشاء

    m = re.search(r'(\d+)\s*مر(?:ات|ة|ه)?\s*(?:في\s*ال|بال)?شهر', text)
    if m:
        return {"type": "monthly_count", "times": int(m.group(1))}
    if "مرتين بالشهر" in text or "مرتين في الشهر" in text:
        return {"type": "monthly_count", "times": 2}

    m = re.search(r'يوم\s*(\d{1,2})\s*(?:من\s*)?(?:كل\s*)?شهر', text)
    if m:
        day = int(m.group(1))
        if 1 <= day <= 31:
            return {"type": "monthly", "day": day}
    if "شهري" in text or "كل شهر" in text or "بالشهر مره" in text or "بالشهر مرة" in text or "مرة بالشهر" in text or "مره بالشهر" in text:
        return {"type": "monthly", "day": None}  # None = نفس يوم الإنشاء

    if "يوم" in text or "يوميا" in text or "يومياً" in text:
        if "يومين" not in text:
            return {"type": "daily"}

    return {"type": "daily"}


def recurrence_description(rec, created_dt=None):
    t = rec.get("type", "daily")
    if t == "daily":
        return "يومياً"
    if t == "interval_days":
        return f"كل {rec['days']} يوم"
    if t == "weekly":
        wd = rec.get("weekday")
        if wd is None and created_dt:
            wd = created_dt.weekday()
        names = {0: "الإثنين", 1: "الثلاثاء", 2: "الأربعاء", 3: "الخميس", 4: "الجمعة", 5: "السبت", 6: "الأحد"}
        return f"أسبوعياً (كل {names.get(wd, 'نفس اليوم')})"
    if t == "monthly":
        day = rec.get("day")
        if day is None and created_dt:
            day = created_dt.day
        return f"شهرياً (يوم {day})"
    if t == "monthly_count":
        return f"{rec['times']} مرات بالشهر"
    return "يومياً"


def next_run_datetime(hour, minute, rec, now=None, created_dt=None):
    """يحسب موعد التنفيذ القادم بناءً على الوقت والتكرار."""
    now = now or datetime.datetime.now()
    t = rec.get("type", "daily")

    base = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if t == "daily":
        if base <= now:
            base += datetime.timedelta(days=1)
        return base

    if t == "interval_days":
        days = max(1, rec.get("days", 1))
        candidate = base
        if candidate <= now:
            candidate += datetime.timedelta(days=1)
        if created_dt:
            ref = created_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            delta_days = (candidate.date() - ref.date()).days
            remainder = delta_days % days
            if remainder != 0:
                candidate += datetime.timedelta(days=(days - remainder))
        return candidate

    if t == "weekly":
        wd = rec.get("weekday")
        if wd is None and created_dt:
            wd = created_dt.weekday()
        if wd is None:
            wd = now.weekday()
        candidate = base
        days_ahead = (wd - candidate.weekday()) % 7
        candidate += datetime.timedelta(days=days_ahead)
        if candidate <= now:
            candidate += datetime.timedelta(days=7)
        return candidate

    if t == "monthly":
        day = rec.get("day")
        if day is None and created_dt:
            day = created_dt.day
        if day is None:
            day = now.day
        year, month = now.year, now.month
        while True:
            try:
                candidate = datetime.datetime(year, month, day, hour, minute)
            except ValueError:
                month += 1
                if month > 12:
                    month = 1
                    year += 1
                continue
            if candidate > now:
                return candidate
            month += 1
            if month > 12:
                month = 1
                year += 1

    if t == "monthly_count":
        times = max(1, rec.get("times", 1))
        interval_days = max(1, 30 // times)
        candidate = base
        if created_dt:
            ref = created_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            elapsed = (now - ref).days
            cycles = (elapsed // interval_days) + 1
            candidate = ref + datetime.timedelta(days=interval_days * cycles)
        if candidate <= now:
            candidate += datetime.timedelta(days=interval_days)
        return candidate

    if base <= now:
        base += datetime.timedelta(days=1)
    return base


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


async def schedule_loop(sched_id, time_index):
    """يرسل الرسالة/الوسائط المجدولة بشكل متكرر حسب التكرار المحدد."""
    while True:
        sched = db["schedules"].get(sched_id)
        if not sched or time_index >= len(sched.get("times", [])):
            return  # تم حذفها أو حذف هذا الوقت

        t = sched["times"][time_index]
        rec = sched.get("recurrence", {"type": "daily"})
        created_dt = None
        try:
            created_dt = datetime.datetime.fromisoformat(sched["created_at"])
        except Exception:
            pass

        now = datetime.datetime.now()
        target = next_run_datetime(t["hour"], t["minute"], rec, now=now, created_dt=created_dt)

        wait_seconds = (target - now).total_seconds()
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        sched = db["schedules"].get(sched_id)
        if not sched or time_index >= len(sched.get("times", [])):
            return

        try:
            chat_id = int(sched["chat_id"])
            content = sched.get("content", {})
            if content.get("type") == "media":
                await client.send_file(chat_id, content["file"], caption=content.get("caption") or None)
            else:
                await client.send_message(chat_id, content.get("text", ""))
        except Exception as e:
            print(f"Schedule Send Error ({sched_id}#{time_index}): {e}")

        # نعيد الحساب باللوب لمرة التنفيذ القادمة


def start_schedule_task(sched_id):
    sched = db["schedules"].get(sched_id)
    if not sched:
        return
    for idx in range(len(sched.get("times", []))):
        key = f"{sched_id}_{idx}"
        if key in schedule_tasks:
            schedule_tasks[key].cancel()
        schedule_tasks[key] = asyncio.create_task(schedule_loop(sched_id, idx))

def stop_schedule_task(sched_id):
    keys = [k for k in schedule_tasks if k.startswith(f"{sched_id}_")]
    for k in keys:
        schedule_tasks[k].cancel()
        schedule_tasks.pop(k, None)

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

    state = {
        "step": "time",
        "chat_id": event.chat_id,
        "conv_msg_ids": [],
    }
    scheduling_state[event.sender_id] = state

    msg = await event.get_message()
    state["conv_msg_ids"].append(msg.id)  # رسالة القائمة نفسها

    await event.edit(
        "🕖 أرسل وقت/أوقات الإرسال (يقبل صيغ متعددة):\n"
        "مثال: 7 صباحا — ٧:٣٠ — 19:30 — 7 صباحا و7 مساء"
    )


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
        times_str = " / ".join(f"{t['hour']:02d}:{t['minute']:02d}" for t in s.get("times", []))
        content = s.get("content", {})
        if content.get("type") == "media":
            preview = f"[{content.get('media_kind', 'وسائط')}]" + (f" — {content.get('caption','')[:50]}" if content.get('caption') else "")
        else:
            txt = content.get("text", "")
            preview = txt if len(txt) <= 80 else txt[:77] + "..."
        rec_desc = recurrence_description(s.get("recurrence", {"type": "daily"}))
        msg = f"⏰ الأوقات: {times_str}\n🔁 التكرار: {rec_desc}\n📝 المحتوى: {preview}"
        await client.send_message(
            event.chat_id, msg, buttons=schedule_item_keyboard(sid)
        )


@client.on(events.CallbackQuery(pattern=rb"^sched_del_(.+)$"))
async def schedule_delete(event):
    if not await is_admin(event):
        return await event.answer("ليس لديك صلاحية.", alert=True)

    sched_id = event.pattern_match.group(1).decode()
    sched = db["schedules"].get(sched_id)

    if sched:
        # حذف كل رسائل ضبط الجدولة المرتبطة (من لحظة الضغط على "جدولة جديدة" حتى التأكيد)
        setup_ids = sched.get("setup_msg_ids", [])
        chat_id = int(sched["chat_id"])
        db["schedules"].pop(sched_id, None)
        save_db()
        stop_schedule_task(sched_id)

        try:
            if setup_ids:
                await client.delete_messages(chat_id, setup_ids)
        except Exception as e:
            print(f"Setup messages delete error: {e}")

        try:
            await event.delete()  # حذف بطاقة عرض هذه الجدولة نفسها
        except:
            pass

        confirm = await client.send_message(chat_id, "🗑️ تم حذف الجدولة.")
        await asyncio.sleep(3)
        try:
            await confirm.delete()
        except:
            pass
    else:
        try:
            await event.edit("❌ لم يتم العثور على هذه الجدولة (ربما حُذفت مسبقاً).")
        except:
            pass


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
        "conv_msg_ids": [],
    }
    await event.edit(
        "🕖 أرسل الوقت/الأوقات الجديدة (نفس الصيغ المرنة مدعومة):\n"
        "مثال: 7 صباحا — 19:30 — 7 صباحا و7 مساء"
    )


@client.on(events.NewMessage)
async def schedule_conversation_handler(event):
    """يلتقط الرسائل أثناء عملية إنشاء/تعديل الجدولة (وقت → تكرار → محتوى)."""
    if event.sender_id not in scheduling_state:
        return
    if not await is_admin(event):
        return

    state = scheduling_state[event.sender_id]
    text = event.text.strip() if event.text else ""

    # نتتبع رسالة المستخدم بالمحادثة
    state.setdefault("conv_msg_ids", []).append(event.id)

    if state["step"] == "time":
        times = parse_times(text)
        if not times:
            err = await event.reply(
                "⚠️ ما قدرت أفهم الوقت. جرّب مثلاً: 7 صباحا — ٧:٣٠ مساءً — 19:30 — 7 صباحا و7 مساء"
            )
            state["conv_msg_ids"].append(err.id)
            return

        state["times"] = times
        state["step"] = "recurrence"
        ask = await event.reply(
            "🔁 خلال كم تتكرر الرسالة؟ اكتب مثلاً:\n"
            "يومي — كل يومين — كل 3 ايام — اسبوعي — الجمعة — شهري — يوم 15 من كل شهر — مرتين بالشهر\n"
            "أو اكتب (تخطي) لتكون يومية افتراضياً."
        )
        state["conv_msg_ids"].append(ask.id)
        return

    elif state["step"] == "recurrence":
        if text in ("تخطي", "تجاوز", "لا", "-"):
            rec = {"type": "daily"}
        else:
            rec = parse_recurrence(text)
        state["recurrence"] = rec
        state["step"] = "content"
        ask = await event.reply("📝 الآن أرسل نص الرسالة، أو أرسل صورة/فيديو (مع كابشن اختياري) لتُرسل تلقائياً.")
        state["conv_msg_ids"].append(ask.id)
        return

    elif state["step"] == "content":
        if event.photo or event.video:
            media_kind = "صورة" if event.photo else "فيديو"
            content = {
                "type": "media",
                "media_kind": media_kind,
                "file": event.media,
                "caption": text or "",
            }
        elif text:
            content = {"type": "text", "text": text}
        else:
            err = await event.reply("⚠️ أرسل نص الرسالة أو صورة/فيديو.")
            state["conv_msg_ids"].append(err.id)
            return

        sched_id = f"s{len(db['schedules']) + 1}_{int(datetime.datetime.now().timestamp())}"
        db["schedules"][sched_id] = {
            "chat_id": state["chat_id"],
            "times": state["times"],
            "recurrence": state["recurrence"],
            "content": content,
            "created_at": datetime.datetime.now().isoformat(),
            "setup_msg_ids": [],  # نملأها بعد إرسال رسالة التأكيد
        }

        times_str = " / ".join(f"{t['hour']:02d}:{t['minute']:02d}" for t in state["times"])
        rec_desc = recurrence_description(state["recurrence"])
        confirm = await event.reply(
            f"✅ تم جدولة الرسالة بنجاح.\n⏰ الأوقات: {times_str}\n🔁 التكرار: {rec_desc}"
        )
        state["conv_msg_ids"].append(confirm.id)

        # نحفظ كل رسائل المحادثة (من لحظة الضغط على "جدولة جديدة" وحتى التأكيد)
        db["schedules"][sched_id]["setup_msg_ids"] = list(state["conv_msg_ids"])
        save_db()
        start_schedule_task(sched_id)

        del scheduling_state[event.sender_id]
        return

    elif state["step"] == "edit_time":
        times = parse_times(text)
        if not times:
            err = await event.reply(
                "⚠️ ما قدرت أفهم الوقت. جرّب مثلاً: 7 صباحا — 19:30 — 7 صباحا و7 مساء"
            )
            state["conv_msg_ids"].append(err.id)
            return

        sched_id = state["sched_id"]
        if sched_id in db["schedules"]:
            db["schedules"][sched_id]["times"] = times
            save_db()
            start_schedule_task(sched_id)  # إعادة تشغيل المؤقتات بالأوقات الجديدة
            times_str = " / ".join(f"{t['hour']:02d}:{t['minute']:02d}" for t in times)
            ok = await event.reply(f"✅ تم تحديث أوقات الجدولة إلى: {times_str}")
            # نضيف رسائل التعديل لقائمة setup_msg_ids الأصلية حتى تُحذف لاحقاً مع الجدولة
            db["schedules"][sched_id].setdefault("setup_msg_ids", [])
            db["schedules"][sched_id]["setup_msg_ids"].extend(state["conv_msg_ids"] + [ok.id])
            save_db()
        else:
            err = await event.reply("❌ لم يتم العثور على هذه الجدولة (ربما حُذفت).")
            state["conv_msg_ids"].append(err.id)

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
            "✨ الملف الشخصي ✨\n\n"
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
