
# -*- coding: utf-8 -*-

"""
بوت تليجيرام لإدارة المجموعات مع ميزات تفاعلية متقدمة.

الميزات:
- ترحيب بالأعضاء الجدد.
- منشن جماعي (all).
- ردود نصية وميديا مخصصة.
- تعديل الردود.
- حذف ذكي للرسائل.
- أدوات إشراف (كتم، إنذار).
- ملف شخصي وإحصائيات.
"""

import asyncio
import datetime
import re
from functools import wraps
from telethon import TelegramClient, events, types

# --- 1. الإعدادات والمتغيرات الأساسية ---
API_ID = 34257542
API_HASH = '614a1b5c5b712ac6de5530d5c571c42a'
BOT_TOKEN = '7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw'
OWNER_ID = 1486879970

# حاويات لتخزين البيانات في الذاكرة
# (في المشاريع الكبيرة، يفضل استخدام قاعدة بيانات مثل SQLite)
custom_responses = {}
custom_media = {}
warns = {}
stats = {}

# --- 2. تهيئة البوت والمصادقة ---
client = TelegramClient('bot_session', API_ID, API_HASH)

# --- 3. الدوال المساعدة والمزخرفات (Decorators) ---

def admin_only(func):
    """مزخرف (Decorator) للتحقق من أن المستخدم هو المالك أو مشرف."""
    @wraps(func)
    async def wrapped(event, *args, **kwargs):
        if event.sender_id == OWNER_ID:
            return await func(event, *args, **kwargs)
        try:
            permissions = await client.get_permissions(event.chat_id, event.sender_id)
            if permissions.is_admin:
                return await func(event, *args, **kwargs)
        except Exception:
            pass # تجاهل الأخطاء إذا لم يتمكن من جلب الصلاحيات
        return await event.reply("عذراً، هذا الأمر خاص بالمشرفين والمالك فقط 🚫")
    return wrapped

# --- 4. أوامر وميزات البوت ---

@client.on(events.ChatAction)
async def welcome_handler(event):
    """يرحب بالأعضاء الجدد عند انضمامهم للمجموعة."""
    if event.user_joined:
        user = await event.get_user()
        welcome_msg = (
            f"اهلاً بك في فجـر جـديد [\u200b](tg://user?id={user.id}) 🙋🏻‍♂️\n\n"
            "خطوة صغيرة اليوم… تصنع فرق كبير غدًا 🌅\n\n"
            "• ممنوع السلبية أو إحباط الآخرين ❌\n"
            "• لا يُسمح بأي محتوى غير لائق 🚫\n"
            "• الاحترام أسلوبنا الدائم 🤝\n"
            "• شارك بما يفيد ويحفّز غيرك 📌\n"
            "• التزامك اليوم هو نجاحك غداً 🌇"
        )
        await event.reply(welcome_msg)

@client.on(events.NewMessage(pattern=r'(?i)^all(?:\s+(.*))?'))
@admin_only
async def mention_all_handler(event):
    """يقوم بعمل منشن لجميع أعضاء المجموعة."""
    extra_text = event.pattern_match.group(1) or ""
    mentions = []
    async for user in client.iter_participants(event.chat_id):
        if not user.bot and user.first_name:
            mentions.append(f"[{user.first_name}](tg://user?id={user.id})")

    if not mentions:
        return await event.reply("لا يوجد أعضاء يمكن عمل منشن لهم. ❌")

    for i in range(0, len(mentions), 5):
        chunk = mentions[i:i+5]
        msg = f"{extra_text}\n" + " ".join(chunk)
        try:
            await client.send_message(event.chat_id, msg)
            await asyncio.sleep(1.5)  # لتقليل احتمالية الحظر من تيليجرام
        except Exception:
            await asyncio.sleep(3) # انتظار أطول في حال حدوث خطأ

@client.on(events.NewMessage(pattern=r'(?s)^رد\s*\((.*?)\)\s*\((.*)\)'))
@admin_only
async def add_text_reply_handler(event):
    """يضيف رد نصي مخصص لكلمة معينة."""
    word = event.pattern_match.group(1).strip().lower()
    reply = event.pattern_match.group(2).strip()
    custom_responses[word] = reply
    if word in custom_media: del custom_media[word] # حذف الرد الميديا إذا كان موجوداً
    await event.reply(f"تمت إضافة الرد النصي للكلمة: **{word}** ✅")

@client.on(events.NewMessage(pattern=r'^(صوره|فيديو)\s+(.*)'))
@admin_only
async def add_media_reply_handler(event):
    """يضيف رد ميديا (صورة/فيديو) مخصص لكلمة معينة."""
    media_type = event.pattern_match.group(1)
    trigger_text = event.pattern_match.group(2).strip().lower()

    async with client.conversation(event.chat_id, timeout=60) as conv:
        await conv.send_message(f"حسناً، أرسل الآن الـ **{media_type}** للكلمة `{trigger_text}`")
        try:
            response = await conv.get_response()
        except asyncio.TimeoutError:
            return await conv.send_message("انتهى الوقت، حاول مرة أخرى. ⏳")

        if not response.media:
            return await conv.send_message("يجب إرسال ملف ميديا (صورة أو فيديو). ❌")

        custom_media[trigger_text] = response.media
        if trigger_text in custom_responses: del custom_responses[trigger_text]
        await response.reply(f"تمت إضافة الـ **{media_type}** للكلمة: **{trigger_text}** ✅")

