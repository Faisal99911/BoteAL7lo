
from pyrogram import Client, filters
from pyrogram.types import ChatPermissions
from pyrogram.enums import ChatMemberStatus
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
import re
import dateparser
from functools import wraps

# --- Configuration ---
API_ID = 34257542
API_HASH = "614a1b5c5b712ac6de5530d5c571c42a"
BOT_TOKEN = "7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw"
OWNER_ID = 1486879970

# --- Data Structures ---
scheduler = AsyncIOScheduler()
pending_reminders = {}
recovery_content = {}
recovery_pointers = {}
image_responses = {}
video_responses = {}
text_responses = {}
user_warnings = {}
user_stats = {}
pending_schedules = {} # {chat_id: {user_id: {"type": "video/photo/text", "data": file_id/text, "caption": caption}}}

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- Decorators ---
def admin_or_owner_only(func):
    @wraps(func)
    async def wrapper(client, message):
        if message.from_user.id == OWNER_ID:
            return await func(client, message)
        if message.chat.type in ["group", "supergroup"]:
            member = await client.get_chat_member(message.chat.id, message.from_user.id)
            if member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                return await func(client, message)
        await message.reply_text("عذراً، هذا الأمر خاص بالمشرفين والمالك فقط 🚫")
    return wrapper

# --- Helper Functions ---
def parse_duration(duration_str):
    duration_str = duration_str.lower()
    if "دقائق" in duration_str or "دقيقة" in duration_str:
        match = re.search(r'\d+', duration_str)
        if match: return int(match.group()) * 60
    elif "ساعة" in duration_str or "ساعات" in duration_str:
        match = re.search(r'\d+', duration_str)
        if match: return int(match.group()) * 3600
        if "كل ساعه" in duration_str: return 3600
    elif "يوم" in duration_str or "يومين" in duration_str:
        match = re.search(r'\d+', duration_str)
        if match: return int(match.group()) * 86400
        if "كل يوم" in duration_str: return 86400
    return None

async def send_reminder(client, chat_id, text):
    await client.send_message(chat_id, f"تذكير: {text}")

async def send_scheduled_msg(client, chat_id, item):
    if item["type"] == "text": await client.send_message(chat_id, item["data"])
    elif item["type"] == "photo": await client.send_photo(chat_id, item["data"], caption=item.get("caption"))
    elif item["type"] == "video": await client.send_video(chat_id, item["data"], caption=item.get("caption"))

async def update_countdown_message(client, chat_id, message_id, target_date, job_id):
    now = datetime.now()
    time_left = target_date - now
    if time_left.total_seconds() <= 0:
        await client.edit_message_text(chat_id, message_id, "انتهى العد التنازلي!")
        scheduler.remove_job(job_id)
        return
    total_seconds = int(time_left.total_seconds())
    months = total_seconds // (30 * 24 * 3600)
    total_seconds %= (30 * 24 * 3600)
    weeks = total_seconds // (7 * 24 * 3600)
    total_seconds %= (7 * 24 * 3600)
    days = total_seconds // (24 * 3600)
    total_seconds %= (24 * 3600)
    hours = total_seconds // 3600
    total_seconds %= 3600
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    parts = []
    if months > 0: parts.append(f"{months} شهر")
    if weeks > 0: parts.append(f"{weeks} أسبوع")
    if days > 0: parts.append(f"{days} يوم")
    if hours > 0: parts.append(f"{hours} ساعة")
    if minutes > 0: parts.append(f"{minutes} دقيقة")
    if seconds > 0 and not parts: parts.append(f"{seconds} ثانية")
    text = f"متبقي: {', '.join(parts)}"
    try: await client.edit_message_text(chat_id, message_id, text)
    except: scheduler.remove_job(job_id)

# --- Command Handlers ---

@app.on_message(filters.regex(r"^تذكير (.+)$") & filters.group)
@admin_or_owner_only
async def set_reminder_direct(client, message):
    reminder_text = message.matches[0].group(1)
    pending_reminders[message.chat.id] = {"text": reminder_text}
    await message.reply_text(f"حسناً الآن حدد المده ⏰", reply_to_message_id=message.id)

