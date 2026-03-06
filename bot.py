import os
import re
import sqlite3
import asyncio
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message,
    ChatPermissions,
)

from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("34257542"))
API_HASH = os.getenv("614a1b5c5b712ac6de5530d5c571c42a")
BOT_TOKEN = os.getenv("7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw")

app = Client("fajr_jadid_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
scheduler = AsyncIOScheduler(timezone="Asia/Riyadh")

DB = "bot.db"


# ---------------------- قاعدة البيانات ---------------------- #

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # تذكيرات نصية / وسائط
    c.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        user_id INTEGER,
        text TEXT,
        media_type TEXT,  -- none / photo / video
        media_file_id TEXT,
        kind TEXT,        -- interval / datetime
        interval_seconds INTEGER,
        run_at DATETIME,
        created_at DATETIME
    )
    """)

    # ردود جاهزة
    c.execute("""
    CREATE TABLE IF NOT EXISTS custom_replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        trigger TEXT,
        reply TEXT
    )
    """)

    # ربط نص -> صورة/فيديو
    c.execute("""
    CREATE TABLE IF NOT EXISTS media_triggers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        trigger TEXT,
        media_type TEXT,
        file_id TEXT
    )
    """)

    # تعافي
    c.execute("""
    CREATE TABLE IF NOT EXISTS recovery_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        user_id INTEGER,
        index_pos INTEGER,
        item_type TEXT,   -- text/photo/video/voice/audio/document/link
        text TEXT,
        file_id TEXT,
        url TEXT
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS recovery_state (
        chat_id INTEGER PRIMARY KEY,
        next_index INTEGER
    )
    """)

    # كتم / انذارات
    c.execute("""
    CREATE TABLE IF NOT EXISTS punishments (
        chat_id INTEGER,
        user_id INTEGER,
        warnings INTEGER DEFAULT 0,
        muted_until DATETIME,
        PRIMARY KEY (chat_id, user_id)
    )
    """)

    # احصائيات رسائل
    c.execute("""
    CREATE TABLE IF NOT EXISTS message_stats (
        chat_id INTEGER,
        user_id INTEGER,
        count INTEGER DEFAULT 0,
        PRIMARY KEY (chat_id, user_id)
    )
    """)

    conn.commit()
    conn.close()


def db():
    return sqlite3.connect(DB)


# ---------------------- صلاحيات الأوامر ---------------------- #

async def is_admin_or_owner(message: Message) -> bool:
    if message.chat.type not in (enums.ChatType.SUPERGROUP, enums.ChatType.GROUP):
        return True
    member = await app.get_chat_member(message.chat.id, message.from_user.id)
    return member.status in (
        enums.ChatMemberStatus.ADMINISTRATOR,
        enums.ChatMemberStatus.OWNER,
    )


async def ensure_admin(message: Message) -> bool:
    if not await is_admin_or_owner(message):
        await message.reply_text("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
        return False
    return True


# ---------------------- تحليل المدة بالعربي ---------------------- #

def parse_duration(text: str) -> int | None:
    """
    يرجع عدد الثواني من نص عربي مثل:
    كل ١٠ دقائق / بعد 3 ساعات / كل يوم / كل يومين / بعد ساعة / بعد 30 دقيقة
    """
    text = text.replace("ساعة", "ساعه")
    text = text.replace("يوميًا", "كل يوم")
    text = text.strip()

    # 'كل يوم' أو 'كل يومين'
    if re.search(r"كل\s*يومين", text):
        return 2 * 24 * 3600
    if re.search(r"كل\s*يوم", text):
        return 24 * 3600

    # 'كل X دقيقة/ساعه/ساعات'
    m = re.search(r"كل\s*(\d+)\s*(دقيقة|دقائق|دقيقه|ساعه|ساعات|ساعة)", text)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        if "دقي" in unit:
            return num * 60
        else:
            return num * 3600

    # 'بعد X ...'
    m = re.search(r"بعد\s*(\d+)\s*(دقيقة|دقائق|دقيقه|ساعه|ساعات|ساعة|يوم|ايام|أيام)", text)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        if "دقي" in unit:
            return num * 60
        elif "ساع" in unit:
            return num * 3600
        else:
            return num * 24 * 3600

    # 'بعد ساعه' بدون رقم
    if re.search(r"بعد\s*ساعه", text):
        return 3600
    if re.search(r"بعد\s*يوم", text):
        return 24 * 3600

    return None


def parse_datetime_ar(text: str) -> datetime | None:
    """
    يحاول قراءة وقت مثل:
    بكرى في الساعه 4:55
    غداً 16:30
    اليوم 18:00
    2026-03-07 16:30
    """
    text = text.strip()
    now = datetime.now()

    # بكرى / غداً
    if "بكرا" in text or "بكرى" in text or "غداً" in text or "غدا" in text:
        base = now + timedelta(days=1)
    elif "اليوم" in text:
        base = now
    else:
        base = now

    m = re.search(r"(\d{1,2})\s*[:：]\s*(\d{2})", text)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2))
        dt = datetime(base.year, base.month, base.day, h, mi)
        if dt < now:
            dt += timedelta(days=1)
        return dt

    # ISO
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


# ---------------------- جدولة المهام ---------------------- #

async def send_reminder(chat_id: int, text: str, media_type: str | None, media_file_id: str | None):
    if media_type == "photo" and media_file_id:
        await app.send_photo(chat_id, media_file_id, caption=text or "")
    elif media_type == "video" and media_file_id:
        await app.send_video(chat_id, media_file_id, caption=text or "")
    else:
        await app.send_message(chat_id, text)


def schedule_existing_reminders():
    conn = db()
    c = conn.cursor()
    c.execute("SELECT id, chat_id, text, media_type, media_file_id, kind, interval_seconds, run_at FROM reminders")
    rows = c.fetchall()
    conn.close()

    for rid, chat_id, text, media_type, file_id, kind, interval_seconds, run_at in rows:
        if kind == "interval" and interval_seconds:
            scheduler.add_job(
                send_reminder,
                IntervalTrigger(seconds=interval_seconds),
                args=[chat_id, text, media_type, file_id],
                id=f"rem_{rid}",
                replace_existing=True
            )
        elif kind == "datetime" and run_at:
            dt = datetime.fromisoformat(run_at)
            if dt > datetime.now():
                scheduler.add_job(
                    send_reminder,
                    DateTrigger(run_date=dt),
                    args=[chat_id, text, media_type, file_id],
                    id=f"rem_{rid}",
                    replace_existing=True
                )


# ---------------------- رسالة الترحيب ---------------------- #

WELCOME_TEXT = (
    "اهلاً بك في فجـر جـديد 🙋🏻‍♂️\n\n"
    "خطوة صغيرة اليوم… تصنع فرق كبير غدًا 🌅\n\n"
    "• ممنوع السلبية أو إحباط الآخرين ❌\n"
    "• لا يُسمح بأي محتوى غير لائق 🚫\n"
    "• الاحترام أسلوبنا الدائم 🤝\n"
    "• شارك بما يفيد ويحفّز غيرك 📌\n"
    "• التزامك اليوم هو نجاحك غداً 🌇"
)


@app.on_chat_member_updated()
async def on_added(client, event):
    if event.new_chat_member and event.new_chat_member.user.is_bot and event.new_chat_member.user.id == (await app.get_me()).id:
        await app.send_message(event.chat.id, WELCOME_TEXT)


# ---------------------- إحصائيات الرسائل ---------------------- #

@app.on_message(filters.group & ~filters.service)
async def count_messages(client, message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    conn = db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO message_stats(chat_id, user_id, count)
        VALUES (?, ?, 1)
        ON CONFLICT(chat_id, user_id)
        DO UPDATE SET count = count + 1
    """, (chat_id, user_id))
    conn.commit()
    conn.close()


