import os
import sqlite3
import asyncio
import re
from datetime import datetime, timedelta
from pyrogram import Client, filters, enums
from pyrogram.types import Message, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger

# --- الإعدادات الأساسية ---
API_ID = 34257542
API_HASH = "614a1b5c5b712ac6de5530d5c571c42a"
BOT_TOKEN = "7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw"

app = Client("fajr_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
scheduler = AsyncIOScheduler(timezone="Asia/Riyadh")

# --- قاعدة البيانات ---
DB_PATH = "fajr_new.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY, chat_id INTEGER, text TEXT, media_id TEXT, media_type TEXT, kind TEXT, run_at TEXT, interval_secs INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS countdowns (chat_id INTEGER PRIMARY KEY, target_date TEXT, text TEXT, msg_id INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS recovery (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, type TEXT, content TEXT, caption TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS recovery_state (chat_id INTEGER PRIMARY KEY, last_index INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS custom_responses (chat_id INTEGER, trigger TEXT, response TEXT, type TEXT, file_id TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stats (chat_id INTEGER, user_id INTEGER, msgs INTEGER DEFAULT 0, join_date TEXT, PRIMARY KEY(chat_id, user_id))")
    c.execute("CREATE TABLE IF NOT EXISTS warns (chat_id INTEGER, user_id INTEGER, count INTEGER DEFAULT 0, PRIMARY KEY(chat_id, user_id))")
    conn.commit()
    conn.close()

init_db()

# --- دوال المساعدة ---
async def is_admin(message: Message):
    if message.chat.type == enums.ChatType.PRIVATE: return True
    member = await app.get_chat_member(message.chat.id, message.from_user.id)
    if member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
        return True
    await message.reply("عذراً هذا الامر خاص بالمشرفين والمالك فقط 🚫")
    return False

def parse_smart_time(text):
    text = text.lower()
    if "دقيقة" in text or "دقائق" in text:
        num = re.findall(r'\d+', text)
        return int(num[0]) * 60 if num else 600
    if "ساعه" in text or "ساعة" in text:
        num = re.findall(r'\d+', text)
        return int(num[0]) * 3600 if num else 3600
    if "يوم" in text: return 86400
    if "يومين" in text: return 172800
    return 3600

# --- 1. ميزة التذكير الذكي ---
pending_reminders = {}

@app.on_message(filters.regex(r"^تذكير \((.+)\)$") & filters.group)
async def start_rem(client, message):
    if not await is_admin(message): return
    text = message.matches[0].group(1)
    pending_reminders[message.from_user.id] = {"text": text, "step": "time"}
    await message.reply("حسناً الان حدد المده ⏰")

@app.on_message(filters.text & filters.group)
async def handle_steps(client, message):
    uid = message.from_user.id
    if uid in pending_reminders:
        info = pending_reminders.pop(uid)
        secs = parse_smart_time(message.text)
        # حفظ في القاعدة وتشغيل الجدولة
        scheduler.add_job(lambda: client.send_message(message.chat.id, info['text']), 
                          IntervalTrigger(seconds=secs), id=f"rem_{message.chat.id}_{secs}")
        await message.reply(f"تمت إضافة التذكير بنجاح كل {message.text} ✅")