@app.on_message(filters.regex(r"^عد تنازلي (.+)$") & filters.group)
@admin_or_owner_only
async def countdown_direct(client, message):
    target_str = message.matches[0].group(1)
    try:
        parts = target_str.split()
        day = int(parts[1])
        month_name = parts[2]
        month_map = {"يناير":1,"فبراير":2,"مارس":3,"ابريل":4,"أبريل":4,"مايو":5,"يونيو":6,"يوليو":7,"اغسطس":8,"سبتمبر":9,"اكتوبر":10,"نوفمبر":11,"ديسمبر":12}
        month = month_map.get(month_name)
        if not month: return await message.reply_text("خطأ في اسم الشهر")
        target_date = datetime(datetime.now().year, month, day)
        if target_date < datetime.now(): target_date = datetime(datetime.now().year + 1, month, day)
        job_id = f"cd_{message.chat.id}_{message.id}"
        scheduler.add_job(update_countdown_message, 'interval', seconds=1, id=job_id, args=[client, message.chat.id, 0, target_date, job_id])
        msg = await message.reply_text("جاري الإعداد...", reply_to_message_id=message.id)
        scheduler.modify_job(job_id, args=[client, message.chat.id, msg.id, target_date, job_id])
    except: await message.reply_text("الصيغة: عد تنازلي إلى 30 ابريل")

@app.on_message(filters.regex(r"^تعافي اضف$") & filters.group)
@admin_or_owner_only
async def add_recovery_direct(client, message):
    recovery_content[message.chat.id] = recovery_content.get(message.chat.id, [])
    recovery_pointers[message.chat.id] = recovery_pointers.get(message.chat.id, 0)
    await message.reply_text("اضف المحتوى", reply_to_message_id=message.id)

@app.on_message(filters.regex(r"^تعافي$") & filters.group)
async def send_recovery_direct(client, message):
    chat_id = message.chat.id
    if not recovery_content.get(chat_id): return await message.reply_text("القائمة فارغة")
    idx = recovery_pointers[chat_id]
    item = recovery_content[chat_id][idx]
    if item["type"] == "text": await client.send_message(chat_id, item["data"], reply_to_message_id=message.id)
    elif item["type"] == "photo": await client.send_photo(chat_id, item["data"], caption=item.get("caption"), reply_to_message_id=message.id)
    elif item["type"] == "video": await client.send_video(chat_id, item["data"], caption=item.get("caption"), reply_to_message_id=message.id)
    elif item["type"] == "audio": await client.send_audio(chat_id, item["data"], caption=item.get("caption"), reply_to_message_id=message.id)
    elif item["type"] == "voice": await client.send_voice(chat_id, item["data"], caption=item.get("caption"), reply_to_message_id=message.id)
    recovery_pointers[chat_id] = (idx + 1) % len(recovery_content[chat_id])

@app.on_message(filters.regex(r"^صوره (.+)$") & filters.group)
@admin_or_owner_only
async def add_img_direct(client, message):
    image_responses[message.chat.id] = {"keyword": message.matches[0].group(1)}
    await message.reply_text("حسنا ارسل الصورة", reply_to_message_id=message.id)

@app.on_message(filters.regex(r"^فيديو (.+)$") & filters.group)
@admin_or_owner_only
async def add_vid_direct(client, message):
    video_responses[message.chat.id] = {"keyword": message.matches[0].group(1)}
    await message.reply_text("حسنا ارسل الفيديو", reply_to_message_id=message.id)

@app.on_message(filters.regex(r"^اضف نص (.+)$") & filters.group)
@admin_or_owner_only
async def add_txt_direct(client, message):
    text_responses[message.chat.id] = {"keyword": message.matches[0].group(1)}
    await message.reply_text("اضف النص المطلوب", reply_to_message_id=message.id)

@app.on_message(filters.regex(r"^حذف نص (.+)$") & filters.group)
@admin_or_owner_only
async def del_txt_direct(client, message):
    kw = message.matches[0].group(1)
    if text_responses.get(message.chat.id, {}).get("keyword") == kw:
        del text_responses[message.chat.id]
        await message.reply_text("تم حذف النص")
    else: await message.reply_text("غير موجود")

@app.on_message(filters.regex(r"^all( .*|)$") & filters.group)
@admin_or_owner_only
async def all_direct(client, message):
    extra = message.matches[0].group(1).strip()
    members = [m.user async for m in client.get_chat_members(message.chat.id) if not m.user.is_bot]
    mentions = []
    for i, m in enumerate(members):
        mentions.append(f"[{m.first_name}](tg://user?id={m.id})")
        if (i + 1) % 5 == 0 or (i + 1) == len(members):
            await client.send_message(message.chat.id, f"{extra} {' '.join(mentions)}")
            mentions = []