@client.on(events.NewMessage(pattern=r'^تعديل\s*\((.*)\)'))
@admin_only
async def edit_reply_handler(event):
    """يعدل رد موجود مسبقاً."""
    word = event.pattern_match.group(1).strip().lower()
    if word not in custom_responses and word not in custom_media:
        return await event.reply(f"الكلمة **{word}** غير موجودة أصلاً لتعديلها. ❌")

    async with client.conversation(event.chat_id, timeout=60) as conv:
        await conv.send_message(f"حسناً، أرسل الرد الجديد للكلمة **{word}** (نص أو ميديا):")
        try:
            response = await conv.get_response()
        except asyncio.TimeoutError:
            return await conv.send_message("انتهى الوقت، حاول مرة أخرى. ⏳")

        if response.media:
            custom_media[word] = response.media
            if word in custom_responses: del custom_responses[word]
        else:
            custom_responses[word] = response.text
            if word in custom_media: del custom_media[word]
        await response.reply("تمت إضافة التعديل بنجاح. 👍🏼")

@client.on(events.NewMessage(pattern=r'^[اأإآ]$'))
async def profile_stats_handler(event):
    """يعرض الملف الشخصي والإحصائيات للمستخدم."""
    user = await event.get_sender()
    user_id = user.id
    
    # زيادة عدد الرسائل
    stats[user_id] = stats.get(user_id, 0) + 1
    msg_count = stats[user_id]

    # حساب الترتيب
    sorted_users = sorted(stats.items(), key=lambda item: item[1], reverse=True)
    rank = next((i + 1 for i, (uid, _) in enumerate(sorted_users) if uid == user_id), 1)

    # جلب تاريخ الانضمام
    try:
        user_entity = await client.get_entity(user_id)
        join_date = user_entity.date.strftime("%Y-%m-%d")
    except Exception:
        join_date = "غير متوفر"

    caption = (
        f"✨ **ملفك الشخصي في فجـر جـديد** ✨\n\n"
        f"**إحصائياتك:**\n"
        f"  ✉️ عدد رسائلك: `{msg_count}`\n"
        f"  🏆 ترتيبك في المتفاعلين: `{rank}`\n"
        f"  📅 تاريخ انضمامك: `{join_date}`\n\n"
        f"استمر في التفاعل والمشاركة لتصنع فرقاً وتزيد من ترتيبك! 🚀"
    )

    try:
        photo = await client.download_profile_photo(user_id, file=bytes)
        await client.send_file(event.chat_id, photo, caption=caption, reply_to=event.id)
    except Exception:
        await event.reply(caption)

# --- 5. المعالج الرئيسي للرسائل (أدوات الإشراف والردود) ---

@client.on(events.NewMessage)
async def main_handler(event):
    """المعالج الرئيسي للرسائل، يدير أوامر الإشراف والردود المخصصة."""
    if not event.text:
        return

    # --- أوامر الإشراف (تتطلب الرد على رسالة) ---
    if event.is_reply:
        text = event.text.strip()
        is_admin_user = await is_admin_check(event)
        
        if text == "حذف" and is_admin_user:
            reply_msg = await event.get_reply_message()
            me = await client.get_me()
            if reply_msg and reply_msg.sender_id == me.id:
                to_delete = [event.id, reply_msg.id]
                if reply_msg.is_reply:
                    to_delete.append(reply_msg.reply_to_msg_id)
                await client.delete_messages(event.chat_id, to_delete)
                return # تم التعامل مع الأمر، لا تكمل

        if text in ("كتم", "الغاء كتم", "انذار") and is_admin_user:
            reply_msg = await event.get_reply_message()
            user_id = reply_msg.sender_id
            if text == "كتم":
                await client.edit_permissions(event.chat_id, user_id, send_messages=False)
                await event.reply("تم كتم العضو لمدة 24 ساعة. 🔇")
            elif text == "الغاء كتم":
                await client.edit_permissions(event.chat_id, user_id, send_messages=True)
                await event.reply("تم إلغاء كتم العضو. ✅")
            elif text == "انذار":
                count = warns.get(user_id, 0) + 1
                warns[user_id] = count
                if count >= 3:
                    await client.edit_permissions(event.chat_id, user_id, until_date=datetime.timedelta(hours=6), send_messages=False)
                    await event.reply(f"الإنذار 3/3.. تم كتم العضو 6 ساعات تلقائياً. ⚠️")
                    warns[user_id] = 0
                else:
                    await event.reply(f"تم إعطاء إنذار للعضو ({count}/3). ⚠️")
            return # تم التعامل مع الأمر

    # --- الردود المخصصة وزيادة الإحصائيات ---
    # تجاهل إذا كانت الرسالة هي أحد الأوامر المعروفة
    if not event.text.startswith(('رد', 'تعديل', 'صوره', 'فيديو', 'all')) and not re.match(r'^[اأإآ]$', event.text):
        input_text = event.text.strip().lower()
        
        # زيادة الإحصائيات فقط للرسائل العادية
        stats[event.sender_id] = stats.get(event.sender_id, 0) + 1
        
        if input_text in custom_responses:
            await event.reply(custom_responses[input_text])
        elif input_text in custom_media:
            await client.send_file(event.chat_id, custom_media[input_text], reply_to=event.id)

async def is_admin_check(event):
    """دالة مساعدة للتحقق من صلاحيات المشرف دون إرسال رد."""
    if event.sender_id == OWNER_ID: return True
    try:
        p = await client.get_permissions(event.chat_id, event.sender_id)
        return p.is_admin
    except: return False

# --- 6. تشغيل البوت ---

async def main():
    """الدالة الرئيسية لتشغيل البوت."""
    await client.start(bot_token=BOT_TOKEN)
    print("البوت يعمل الآن بنجاح...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
