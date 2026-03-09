import os
import re
import sqlite3
import asyncio
from datetime import datetime, timedelta
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

# الإعدادات الأساسية
API_ID = 34257542
API_HASH = "614a1b5c5b712ac6de5530d5c571c42a"
BOT_TOKEN = "7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw"

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
    try:
        member = await app.get_chat_member(message.chat.id, message.from_user.id)
        return member.status in (
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        )
    except Exception:
        return False


async def ensure_admin(message: Message) -> bool:
    if not await is_admin_or_owner(message):
        await message.reply_text("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
        return False
    return True


# ---------------------- تحليل المدة بالعربي ---------------------- #

def parse_duration(text: str) -> int | None:
    text = text.replace("ساعة", "ساعه")
    text = text.replace("يوميًا", "كل يوم")
    text = text.strip()

    if re.search(r"كل\s*يومين", text):
        return 2 * 24 * 3600
    if re.search(r"كل\s*يوم", text):
        return 24 * 3600

    m = re.search(r"كل\s*(\d+)\s*(دقيقة|دقائق|دقيقه|ساعه|ساعات|ساعة)", text)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        if "دقي" in unit:
            return num * 60
        else:
            return num * 3600

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

    if re.search(r"بعد\s*ساعه", text):
        return 3600
    if re.search(r"بعد\s*يوم", text):
        return 24 * 3600

    return None


def parse_datetime_ar(text: str) -> datetime | None:
    text = text.strip()
    now = datetime.now()

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

    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


# ---------------------- جدولة المهام ---------------------- #

async def send_reminder(chat_id: int, text: str, media_type: str | None, media_file_id: str | None):
    try:
        if media_type == "photo" and media_file_id:
            await app.send_photo(chat_id, media_file_id, caption=text or "")
        elif media_type == "video" and media_file_id:
            await app.send_video(chat_id, media_file_id, caption=text or "")
        else:
            await app.send_message(chat_id, text)
    except Exception as e:
        print(f"Error in send_reminder: {e}")


def schedule_existing_reminders():
    conn = db()
    c = conn.cursor()
    c.execute("SELECT id, chat_id, text, media_type, media_file_id, kind, interval_seconds, run_at FROM reminders")
    rows = c.fetchall()
    conn.close()

    for rid, chat_id, text, media_type, file_id, kind, interval_seconds, run_at in rows:
        try:
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
        except Exception:
            continue


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
    try:
        if event.new_chat_member and event.new_chat_member.user.is_bot and event.new_chat_member.user.id == (await app.get_me()).id:
            await app.send_message(event.chat.id, WELCOME_TEXT)
    except Exception:
        pass


# ---------------------- إحصائيات الرسائل ---------------------- #

@app.on_message(filters.group & ~filters.service, group=1)
async def count_messages(client, message: Message):
    if not message.from_user: return
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

@app.on_message(filters.group & filters.text & filters.regex(r"^ا$"), group=2)
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

    try:
        member = await app.get_chat_member(chat.id, user.id)
        join_date = member.joined_date.strftime("%Y-%m-%d") if member.joined_date else "غير معروف"
    except:
        join_date = "غير معروف"

    caption = (
        f"👤 الاسم: {user.mention}\n"
        f"🆔 المعرف: {user.id}\n"
        f"💬 عدد رسائلك: {count}\n"
        f"📅 تاريخ الانضمام: {join_date}\n"
        f"🏆 ترتيبك في التفاعل: {rank if rank else 'غير مصنف'}"
    )

    try:
        photos = await app.get_profile_photos(user.id, limit=1)
        if photos.total_count > 0:
            await app.send_photo(chat.id, photos[0].file_id, caption=caption)
        else:
            await app.send_message(chat.id, caption)
    except:
        await app.send_message(chat.id, caption)


# ---------------------- تذكير نصي متكرر ---------------------- #

PENDING_REMINDERS = {}

@app.on_message(filters.group & filters.text & filters.regex(r"^تذكير\s*\\((.+)\\)$"), group=3)
async def start_reminder(client, message: Message):
    text = re.findall(r"^تذكير\s*\\((.+)\\)$", message.text)[0]
    PENDING_REMINDERS[(message.chat.id, message.from_user.id)] = {"text": text, "media_type": None, "file_id": None}
    await message.reply_text("حسناً الان حدد المدة ⏰ (مثال: كل ١٠ دقائق، كل ساعتين، كل يوم، كل يومين)")


# ---------------------- تذكير صورة/فيديو بوقت محدد ---------------------- #

PENDING_MEDIA_REMINDER = {}

@app.on_message(filters.group & filters.text & filters.regex(r"^تذكير\s+(صوره|صورة|فيديو)\s*\\((.+)\\)$"), group=4)
async def start_media_reminder(client, message: Message):
    m = re.findall(r"^تذكير\s+(صوره|صورة|فيديو)\s*\\((.+)\\)$", message.text)[0]
    media_word, text = m
    PENDING_MEDIA_REMINDER[(message.chat.id, message.from_user.id)] = {
        "text": text,
        "media_type": media_word
    }
    await message.reply_text("اكتب الوقت المطلوب (مثال: بكرى في الساعه 4:55)")


# ---------------------- ربط نص -> صورة / فيديو ---------------------- #

PENDING_MEDIA_TRIGGER = {}

@app.on_message(filters.group & filters.text & filters.regex(r"^(صوره|فيديو)\s*\\((.+)\\)$"), group=5)
async def add_media_trigger_command(client, message: Message):
    m = re.findall(r"^(صوره|فيديو)\s*\\((.+)\\)$", message.text)[0]
    m_type = "photo" if "صوره" in m[0] else "video"
    trigger = m[1].strip()
    PENDING_MEDIA_TRIGGER[(message.chat.id, message.from_user.id)] = {"trigger": trigger, "type": m_type}
    await message.reply_text(f"حسنا ارسل {'الصورة' if m_type=='photo' else 'الفيديو'}")


# ---------------------- تعافي ---------------------- #

PENDING_RECOVERY = {}

@app.on_message(filters.group & filters.text & filters.regex(r"^تعافي$"), group=6)
async def recovery_logic(client, message: Message):
    key = (message.chat.id, message.from_user.id)
    if key in PENDING_RECOVERY:
        PENDING_RECOVERY.pop(key)
        await message.reply_text("تم الخروج من وضع إضافة التعافي.")
        return

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
    if next_index > total: next_index = 1

    c.execute("SELECT item_type, text, file_id, url FROM recovery_items WHERE chat_id = ? AND index_pos = ?", (message.chat.id, next_index))
    item = c.fetchone()
    if not item:
        conn.close()
        return

    it_type, it_text, it_file, it_url = item
    if it_type == "text": await message.reply_text(it_text)
    elif it_type == "photo": await app.send_photo(message.chat.id, it_file, caption=it_text)
    elif it_type == "video": await app.send_video(message.chat.id, it_file, caption=it_text)
    elif it_type == "voice": await app.send_voice(message.chat.id, it_file, caption=it_text)
    elif it_type == "audio": await app.send_audio(message.chat.id, it_file, caption=it_text)
    elif it_type == "document": await app.send_document(message.chat.id, it_file, caption=it_text)
    elif it_type == "link": await message.reply_text(f"{it_text}\n{it_url}")

    c.execute("INSERT INTO recovery_state(chat_id, next_index) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET next_index = ?", (message.chat.id, next_index + 1, next_index + 1))
    conn.commit()
    conn.close()


@app.on_message(filters.group & filters.command("تعافي_اضف"), group=7)
async def enable_recovery_add(client, message: Message):
    if not await ensure_admin(message): return
    PENDING_RECOVERY[(message.chat.id, message.from_user.id)] = True
    await message.reply_text("أرسل المحتوى الآن لإضافته لقائمة تعافي.\nللإنهاء اكتب: تعافي.")


# ---------------------- كتم وإنذارات ---------------------- #

@app.on_message(filters.group & filters.reply & filters.text & filters.regex(r"^كتم$"), group=8)
async def mute_user(client, message: Message):
    if not await ensure_admin(message): return
    target = message.reply_to_message.from_user
    until = datetime.now() + timedelta(hours=24)
    await app.restrict_chat_member(message.chat.id, target.id, ChatPermissions(), until_date=until)
    conn = db(); c = conn.cursor()
    c.execute("INSERT INTO punishments(chat_id, user_id, muted_until) VALUES (?, ?, ?) ON CONFLICT(chat_id, user_id) DO UPDATE SET muted_until = ?", (message.chat.id, target.id, until.isoformat(), until.isoformat()))
    conn.commit(); conn.close()
    await message.reply_text(f"تم كتم {target.mention} لمدة 24 ساعة ✅")


@app.on_message(filters.group & filters.reply & filters.text & filters.regex(r"^انذار$"), group=9)
async def warn_user(client, message: Message):
    if not await ensure_admin(message): return
    target = message.reply_to_message.from_user
    conn = db(); c = conn.cursor()
    c.execute("INSERT INTO punishments(chat_id, user_id, warnings) VALUES (?, ?, 1) ON CONFLICT(chat_id, user_id) DO UPDATE SET warnings = warnings + 1", (message.chat.id, target.id))
    conn.commit()
    c.execute("SELECT warnings FROM punishments WHERE chat_id = ? AND user_id = ?", (message.chat.id, target.id))
    w = c.fetchone()[0]
    conn.close()
    if w >= 3:
        await app.restrict_chat_member(message.chat.id, target.id, ChatPermissions(), until_date=datetime.now()+timedelta(hours=6))
        await message.reply_text(f"وصل {target.mention} لـ 3 انذارات وكتم 6 ساعات.")
    else:
        await message.reply_text(f"تم انذار {target.mention} ({w}/3)")


# ---------------------- ردود جاهزة ---------------------- #

PENDING_CUSTOM_REPLY = {}

@app.on_message(filters.group & filters.text & filters.regex(r"^اضف رد\s*\\((.+)\\)$"), group=10)
async def add_custom_reply_cmd(client, message: Message):
    if not await ensure_admin(message): return
    trig = re.findall(r"^اضف رد\s*\\((.+)\\)$", message.text)[0].strip()
    PENDING_CUSTOM_REPLY[(message.chat.id, message.from_user.id)] = {"trigger": trig}
    await message.reply_text("اضف النص المطلوب")


# ---------------------- منشن جماعي ---------------------- #

@app.on_message(filters.group & filters.text & filters.regex(r"^all(\s+.*)?$"), group=11)
async def mention_all(client, message: Message):
    if not await ensure_admin(message): return
    extra = ""
    m = re.match(r"^all\s+(.+)$", message.text)
    if m: extra = m.group(1)
    members = []
    async for member in app.get_chat_members(message.chat.id):
        if not member.user.is_bot: members.append(member.user.mention)
    for i in range(0, len(members), 5):
        await app.send_message(message.chat.id, (extra + "\n" if extra else "") + " ".join(members[i:i+5]))


# ---------------------- معالج الرسائل العام (المنطق الموحد) ---------------------- #

@app.on_message(filters.group & (filters.text | filters.photo | filters.video | filters.voice | filters.audio | filters.document), group=12)
async def global_handler(client, message: Message):
    key = (message.chat.id, message.from_user.id)
    text = message.text or message.caption or ""

    # 1. معالجة تذكير نصي متكرر
    if key in PENDING_REMINDERS:
        secs = parse_duration(text)
        if secs:
            info = PENDING_REMINDERS.pop(key)
            conn = db(); c = conn.cursor()
            c.execute("INSERT INTO reminders(chat_id, user_id, text, kind, interval_seconds, created_at) VALUES (?,?,?, 'interval', ?, ?)", (message.chat.id, message.from_user.id, info["text"], secs, datetime.now().isoformat()))
            rid = c.lastrowid; conn.commit(); conn.close()
            scheduler.add_job(send_reminder, IntervalTrigger(seconds=secs), args=[message.chat.id, info["text"], None, None], id=f"rem_{rid}")
            await message.reply_text("تم إضافة التذكير ✅")
            return

    # 2. معالجة وقت تذكير الوسائط
    if key in PENDING_MEDIA_REMINDER and "run_at" not in PENDING_MEDIA_REMINDER[key]:
        dt = parse_datetime_ar(text)
        if dt:
            PENDING_MEDIA_REMINDER[key]["run_at"] = dt.isoformat()
            await message.reply_text("هل تريد اضافة فيديو او صوره؟ (نعم / لا)")
            return

    # 3. معالجة نعم/لا للوسائط
    if key in PENDING_MEDIA_REMINDER and "run_at" in PENDING_MEDIA_REMINDER[key] and not PENDING_MEDIA_REMINDER[key].get("await_media"):
        if text == "نعم":
            PENDING_MEDIA_REMINDER[key]["await_media"] = True
            await message.reply_text("ارسل الوسائط الآن.")
            return
        elif text == "لا":
            info = PENDING_MEDIA_REMINDER.pop(key)
            conn = db(); c = conn.cursor()
            c.execute("INSERT INTO reminders(chat_id, user_id, text, kind, run_at, created_at) VALUES (?,?,?, 'datetime', ?, ?)", (message.chat.id, message.from_user.id, info["text"], info["run_at"], datetime.now().isoformat()))
            rid = c.lastrowid; conn.commit(); conn.close()
            scheduler.add_job(send_reminder, DateTrigger(run_date=datetime.fromisoformat(info["run_at"])), args=[message.chat.id, info["text"], None, None], id=f"rem_{rid}")
            await message.reply_text("تم إضافة التذكير ✅")
            return

    # 4. استقبال ملف تذكير الوسائط
    if key in PENDING_MEDIA_REMINDER and PENDING_MEDIA_REMINDER[key].get("await_media"):
        m_type = "photo" if message.photo else "video" if message.video else None
        if m_type:
            f_id = message.photo.file_id if message.photo else message.video.file_id
            info = PENDING_MEDIA_REMINDER.pop(key)
            conn = db(); c = conn.cursor()
            c.execute("INSERT INTO reminders(chat_id, user_id, text, media_type, media_file_id, kind, run_at, created_at) VALUES (?,?,?,?,?, 'datetime', ?, ?)", (message.chat.id, message.from_user.id, info["text"], m_type, f_id, info["run_at"], datetime.now().isoformat()))
            rid = c.lastrowid; conn.commit(); conn.close()
            scheduler.add_job(send_reminder, DateTrigger(run_date=datetime.fromisoformat(info["run_at"])), args=[message.chat.id, info["text"], m_type, f_id], id=f"rem_{rid}")
            await message.reply_text("تم الإضافة مع الوسائط ✅")
            return

    # 5. حفظ Media Trigger
    if key in PENDING_MEDIA_TRIGGER:
        f_id = message.photo.file_id if message.photo else message.video.file_id if message.video else None
        if f_id:
            info = PENDING_MEDIA_TRIGGER.pop(key)
            conn = db(); c = conn.cursor()
            c.execute("INSERT INTO media_triggers(chat_id, trigger, media_type, file_id) VALUES (?,?,?,?)", (message.chat.id, info["trigger"], info["type"], f_id))
            conn.commit(); conn.close()
            await message.reply_text("تم الحفظ ✅")
            return

    # 6. حفظ رد مخصص
    if key in PENDING_CUSTOM_REPLY:
        info = PENDING_CUSTOM_REPLY.pop(key)
        conn = db(); c = conn.cursor()
        c.execute("INSERT INTO custom_replies(chat_id, trigger, reply) VALUES (?,?,?)", (message.chat.id, info["trigger"], text))
        conn.commit(); conn.close()
        await message.reply_text("تم الحفظ ✅")
        return

    # 7. إضافة عنصر تعافي
    if key in PENDING_RECOVERY:
        m_type = "text"; f_id = None; url = None
        if message.photo: m_type = "photo"; f_id = message.photo.file_id
        elif message.video: m_type = "video"; f_id = message.video.file_id
        elif message.voice: m_type = "voice"; f_id = message.voice.file_id
        elif message.entities: m_type = "link"; url = text
        conn = db(); c = conn.cursor()
        c.execute("SELECT COALESCE(MAX(index_pos), 0) FROM recovery_items WHERE chat_id = ?", (message.chat.id,))
        idx = c.fetchone()[0] + 1
        c.execute("INSERT INTO recovery_items(chat_id, user_id, index_pos, item_type, text, file_id, url) VALUES (?,?,?,?,?,?,?)", (message.chat.id, message.from_user.id, idx, m_type, text, f_id, url))
        conn.commit(); conn.close()
        await message.reply_text(f"تم إضافة عنصر {idx} ✅")
        return

    # 8. تنفيذ الردود والـ Triggers
    if text:
        conn = db(); c = conn.cursor()
        c.execute("SELECT media_type, file_id FROM media_triggers WHERE chat_id = ? AND trigger = ?", (message.chat.id, text))
        m = c.fetchone()
        if m:
            if m[0] == "photo": await app.send_photo(message.chat.id, m[1])
            else: await app.send_video(message.chat.id, m[1])
            conn.close(); return
        c.execute("SELECT reply FROM custom_replies WHERE chat_id = ? AND trigger = ?", (message.chat.id, text))
        r = c.fetchone()
        if r: await message.reply_text(r[0])
        conn.close()


# ---------------------- التشغيل الرئيسي ---------------------- #

if __name__ == "__main__":
    init_db()
    scheduler.start()
    schedule_existing_reminders()
    print("Bot is LIVE!")
    app.run()

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

# الإعدادات الأساسية
API_ID = 34257542
API_HASH = "614a1b5c5b712ac6de5530d5c571c42a"
BOT_TOKEN = "7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw"

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
    try:
        member = await app.get_chat_member(message.chat.id, message.from_user.id)
        return member.status in (
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        )
    except Exception:
        return False


async def ensure_admin(message: Message) -> bool:
    if not await is_admin_or_owner(message):
        await message.reply_text("عذرا هذا الامر خاص بالمشرفين والمالك فقط 🚫")
        return False
    return True


# ---------------------- تحليل المدة بالعربي ---------------------- #

def parse_duration(text: str) -> int | None:
    text = text.replace("ساعة", "ساعه")
    text = text.replace("يوميًا", "كل يوم")
    text = text.strip()

    if re.search(r"كل\s*يومين", text):
        return 2 * 24 * 3600
    if re.search(r"كل\s*يوم", text):
        return 24 * 3600

    m = re.search(r"كل\s*(\d+)\s*(دقيقة|دقائق|دقيقه|ساعه|ساعات|ساعة)", text)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        if "دقي" in unit:
            return num * 60
        else:
            return num * 3600

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

    if re.search(r"بعد\s*ساعه", text):
        return 3600
    if re.search(r"بعد\s*يوم", text):
        return 24 * 3600

    return None


def parse_datetime_ar(text: str) -> datetime | None:
    text = text.strip()
    now = datetime.now()

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

    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


# ---------------------- جدولة المهام ---------------------- #

async def send_reminder(chat_id: int, text: str, media_type: str | None, media_file_id: str | None):
    try:
        if media_type == "photo" and media_file_id:
            await app.send_photo(chat_id, media_file_id, caption=text or "")
        elif media_type == "video" and media_file_id:
            await app.send_video(chat_id, media_file_id, caption=text or "")
        else:
            await app.send_message(chat_id, text)
    except Exception as e:
        print(f"Error in send_reminder: {e}")


def schedule_existing_reminders():
    conn = db()
    c = conn.cursor()
    c.execute("SELECT id, chat_id, text, media_type, media_file_id, kind, interval_seconds, run_at FROM reminders")
    rows = c.fetchall()
    conn.close()

    for rid, chat_id, text, media_type, file_id, kind, interval_seconds, run_at in rows:
        try:
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
        except Exception:
            continue


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
    try:
        if event.new_chat_member and event.new_chat_member.user.is_bot and event.new_chat_member.user.id == (await app.get_me()).id:
            await app.send_message(event.chat.id, WELCOME_TEXT)
    except Exception:
        pass


# ---------------------- إحصائيات الرسائل ---------------------- #

@app.on_message(filters.group & ~filters.service, group=1)
async def count_messages(client, message: Message):
    if not message.from_user: return
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

@app.on_message(filters.group & filters.text & filters.regex(r"^ا$"), group=2)
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

    try:
        member = await app.get_chat_member(chat.id, user.id)
        join_date = member.joined_date.strftime("%Y-%m-%d") if member.joined_date else "غير معروف"
    except:
        join_date = "غير معروف"

    caption = (
        f"👤 الاسم: {user.mention}\n"
        f"🆔 المعرف: {user.id}\n"
        f"💬 عدد رسائلك: {count}\n"
        f"📅 تاريخ الانضمام: {join_date}\n"
        f"🏆 ترتيبك في التفاعل: {rank if rank else 'غير مصنف'}"
    )

    try:
        photos = await app.get_profile_photos(user.id, limit=1)
        if photos.total_count > 0:
            await app.send_photo(chat.id, photos[0].file_id, caption=caption)
        else:
            await app.send_message(chat.id, caption)
    except:
        await app.send_message(chat.id, caption)


# ---------------------- تذكير نصي متكرر ---------------------- #

PENDING_REMINDERS = {}

@app.on_message(filters.group & filters.text & filters.regex(r"^تذكير\s*\\((.+)\\)$"), group=3)
async def start_reminder(client, message: Message):
    text = re.findall(r"^تذكير\s*\\((.+)\\)$", message.text)[0]
    PENDING_REMINDERS[(message.chat.id, message.from_user.id)] = {"text": text, "media_type": None, "file_id": None}
    await message.reply_text("حسناً الان حدد المدة ⏰ (مثال: كل ١٠ دقائق، كل ساعتين، كل يوم، كل يومين)")


# ---------------------- تذكير صورة/فيديو بوقت محدد ---------------------- #

PENDING_MEDIA_REMINDER = {}

@app.on_message(filters.group & filters.text & filters.regex(r"^تذكير\s+(صوره|صورة|فيديو)\s*\\((.+)\\)$"), group=4)
async def start_media_reminder(client, message: Message):
    m = re.findall(r"^تذكير\s+(صوره|صورة|فيديو)\s*\\((.+)\\)$", message.text)[0]
    media_word, text = m
    PENDING_MEDIA_REMINDER[(message.chat.id, message.from_user.id)] = {
        "text": text,
        "media_type": media_word
    }
    await message.reply_text("اكتب الوقت المطلوب (مثال: بكرى في الساعه 4:55)")


# ---------------------- ربط نص -> صورة / فيديو ---------------------- #

PENDING_MEDIA_TRIGGER = {}

@app.on_message(filters.group & filters.text & filters.regex(r"^(صوره|فيديو)\s*\\((.+)\\)$"), group=5)
async def add_media_trigger_command(client, message: Message):
    m = re.findall(r"^(صوره|فيديو)\s*\\((.+)\\)$", message.text)[0]
    m_type = "photo" if "صوره" in m[0] else "video"
    trigger = m[1].strip()
    PENDING_MEDIA_TRIGGER[(message.chat.id, message.from_user.id)] = {"trigger": trigger, "type": m_type}
    await message.reply_text(f"حسنا ارسل {'الصورة' if m_type=='photo' else 'الفيديو'}")


# ---------------------- تعافي ---------------------- #

PENDING_RECOVERY = {}

@app.on_message(filters.group & filters.text & filters.regex(r"^تعافي$"), group=6)
async def recovery_logic(client, message: Message):
    key = (message.chat.id, message.from_user.id)
    if key in PENDING_RECOVERY:
        PENDING_RECOVERY.pop(key)
        await message.reply_text("تم الخروج من وضع إضافة التعافي.")
        return

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
    if next_index > total: next_index = 1

    c.execute("SELECT item_type, text, file_id, url FROM recovery_items WHERE chat_id = ? AND index_pos = ?", (message.chat.id, next_index))
    item = c.fetchone()
    if not item:
        conn.close()
        return

    it_type, it_text, it_file, it_url = item
    if it_type == "text": await message.reply_text(it_text)
    elif it_type == "photo": await app.send_photo(message.chat.id, it_file, caption=it_text)
    elif it_type == "video": await app.send_video(message.chat.id, it_file, caption=it_text)
    elif it_type == "voice": await app.send_voice(message.chat.id, it_file, caption=it_text)
    elif it_type == "audio": await app.send_audio(message.chat.id, it_file, caption=it_text)
    elif it_type == "document": await app.send_document(message.chat.id, it_file, caption=it_text)
    elif it_type == "link": await message.reply_text(f"{it_text}\n{it_url}")

    c.execute("INSERT INTO recovery_state(chat_id, next_index) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET next_index = ?", (message.chat.id, next_index + 1, next_index + 1))
    conn.commit()
    conn.close()


@app.on_message(filters.group & filters.command("تعافي_اضف"), group=7)
async def enable_recovery_add(client, message: Message):
    if not await ensure_admin(message): return
    PENDING_RECOVERY[(message.chat.id, message.from_user.id)] = True
    await message.reply_text("أرسل المحتوى الآن لإضافته لقائمة تعافي.\nللإنهاء اكتب: تعافي.")


# ---------------------- كتم وإنذارات ---------------------- #

@app.on_message(filters.group & filters.reply & filters.text & filters.regex(r"^كتم$"), group=8)
async def mute_user(client, message: Message):
    if not await ensure_admin(message): return
    target = message.reply_to_message.from_user
    until = datetime.now() + timedelta(hours=24)
    await app.restrict_chat_member(message.chat.id, target.id, ChatPermissions(), until_date=until)
    conn = db(); c = conn.cursor()
    c.execute("INSERT INTO punishments(chat_id, user_id, muted_until) VALUES (?, ?, ?) ON CONFLICT(chat_id, user_id) DO UPDATE SET muted_until = ?", (message.chat.id, target.id, until.isoformat(), until.isoformat()))
    conn.commit(); conn.close()
    await message.reply_text(f"تم كتم {target.mention} لمدة 24 ساعة ✅")


@app.on_message(filters.group & filters.reply & filters.text & filters.regex(r"^انذار$"), group=9)
async def warn_user(client, message: Message):
    if not await ensure_admin(message): return
    target = message.reply_to_message.from_user
    conn = db(); c = conn.cursor()
    c.execute("INSERT INTO punishments(chat_id, user_id, warnings) VALUES (?, ?, 1) ON CONFLICT(chat_id, user_id) DO UPDATE SET warnings = warnings + 1", (message.chat.id, target.id))
    conn.commit()
    c.execute("SELECT warnings FROM punishments WHERE chat_id = ? AND user_id = ?", (message.chat.id, target.id))
    w = c.fetchone()[0]
    conn.close()
    if w >= 3:
        await app.restrict_chat_member(message.chat.id, target.id, ChatPermissions(), until_date=datetime.now()+timedelta(hours=6))
        await message.reply_text(f"وصل {target.mention} لـ 3 انذارات وكتم 6 ساعات.")
    else:
        await message.reply_text(f"تم انذار {target.mention} ({w}/3)")


# ---------------------- ردود جاهزة ---------------------- #

PENDING_CUSTOM_REPLY = {}

@app.on_message(filters.group & filters.text & filters.regex(r"^اضف رد\s*\\((.+)\\)$"), group=10)
async def add_custom_reply_cmd(client, message: Message):
    if not await ensure_admin(message): return
    trig = re.findall(r"^اضف رد\s*\\((.+)\\)$", message.text)[0].strip()
    PENDING_CUSTOM_REPLY[(message.chat.id, message.from_user.id)] = {"trigger": trig}
    await message.reply_text("اضف النص المطلوب")


# ---------------------- منشن جماعي ---------------------- #

@app.on_message(filters.group & filters.text & filters.regex(r"^all(\s+.*)?$"), group=11)
async def mention_all(client, message: Message):
    if not await ensure_admin(message): return
    extra = ""
    m = re.match(r"^all\s+(.+)$", message.text)
    if m: extra = m.group(1)
    members = []
    async for member in app.get_chat_members(message.chat.id):
        if not member.user.is_bot: members.append(member.user.mention)
    for i in range(0, len(members), 5):
        await app.send_message(message.chat.id, (extra + "\n" if extra else "") + " ".join(members[i:i+5]))


# ---------------------- معالج الرسائل العام (المنطق الموحد) ---------------------- #

@app.on_message(filters.group & (filters.text | filters.photo | filters.video | filters.voice | filters.audio | filters.document), group=12)
async def global_handler(client, message: Message):
    key = (message.chat.id, message.from_user.id)
    text = message.text or message.caption or ""

    # 1. معالجة تذكير نصي متكرر
    if key in PENDING_REMINDERS:
        secs = parse_duration(text)
        if secs:
            info = PENDING_REMINDERS.pop(key)
            conn = db(); c = conn.cursor()
            c.execute("INSERT INTO reminders(chat_id, user_id, text, kind, interval_seconds, created_at) VALUES (?,?,?, 'interval', ?, ?)", (message.chat.id, message.from_user.id, info["text"], secs, datetime.now().isoformat()))
            rid = c.lastrowid; conn.commit(); conn.close()
            scheduler.add_job(send_reminder, IntervalTrigger(seconds=secs), args=[message.chat.id, info["text"], None, None], id=f"rem_{rid}")
            await message.reply_text("تم إضافة التذكير ✅")
            return

    # 2. معالجة وقت تذكير الوسائط
    if key in PENDING_MEDIA_REMINDER and "run_at" not in PENDING_MEDIA_REMINDER[key]:
        dt = parse_datetime_ar(text)
        if dt:
            PENDING_MEDIA_REMINDER[key]["run_at"] = dt.isoformat()
            await message.reply_text("هل تريد اضافة فيديو او صوره؟ (نعم / لا)")
            return

    # 3. معالجة نعم/لا للوسائط
    if key in PENDING_MEDIA_REMINDER and "run_at" in PENDING_MEDIA_REMINDER[key] and not PENDING_MEDIA_REMINDER[key].get("await_media"):
        if text == "نعم":
            PENDING_MEDIA_REMINDER[key]["await_media"] = True
            await message.reply_text("ارسل الوسائط الآن.")
            return
        elif text == "لا":
            info = PENDING_MEDIA_REMINDER.pop(key)
            conn = db(); c = conn.cursor()
            c.execute("INSERT INTO reminders(chat_id, user_id, text, kind, run_at, created_at) VALUES (?,?,?, 'datetime', ?, ?)", (message.chat.id, message.from_user.id, info["text"], info["run_at"], datetime.now().isoformat()))
            rid = c.lastrowid; conn.commit(); conn.close()
            scheduler.add_job(send_reminder, DateTrigger(run_date=datetime.fromisoformat(info["run_at"])), args=[message.chat.id, info["text"], None, None], id=f"rem_{rid}")
            await message.reply_text("تم إضافة التذكير ✅")
            return

    # 4. استقبال ملف تذكير الوسائط
    if key in PENDING_MEDIA_REMINDER and PENDING_MEDIA_REMINDER[key].get("await_media"):
        m_type = "photo" if message.photo else "video" if message.video else None
        if m_type:
            f_id = message.photo.file_id if message.photo else message.video.file_id
            info = PENDING_MEDIA_REMINDER.pop(key)
            conn = db(); c = conn.cursor()
            c.execute("INSERT INTO reminders(chat_id, user_id, text, media_type, media_file_id, kind, run_at, created_at) VALUES (?,?,?,?,?, 'datetime', ?, ?)", (message.chat.id, message.from_user.id, info["text"], m_type, f_id, info["run_at"], datetime.now().isoformat()))
            rid = c.lastrowid; conn.commit(); conn.close()
            scheduler.add_job(send_reminder, DateTrigger(run_date=datetime.fromisoformat(info["run_at"])), args=[message.chat.id, info["text"], m_type, f_id], id=f"rem_{rid}")
            await message.reply_text("تم الإضافة مع الوسائط ✅")
            return

    # 5. حفظ Media Trigger
    if key in PENDING_MEDIA_TRIGGER:
        f_id = message.photo.file_id if message.photo else message.video.file_id if message.video else None
        if f_id:
            info = PENDING_MEDIA_TRIGGER.pop(key)
            conn = db(); c = conn.cursor()
            c.execute("INSERT INTO media_triggers(chat_id, trigger, media_type, file_id) VALUES (?,?,?,?)", (message.chat.id, info["trigger"], info["type"], f_id))
            conn.commit(); conn.close()
            await message.reply_text("تم الحفظ ✅")
            return

    # 6. حفظ رد مخصص
    if key in PENDING_CUSTOM_REPLY:
        info = PENDING_CUSTOM_REPLY.pop(key)
        conn = db(); c = conn.cursor()
        c.execute("INSERT INTO custom_replies(chat_id, trigger, reply) VALUES (?,?,?)", (message.chat.id, info["trigger"], text))
        conn.commit(); conn.close()
        await message.reply_text("تم الحفظ ✅")
        return

    # 7. إضافة عنصر تعافي
    if key in PENDING_RECOVERY:
        m_type = "text"; f_id = None; url = None
        if message.photo: m_type = "photo"; f_id = message.photo.file_id
        elif message.video: m_type = "video"; f_id = message.video.file_id
        elif message.voice: m_type = "voice"; f_id = message.voice.file_id
        elif message.entities: m_type = "link"; url = text
        conn = db(); c = conn.cursor()
        c.execute("SELECT COALESCE(MAX(index_pos), 0) FROM recovery_items WHERE chat_id = ?", (message.chat.id,))
        idx = c.fetchone()[0] + 1
        c.execute("INSERT INTO recovery_items(chat_id, user_id, index_pos, item_type, text, file_id, url) VALUES (?,?,?,?,?,?,?)", (message.chat.id, message.from_user.id, idx, m_type, text, f_id, url))
        conn.commit(); conn.close()
        await message.reply_text(f"تم إضافة عنصر {idx} ✅")
        return

    # 8. تنفيذ الردود والـ Triggers
    if text:
        conn = db(); c = conn.cursor()
        c.execute("SELECT media_type, file_id FROM media_triggers WHERE chat_id = ? AND trigger = ?", (message.chat.id, text))
        m = c.fetchone()
        if m:
            if m[0] == "photo": await app.send_photo(message.chat.id, m[1])
            else: await app.send_video(message.chat.id, m[1])
            conn.close(); return
        c.execute("SELECT reply FROM custom_replies WHERE chat_id = ? AND trigger = ?", (message.chat.id, text))
        r = c.fetchone()
        if r: await message.reply_text(r[0])
        conn.close()


# ---------------------- التشغيل الرئيسي ---------------------- #

if __name__ == "__main__":
    init_db()
    scheduler.start()
    schedule_existing_reminders()
    print("Bot is LIVE!")
    app.run()