@app.on_message(filters.regex(r"^كتم$") & filters.group & filters.reply)
@admin_or_owner_only
async def mute_direct(client, message):
    uid = message.reply_to_message.from_user.id
    await client.restrict_chat_member(message.chat.id, uid, ChatPermissions(can_send_messages=False), datetime.now() + timedelta(hours=24))
    await message.reply_text("تم الكتم 24 ساعة")

@app.on_message(filters.regex(r"^الغاء كتم$") & filters.group & filters.reply)
@admin_or_owner_only
async def unmute_direct(client, message):
    uid = message.reply_to_message.from_user.id
    await client.restrict_chat_member(message.chat.id, uid, ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True, can_send_polls=True, can_invite_users=True))
    await message.reply_text("تم إلغاء الكتم")

@app.on_message(filters.regex(r"^انذار$") & filters.group & filters.reply)
@admin_or_owner_only
async def warn_direct(client, message):
    cid, uid = message.chat.id, message.reply_to_message.from_user.id
    user_warnings[cid] = user_warnings.get(cid, {})
    user_warnings[cid][uid] = user_warnings[cid].get(uid, 0) + 1
    count = user_warnings[cid][uid]
    if count >= 3:
        await client.restrict_chat_member(cid, uid, ChatPermissions(can_send_messages=False), datetime.now() + timedelta(hours=6))
        await message.reply_text(f"انذار 3/3 تم الكتم 6 ساعات")
        user_warnings[cid][uid] = 0
    else: await message.reply_text(f"انذار {count}/3")

@app.on_message(filters.regex(r"^ا$") & filters.group)
async def card_direct(client, message):
    cid, uid = message.chat.id, message.from_user.id
    m = (await client.get_chat_member(cid, uid)).user
    cnt = user_stats.get(cid, {}).get(uid, {}).get("count", 0)
    jd = user_stats.get(cid, {}).get(uid, {}).get("date")
    all_s = sorted(user_stats.get(cid, {}).items(), key=lambda x: x[1].get("count", 0), reverse=True)
    rank = next((i+1 for i, (u, s) in enumerate(all_s) if u == uid), 0)
    txt = f"**بطاقة المستخدم** 🪪\n\nالاسم: {m.first_name}\nالمعرف: `{m.id}`\nالرسائل: {cnt}\nالتاريخ: {jd.strftime('%Y-%m-%d') if jd else 'غير مسجل'}\nالترتيب: {rank}"
    if m.photo: await client.send_photo(cid, m.photo.big_file_id, caption=txt)
    else: await message.reply_text(txt)

# --- Smart Scheduling ---
@app.on_message(filters.regex(r"^جدولة (.+)$") & filters.group)
@admin_or_owner_only
async def schedule_direct(client, message):
    text = message.matches[0].group(1)
    pending_schedules[message.chat.id] = {message.from_user.id: {"type": "text", "data": text}}
    await message.reply_text("متى ارسلها", reply_to_message_id=message.id)

@app.on_message(filters.regex(r"^جدولة فيديو$") & filters.group)
@admin_or_owner_only
async def schedule_vid_direct(client, message):
    pending_schedules[message.chat.id] = {message.from_user.id: {"type": "video"}}
    await message.reply_text("ارسل الفيديو", reply_to_message_id=message.id)

@app.on_message(filters.regex(r"^جدولة صوره$") & filters.group)
@admin_or_owner_only
async def schedule_img_direct(client, message):
    pending_schedules[message.chat.id] = {message.from_user.id: {"type": "photo"}}
    await message.reply_text("ارسل الصورة", reply_to_message_id=message.id)