# ---------------------- ميزة "ا" معلومات العضو ---------------------- #

@app.on_message(filters.group & filters.text & filters.regex(r"^ا$"))
async def user_info(client, message: Message):
    user = message.from_user
    chat = message.chat

    conn = db()
    c = conn.cursor()
    c.execute("SELECT count FROM message_stats WHERE chat_id = ? AND user_id = ?", (chat.id, user.id))
    row = c.fetchone()
    count = row[0] if row else 0

    c.execute("SELECT user_id, count FROM message_stats WHERE chat_id = ? ORDER BY count DESC", (chat.id,))
    rows = c.fetchall()
    conn.close()

    rank = 0
    for i, (uid, cnt) in enumerate(rows, start=1):
        if uid == user.id:
            rank = i
            break

    member = await app.get_chat_member(chat.id, user.id)
    join_date = member.joined_date.strftime("%Y-%m-%d") if member.joined_date else "غير معروف"

    caption = (
        f"👤 الاسم: {user.mention}\n"
        f"🆔 المعرف: {user.id}\n"
        f"💬 عدد رسائلك: {count}\n"
        f"📅 تاريخ الانضمام: {join_date}\n"
        f"🏆 ترتيبك في التفاعل: {rank if rank else 'غير مصنف'}"
    )

    photos = await app.get_profile_photos(user.id, limit=1)
    if photos.total_count > 0:
        await app.send_photo(chat.id, photos[0].file_id, caption=caption)
    else:
        await app.send_message(chat.id, caption)