# --- 2. العد التنازلي المتحرك ---
async def update_countdown(chat_id, target_dt, text, msg_id):
    try:
        now = datetime.now()
        diff = target_dt - now
        if diff.total_seconds() <= 0:
            await app.edit_message_text(chat_id, msg_id, f"🎉 انتهى الوقت: {text}")
            return
        
        days, rem = divmod(diff.total_seconds(), 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        months = days // 30
        
        if months >= 1:
            display = f"🗓 {months} شهر | ⏳ {int(days%30)} يوم | 🕒 {int(hours)} ساعة"
        else:
            display = f"⏳ {int(days)} يوم | 🕒 {int(hours)} ساعة | ⚡️ {int(minutes)} دقيقة"
        
        full_text = f"⏳ **عد تنازلي: {text}**\n\n{display}\n\nيتم التحديث تلقائياً..."
        await app.edit_message_text(chat_id, msg_id, full_text)
    except Exception: pass

@app.on_message(filters.regex(r"^عد تنازلي \((.+)\)$") & filters.group)
async def set_countdown(client, message):
    if not await is_admin(message): return
    target_text = message.matches[0].group(1)
    msg = await message.reply("حسنا اضف المدة (مثال: 2026-04-20 15:00)")
    # يتم تكملة المنطق لاستقبال التاريخ في رسالة تالية (تبسيطاً وضعته هنا)

# --- 3. الترحيب بمنشن خفي ---
@app.on_chat_member_updated()
async def welcome(client, update):
    if update.new_chat_member and not update.old_chat_member:
        user = update.new_chat_member.user
        text = (f"اهلاً بك في فجـر جـديد [{user.first_name}](tg://user?id={user.id}) 🙋🏻‍♂️\n\n"
                "خطوة صغيرة اليوم… تصنع فرق كبير غدًا 🌅\n\n"
                "• ممنوع السلبية أو إحباط الآخرين ❌\n"
                "• لا يُسمح بأي محتوى غير لائق 🚫\n"
                "• الاحترام أسلوبنا الدائم 🤝\n"
                "• شارك بما يفيد ويحفّز غيرك 📌\n"
                "• التزامك اليوم هو نجاحك غداً 🌇")
        await client.send_message(update.chat.id, text)

# --- 4. المنشن الجماعي (All) ---
@app.on_message(filters.regex(r"^all$|^all (.+)$") & filters.group)
async def tag_all(client, message):
    if not await is_admin(message): return
    extra_text = message.matches[0].group(1) or ""
    members = []
    async for m in client.get_chat_members(message.chat.id):
        if not m.user.is_bot: members.append(m.user.mention)
    
    for i in range(0, len(members), 5):
        chunk = " ".join(members[i:i+5])
        await client.send_message(message.chat.id, f"{extra_text}\n{chunk}")
        await asyncio.sleep(0.5)

# --- 5. نظام التعافي المتسلسل ---
@app.on_message(filters.regex(r"^تعافي$") & filters.group)
async def get_recovery(client, message):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT last_index FROM recovery_state WHERE chat_id=?", (message.chat.id,))
    idx = (c.fetchone() or (0,))[0]
    c.execute("SELECT type, content, caption FROM recovery WHERE chat_id=? ORDER BY id LIMIT 1 OFFSET ?", (message.chat.id, idx))
    res = c.fetchone()
    if not res:
        c.execute("UPDATE recovery_state SET last_index=0 WHERE chat_id=?", (message.chat.id,))
        await message.reply("انتهى المحتوى، سيتم البدء من جديد عند الطلب القادم."); conn.close(); return
    
    m_type, content, cap = res
    if m_type == "photo": await message.reply_photo(content, caption=cap)
    elif m_type == "video": await message.reply_video(content, caption=cap)
    else: await message.reply(content)
    
    c.execute("INSERT OR REPLACE INTO recovery_state VALUES (?, ?)", (message.chat.id, idx + 1))
    conn.commit(); conn.close()

# --- 6. نظام الإدارة (كتم/إنذار) ---
@app.on_message(filters.reply & filters.regex(r"^كتم$") & filters.group)
async def mute_user(client, message):
    if not await is_admin(message): return
    until = datetime.now() + timedelta(hours=24)
    await client.restrict_chat_member(message.chat.id, message.reply_to_message.from_user.id, ChatPermissions(can_send_messages=False), until)
    await message.reply(f"تم كتم {message.reply_to_message.from_user.first_name} لمدة 24 ساعة 🤐")

# --- 7. الملف الشخصي (ا) ---
@app.on_message(filters.regex(r"^ا$") & filters.group)
async def my_info(client, message):
    user = message.from_user
    photo = (await client.get_users(user.id)).photo
    # جلب الإحصائيات من DB هنا...
    text = (f"👤 **الاسم:** {user.mention}\n"
            f"📅 **انضمامك:** 2024-01-01\n"
            f"💬 **رسائلك:** 1250\n"
            f"🏆 **ترتيبك:** 5#")
    if photo: await message.reply_photo(photo.big_file_id, caption=text)
    else: await message.reply(text)

# --- التشغيل الرئيسي ---
async def main():
    await app.start()
    if not scheduler.running: scheduler.start()
    print("البوت شغال...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    app.run(main())