# --- Reply Handlers ---
@app.on_message(filters.reply & filters.group)
async def handle_replies(client, message):
    if not message.reply_to_message or message.reply_to_message.from_user.id != client.me.id: return
    txt = message.reply_to_message.text
    cid, uid = message.chat.id, message.from_user.id
    
    # Scheduling logic
    if "ارسل الفيديو" in txt and cid in pending_schedules and uid in pending_schedules[cid]:
        if message.video:
            pending_schedules[cid][uid].update({"data": message.video.file_id, "caption": message.caption})
            await message.reply_text("متى ارسلها")
    elif "ارسل الصورة" in txt and cid in pending_schedules and uid in pending_schedules[cid]:
        if message.photo:
            pending_schedules[cid][uid].update({"data": message.photo.file_id, "caption": message.caption})
            await message.reply_text("متى ارسلها")
    elif "متى ارسلها" in txt and cid in pending_schedules and uid in pending_schedules[cid]:
        time_str = message.text
        dt = dateparser.parse(time_str, settings={'PREFER_DATES_FROM': 'future', 'RELATIVE_BASE': datetime.now()})
        if dt:
            if dt < datetime.now(): dt += timedelta(days=1) # Handle cases like "4:30 مساء" if it already passed today
            item = pending_schedules[cid].pop(uid)
            scheduler.add_job(send_scheduled_msg, 'date', run_date=dt, args=[client, cid, item])
            await message.reply_text(f"تمت الجدولة في: {dt.strftime('%Y-%m-%d %I:%M %p')}")
        else: await message.reply_text("لم افهم الوقت، حاول مرة اخرى")

    # Other replies (reminders, recovery, etc.)
    elif "حدد المده" in txt and cid in pending_reminders:
        sec = parse_duration(message.text)
        if sec:
            info = pending_reminders.pop(cid)
            scheduler.add_job(send_reminder, 'interval', seconds=sec, args=[client, cid, info["text"]])
            await message.reply_text("تمت الإضافة")
    elif "اضف المحتوى" in txt:
        recovery_content[cid] = recovery_content.get(cid, [])
        if len(recovery_content[cid]) >= 50: return await message.reply_text("الحد 50")
        item = {"caption": message.caption}
        if message.photo: item.update({"type": "photo", "data": message.photo.file_id})
        elif message.video: item.update({"type": "video", "data": message.video.file_id})
        elif message.audio: item.update({"type": "audio", "data": message.audio.file_id})
        elif message.voice: item.update({"type": "voice", "data": message.voice.file_id})
        elif message.text: item.update({"type": "text", "data": message.text})
        recovery_content[cid].append(item)
        await message.reply_text("تمت الإضافة")
    elif "حسنا ارسل الصورة" in txt and cid in image_responses:
        image_responses[cid]["file_id"] = message.photo.file_id
        await message.reply_text("تمت اضافة الصورة")
    elif "حسنا ارسل الفيديو" in txt and cid in video_responses:
        video_responses[cid]["file_id"] = message.video.file_id
        await message.reply_text("تمت اضافة الفيديو")
    elif "اضف النص المطلوب" in txt and cid in text_responses:
        text_responses[cid]["text"] = message.text
        await message.reply_text("تمت اضافة النص")

# --- Global Handlers ---
@app.on_message(filters.text & filters.group)
async def global_text_handler(client, message):
    cid, text = message.chat.id, message.text.lower()
    # Stats
    user_stats[cid] = user_stats.get(cid, {})
    user_stats[cid][message.from_user.id] = user_stats[cid].get(message.from_user.id, {"count": 0, "date": datetime.now()})
    user_stats[cid][message.from_user.id]["count"] += 1
    # Media/Text Responses
    if cid in image_responses and image_responses[cid].get("keyword", "").lower() == text:
        await client.send_photo(cid, image_responses[cid]["file_id"], reply_to_message_id=message.id)
    elif cid in video_responses and video_responses[cid].get("keyword", "").lower() == text:
        await client.send_video(cid, video_responses[cid]["file_id"], reply_to_message_id=message.id)
    elif cid in text_responses and text_responses[cid].get("keyword", "").lower() == text:
        await client.send_message(cid, text_responses[cid]["text"], reply_to_message_id=message.id)

@app.on_message(filters.new_chat_members)
async def welcome(client, message):
    for m in message.new_chat_members:
        if m.id == client.me.id: continue
        welcome_text = f"أهلاً بك في فجـر جـديد 🙋🏻‍♂️\n\nخطوة صغيرة اليوم… تصنع فرق كبير غدًا 🌅\n\n• ممنوع السلبية أو إحباط الآخرين ❌\n• لا يُسمح بأي محتوى غير لائق 🚫\n• الاحترام أسلوبنا الدائم 🤝\n• شارك بما يفيد ويحفّز غيرك 📌\n• التزامك اليوم هو نجاحك غداً 🌇"
        user_stats[message.chat.id] = user_stats.get(message.chat.id, {})
        user_stats[message.chat.id][m.id] = {"count": 0, "date": datetime.now()}
        await message.reply_text(welcome_text)

print("Bot starting...")
scheduler.start()
app.run()