# ---------------------- تذكير نصي متكرر ---------------------- #

PENDING_REMINDERS = {}  # {(chat_id, user_id): {"text": str}}

@app.on_message(filters.group & filters.text & filters.regex(r"^تذكير\s*\\((.+)\\)$"))
async def start_reminder(client, message: Message):
    text = re.findall(r"^تذكير\s*\\((.+)\\)$", message.text)[0]
    PENDING_REMINDERS[(message.chat.id, message.from_user.id)] = {"text": text, "media_type": None, "file_id": None}
    await message.reply_text("حسناً الان حدد المدة ⏰ (مثال: كل ١٠ دقائق، كل ساعتين، كل يوم، كل يومين)")


@app.on_message(filters.group & filters.text)
async def handle_reminder_duration_and_general_text(client, message: Message):
    key = (message.chat.id, message.from_user.id)
    if key in PENDING_REMINDERS:
        # محاولة فهم كمدة
        seconds = parse_duration(message.text)
        if seconds is None:
            await message.reply_text("لم أفهم المدة، حاول مثلاً: كل 10 دقائق / كل ساعتين / كل يوم / كل يومين.")
            return

        info = PENDING_REMINDERS.pop(key)
        conn = db()
        c = conn.cursor()
        c.execute("""
            INSERT INTO reminders(chat_id, user_id, text, media_type, media_file_id, kind, interval_seconds, run_at, created_at)
            VALUES (?, ?, ?, ?, ?, 'interval', ?, NULL, ?)
        """, (
            message.chat.id,
            message.from_user.id,
            info["text"],
            info["media_type"],
            info["file_id"],
            seconds,
            datetime.now().isoformat()
        ))
        rid = c.lastrowid
        conn.commit()
        conn.close()

        scheduler.add_job(
            send_reminder,
            IntervalTrigger(seconds=seconds),
            args=[message.chat.id, info["text"], info["media_type"], info["file_id"]],
            id=f"rem_{rid}",
            replace_existing=True
        )
        await message.reply_text("تم إضافة التذكير ✅")
        return

    # إذا ليس تذكير معلّق، نكمل إلى مكونات أخرى (ردود، media triggers، تعافي ...)
    await handle_custom_replies_and_triggers(client, message)


# ---------------------- تذكير صورة/فيديو بوقت محدد ---------------------- #

PENDING_MEDIA_REMINDER = {}  # {(chat_id, user_id): {"text": str}}

@app.on_message(filters.group & filters.text & filters.regex(r"^تذكير\s+(صوره|صورة|فيديو)\s*\\((.+)\\)$"))
async def start_media_reminder(client, message: Message):
    m = re.findall(r"^تذكير\s+(صوره|صورة|فيديو)\s*\\((.+)\\)$", message.text)[0]
    media_word, text = m
    PENDING_MEDIA_REMINDER[(message.chat.id, message.from_user.id)] = {
        "text": text,
        "media_type": media_word
    }
    await message.reply_text("اكتب الوقت المطلوب (مثال: بكرى في الساعه 4:55)")


@app.on_message(filters.group & filters.text)
async def handle_media_reminder_time(client, message: Message):
    key = (message.chat.id, message.from_user.id)
    if key in PENDING_MEDIA_REMINDER:
        info = PENDING_MEDIA_REMINDER.pop(key)

        dt = parse_datetime_ar(message.text)
        if not dt:
            await message.reply_text("لم أفهم الوقت، حاول مثل: بكرى في الساعه 4:55 أو 2026-03-07 16:30")
            return

        await message.reply_text("هل تريد اضافة فيديو او صوره؟ (اكتب: نعم أو لا)")
        PENDING_MEDIA_REMINDER[key] = {"text": info["text"], "media_type": info["media_type"], "run_at": dt.isoformat(), "await_media": True}
        return

    # استقبال الوسائط بعد الموافقة
    if key in PENDING_MEDIA_REMINDER:
        # لن يصل هنا عملياً لأننا أعدنا الكتابة بالأعلى؛ تركناه للحماية فقط
        pass


@app.on_message(filters.group & (filters.photo | filters.video))
async def handle_media_file_for_reminder(client, message: Message):
    key = (message.chat.id, message.from_user.id)
    if key in PENDING_MEDIA_REMINDER and PENDING_MEDIA_REMINDER[key].get("await_media"):
        info = PENDING_MEDIA_REMINDER.pop(key)
        media_type = "photo" if message.photo else "video"
        file_id = message.photo.file_id if message.photo else message.video.file_id

        conn = db()
        c = conn.cursor()
        c.execute("""
            INSERT INTO reminders(chat_id, user_id, text, media_type, media_file_id, kind, interval_seconds, run_at, created_at)
            VALUES (?, ?, ?, ?, ?, 'datetime', NULL, ?, ?)
        """, (
            message.chat.id,
            message.from_user.id,
            info["text"],
            media_type,
            file_id,
            info["run_at"],
            datetime.now().isoformat()
        ))
        rid = c.lastrowid
        conn.commit()
        conn.close()

        dt = datetime.fromisoformat(info["run_at"])
        scheduler.add_job(
            send_reminder,
            DateTrigger(run_date=dt),
            args=[message.chat.id, info["text"], media_type, file_id],
            id=f"rem_{rid}",
            replace_existing=True
        )
        await message.reply_text("تم اضافة التذكير مع الوسائط ✅")


@app.on_message(filters.group & filters.text & filters.regex(r"^(?i)(نعم|لا)$"))
async def yes_no_media_reminder(client, message: Message):
    key = (message.chat.id, message.from_user.id)
    if key in PENDING_MEDIA_REMINDER and "run_at" in PENDING_MEDIA_REMINDER[key]:
        info = PENDING_MEDIA_REMINDER[key]
        if message.text.strip().lower() in ["نعم", "yes"]:
            await message.reply_text("حسنا ارسل الصورة أو الفيديو الآن.")
            info["await_media"] = True
            PENDING_MEDIA_REMINDER[key] = info
            return
        else:
            # بدون وسائط
            PENDING_MEDIA_REMINDER.pop(key)
            conn = db()
            c = conn.cursor()
            c.execute("""
                INSERT INTO reminders(chat_id, user_id, text, media_type, media_file_id, kind, interval_seconds, run_at, created_at)
                VALUES (?, ?, ?, NULL, NULL, 'datetime', NULL, ?, ?)
            """, (
                message.chat.id,
                message.from_user.id,
                info["text"],
                info["run_at"],
                datetime.now().isoformat()
            ))
            rid = c.lastrowid
            conn.commit()
            conn.close()

            dt = datetime.fromisoformat(info["run_at"])
            scheduler.add_job(
                send_reminder,
                DateTrigger(run_date=dt),
                args=[message.chat.id, info["text"], None, None],
                id=f"rem_{rid}",
                replace_existing=True
            )
            await message.reply_text("تم اضافة التذكير ✅")


# ---------------------- ربط نص -> صورة / فيديو (صوره (النص)) ---------------------- #

PENDING_MEDIA_TRIGGER = {}  # {(chat_id, user_id): {"trigger": str, "type": "photo"/"video"}}

@app.on_message(filters.group & filters.text & filters.regex(r"^صوره\s*\\((.+)\\)$"))
async def add_photo_trigger(client, message: Message):
    trigger = re.findall(r"^صوره\s*\\((.+)\\)$", message.text)[0].strip()
    PENDING_MEDIA_TRIGGER[(message.chat.id, message.from_user.id)] = {"trigger": trigger, "type": "photo"}
    await message.reply_text("حسنا ارسل الصورة")


@app.on_message(filters.group & filters.text & filters.regex(r"^فيديو\s*\\((.+)\\)$"))
async def add_video_trigger(client, message: Message):
    trigger = re.findall(r"^فيديو\s*\\((.+)\\)$", message.text)[0].strip()
    PENDING_MEDIA_TRIGGER[(message.chat.id, message.from_user.id)] = {"trigger": trigger, "type": "video"}
    await message.reply_text("حسنا ارسل الفيديو")


@app.on_message(filters.group & (filters.photo | filters.video))
async def save_media_trigger(client, message: Message):
    key = (message.chat.id, message.from_user.id)
    if key not in PENDING_MEDIA_TRIGGER:
        return

    info = PENDING_MEDIA_TRIGGER.pop(key)
    media_type = info["type"]
    if media_type == "photo" and not message.photo:
        return
    if media_type == "video" and not message.video:
        return

    file_id = message.photo.file_id if message.photo else message.video.file_id

    conn = db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO media_triggers(chat_id, trigger, media_type, file_id)
        VALUES (?, ?, ?, ?)
    """, (message.chat.id, info["trigger"], media_type, file_id))
    conn.commit()
    conn.close()

    await message.reply_text("تمت إضافة الصورة/الفيديو ✅")


async def handle_custom_replies_and_triggers(client, message: Message):
    # media triggers
    conn = db()
    c = conn.cursor()
    c.execute("SELECT trigger, media_type, file_id FROM media_triggers WHERE chat_id = ?", (message.chat.id,))
    rows = c.fetchall()

    for trigger, media_type, file_id in rows:
        if message.text.strip() == trigger:
            if media_type == "photo":
                await app.send_photo(message.chat.id, file_id)
            elif media_type == "video":
                await app.send_video(message.chat.id, file_id)
            conn.close()
            return

    # custom replies
    c.execute("SELECT trigger, reply FROM custom_replies WHERE chat_id = ?", (message.chat.id,))
    rows = c.fetchall()
    conn.close()
    for trig, rep in rows:
        if message.text.strip() == trig:
            await message.reply_text(rep)
            return


# ---------------------- تعافي ---------------------- #

PENDING_RECOVERY = {}  # {(chat_id, user_id): bool}

@app.on_message(filters.group & filters.text & filters.regex(r"^تعافي$"))
async def start_recovery(client, message: Message):
    key = (message.chat.id, message.from_user.id)
    if key not in PENDING_RECOVERY:
        # إرسال محتوى مخزن
        conn = db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM recovery_items WHERE chat_id = ?", (message.chat.id,))
        total = c.fetchone()[0]
        if total == 0:
            await message.reply_text("لا يوجد محتوى تعافي بعد.")
            conn.close()
            return

        c.execute("SELECT next_index FROM recovery_state WHERE chat_id = ?", (message.chat.id,))
        row = c.fetchone()
        next_index = row[0] if row else 1
        if next_index > total:
            next_index = 1

        c.execute("SELECT index_pos, item_type, text, file_id, url FROM recovery_items WHERE chat_id = ? AND index_pos = ?",
                  (message.chat.id, next_index))
        item = c.fetchone()
        conn.close()
        if not item:
            await message.reply_text("خطأ في بيانات التعافي.")
            return

        _, item_type, text, file_id, url = item
        if item_type == "text":
            await message.reply_text(text or "")
        elif item_type in ["photo", "video", "voice", "audio", "document"]:
            if item_type == "photo":
                await app.send_photo(message.chat.id, file_id, caption=text or "")
            elif item_type == "video":
                await app.send_video(message.chat.id, file_id, caption=text or "")
            elif item_type == "voice":
                await app.send_voice(message.chat.id, file_id, caption=text or "")
            elif item_type == "audio":
                await app.send_audio(message.chat.id, file_id, caption=text or "")
            elif item_type == "document":
                await app.send_document(message.chat.id, file_id, caption=text or "")
        elif item_type == "link":
            await message.reply_text(f"{text or ''}\n{url or ''}")

        conn = db()
        c = conn.cursor()
        c.execute("""
            INSERT INTO recovery_state(chat_id, next_index)
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET next_index = ?
        """, (message.chat.id, next_index + 1, next_index + 1))
        conn.commit()
        conn.close()
    else:
        # طور الإضافة
        PENDING_RECOVERY.pop(key)
        await message.reply_text("تم الخروج من وضع إضافة التعافي.")


@app.on_message(filters.group & filters.command("تعافي_اضف"))
async def enable_recovery_add(client, message: Message):
    if not await ensure_admin(message):
        return
    PENDING_RECOVERY[(message.chat.id, message.from_user.id)] = True
    await message.reply_text("أرسل المحتوى (نص/صورة/فيديو/رابط/صوتية/الخ) لإضافته لقائمة تعافي.\nللإنهاء اكتب: تعافي مرة أخرى.")


@app.on_message(filters.group & (filters.text | filters.photo | filters.video | filters.voice | filters.audio | filters.document))
async def handle_recovery_add(client, message: Message):
    key = (message.chat.id, message.from_user.id)
    if key not in PENDING_RECOVERY:
        return

    conn = db()
    c = conn.cursor()
    c.execute("SELECT COALESCE(MAX(index_pos), 0) FROM recovery_items WHERE chat_id = ?", (message.chat.id,))
    current_max = c.fetchone()[0]
    next_idx = current_max + 1

    item_type = "text"
    text = ""
    file_id = None
    url = None

    if message.text and not message.entities:
        item_type = "text"
        text = message.text
    elif message.text and message.entities:
        # نفترض رابط
        item_type = "link"
        text = message.text
        url = message.text
    elif message.photo:
        item_type = "photo"
        file_id = message.photo.file_id
        text = message.caption or ""
    elif message.video:
        item_type = "video"
        file_id = message.video.file_id
        text = message.caption or ""
    elif message.voice:
        item_type = "voice"
        file_id = message.voice.file_id
        text = message.caption or ""
    elif message.audio:
        item_type = "audio"
        file_id = message.audio.file_id
        text = message.caption or ""
    elif message.document:
        item_type = "document"
        file_id = message.document.file_id
        text = message.caption or ""

    c.execute("""
        INSERT INTO recovery_items(chat_id, user_id, index_pos, item_type, text, file_id, url)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (message.chat.id, message.from_user.id, next_idx, item_type, text, file_id, url))
    conn.commit()
    conn.close()

    await message.reply_text(f"تمت إضافة عنصر تعافي رقم {next_idx} ✅")


# ---------------------- كتم وإنذارات ---------------------- #

@app.on_message(filters.group & filters.reply & filters.text & filters.regex(r"^كتم$"))
async def mute_user(client, message: Message):
    if not await ensure_admin(message):
        return
    target = message.reply_to_message.from_user
    chat_id = message.chat.id

    until = datetime.now() + timedelta(hours=24)
    await app.restrict_chat_member(
        chat_id,
        target.id,
        ChatPermissions(),  # بدون صلاحيات
        until_date=until
    )

    conn = db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO punishments(chat_id, user_id, warnings, muted_until)
        VALUES (?, ?, 0, ?)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET muted_until = ?
    """, (chat_id, target.id, until.isoformat(), until.isoformat()))
    conn.commit()
    conn.close()

    await message.reply_text(f"تم كتم {target.mention} لمدة 24 ساعة ✅")


@app.on_message(filters.group & filters.reply & filters.text & filters.regex(r"^الغاء كتم$"))
async def unmute_user(client, message: Message):
    if not await ensure_admin(message):
        return
    target = message.reply_to_message.from_user
    chat_id = message.chat.id

    await app.restrict_chat_member(
        chat_id,
        target.id,
        ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True)
    )

    conn = db()
    c = conn.cursor()
    c.execute("""
        UPDATE punishments SET muted_until = NULL WHERE chat_id = ? AND user_id = ?
    """, (chat_id, target.id))
    conn.commit()
    conn.close()

    await message.reply_text(f"تم إلغاء الكتم عن {target.mention} ✅")


@app.on_message(filters.group & filters.reply & filters.text & filters.regex(r"^انذار$"))
async def warn_user(client, message: Message):
    if not await ensure_admin(message):
        return
    target = message.reply_to_message.from_user
    chat_id = message.chat.id

    conn = db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO punishments(chat_id, user_id, warnings, muted_until)
        VALUES (?, ?, 1, NULL)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET warnings = warnings + 1
    """, (chat_id, target.id))
    conn.commit()
    c.execute("SELECT warnings FROM punishments WHERE chat_id = ? AND user_id = ?", (chat_id, target.id))
    warnings = c.fetchone()[0]
    conn.close()

    if warnings >= 3:
        until = datetime.now() + timedelta(hours=6)
        await app.restrict_chat_member(
            chat_id,
            target.id,
            ChatPermissions(),
            until_date=until
        )
        await message.reply_text(f"وصل {target.mention} إلى 3 انذارات وتم كتمه 6 ساعات.")
    else:
        await message.reply_text(f"تم إعطاء {target.mention} انذار {warnings}/3.")


# ---------------------- ردود جاهزة (اضف رد) ---------------------- #

PENDING_CUSTOM_REPLY = {}  # {(chat_id, user_id): {"trigger": str}}

@app.on_message(filters.group & filters.text & filters.regex(r"^اضف رد\s*\\((.+)\\)$"))
async def add_custom_reply_trigger(client, message: Message):
    if not await ensure_admin(message):
        return
    trigger = re.findall(r"^اضف رد\s*\\((.+)\\)$", message.text)[0].strip()
    PENDING_CUSTOM_REPLY[(message.chat.id, message.from_user.id)] = {"trigger": trigger}
    await message.reply_text("اضف النص المطلوب")


@app.on_message(filters.group & filters.text)
async def save_custom_reply(client, message: Message):
    key = (message.chat.id, message.from_user.id)
    if key not in PENDING_CUSTOM_REPLY:
        return
    info = PENDING_CUSTOM_REPLY.pop(key)
    trigger = info["trigger"]
    reply = message.text

    conn = db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO custom_replies(chat_id, trigger, reply)
        VALUES (?, ?, ?)
    """, (message.chat.id, trigger, reply))
    conn.commit()
    conn.close()

    await message.reply_text("تم اضافة النص ✅")


# ---------------------- منشن جماعي all ---------------------- #

@app.on_message(filters.group & filters.text & filters.regex(r"^all(\s+.*)?$"))
async def mention_all(client, message: Message):
    if not await ensure_admin(message):
        return
    extra = ""
    m = re.match(r"^all\s+(.+)$", message.text)
    if m:
        extra = m.group(1)

    members = []
    async for m in app.get_chat_members(message.chat.id):
        if m.user.is_bot:
            continue
        members.append(m.user)

    chunk_size = 5
    for i in range(0, len(members), chunk_size):
        chunk = members[i:i+chunk_size]
        text = extra + "\n" if extra else ""
        text += " ".join(user.mention for user in chunk)
        await app.send_message(message.chat.id, text)


# ---------------------- بدء التشغيل ---------------------- #

if _name_ == "_main_":
    init_db()
    scheduler.start()
    schedule_existing_reminders()
    print("Bot running...")
    app.run()

