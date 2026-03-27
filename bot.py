
# -*- coding: utf-8 -*-

"""
بوت تليجرام متقدم لإدارة المجموعات.

الميزات:
- ترحيب بالأعضاء الجدد.
- منشن جماعي (all) مع تحسينات.
- ردود نصية وميديا مخصصة (صور/فيديو) مع دعم الأقواس الحرة.
- تعديل الردود الموجودة.
- حذف ذكي للرسائل المتعلقة بالعمليات.
- أدوات إشراف متكاملة (كتم، إنذار).
- ملف شخصي وإحصائيات للمستخدمين.
- حفظ تلقائي للبيانات (الردود، الإنذارات، الإحصائيات) في ملفات JSON.
- معالجة ذكية للنصوص لتجاهل التشكيل والمسافات الزائدة.
- معالجة الأخطاء وتحسين استقرار البوت.
"""

import asyncio
import datetime
import json
import re
from functools import wraps
from telethon import TelegramClient, events, types
from telethon.errors import ChatAdminRequiredError, UserNotParticipantError, MessageDeleteForbiddenError

# --- 1. الإعدادات والثوابت الأساسية ---

# بيانات API الخاصة بتليجرام (يجب استبدالها ببياناتك الحقيقية)
API_ID = 34257542
API_HASH = '614a1b5c5b712ac6de5530d5c571c42a'
BOT_TOKEN = '7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw'

# معرف المالك (Owner ID) للحصول على صلاحيات كاملة
OWNER_ID = 1486879970  # استبدل هذا بمعرف حسابك في تيليجرام

# مسارات ملفات حفظ البيانات
RESPONSES_FILE = 'custom_responses.json'
MEDIA_FILE = 'custom_media.json'
WARNS_FILE = 'warns.json'
STATS_FILE = 'stats.json'

# --- 2. تهيئة البوت ---

client = TelegramClient('bot_session', API_ID, API_HASH)

# --- 3. حاويات البيانات (سيتم تحميلها من الملفات) ---

custom_responses = {}
custom_media = {}
warns = {}
stats = {}

# --- 4. دوال حفظ وتحميل البيانات (Persistence) ---

async def load_data():
    """تحميل البيانات من ملفات JSON."""
    global custom_responses, custom_media, warns, stats
    try:
        with open(RESPONSES_FILE, 'r', encoding='utf-8') as f:
            custom_responses = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        custom_responses = {}

    try:
        with open(MEDIA_FILE, 'r', encoding='utf-8') as f:
            # يتم تخزين الميديا كـ string (file_id) وليس كائن Media
            custom_media = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        custom_media = {}

    try:
        with open(WARNS_FILE, 'r', encoding='utf-8') as f:
            warns = {int(k): v for k, v in json.load(f).items()} # تحويل المفاتيح إلى int
    except (FileNotFoundError, json.JSONDecodeError):
        warns = {}

    try:
        with open(STATS_FILE, 'r', encoding='utf-8') as f:
            stats = {int(k): v for k, v in json.load(f).items()} # تحويل المفاتيح إلى int
    except (FileNotFoundError, json.JSONDecodeError):
        stats = {}
    print("تم تحميل البيانات بنجاح.")

async def save_data():
    """حفظ البيانات إلى ملفات JSON."""
    try:
        with open(RESPONSES_FILE, 'w', encoding='utf-8') as f:
            json.dump(custom_responses, f, ensure_ascii=False, indent=4)
        with open(MEDIA_FILE, 'w', encoding='utf-8') as f:
            json.dump(custom_media, f, ensure_ascii=False, indent=4)
        with open(WARNS_FILE, 'w', encoding='utf-8') as f:
            json.dump(warns, f, ensure_ascii=False, indent=4)
        with open(STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=4)
        print("تم حفظ البيانات بنجاح.")
    except Exception as e:
        print(f"خطأ أثناء حفظ البيانات: {e}")

# --- 5. دوال مساعدة عامة ---

def normalize_text(text: str) -> str:
    """تنظيف النص من المسافات الزائدة والتشكيل لتوحيد المقارنات."""
    if not isinstance(text, str): return ""
    text = re.sub(r'\s+', ' ', text).strip() # استبدال مسافات متعددة بمسافة واحدة وإزالة الأطراف
    text = re.sub(r'[ًٌٍَّْـّ]', '', text) # إزالة التشكيل العربي
    return text.lower()

async def is_admin_check(event) -> bool:
    """التحقق من صلاحيات المشرف أو المالك بدون إرسال رد."""
    if event.sender_id == OWNER_ID: return True
    try:
        # التأكد من أن event.chat_id ليس None قبل استخدامه
        if event.chat_id:
            permissions = await client.get_permissions(event.chat_id, event.sender_id)
            return permissions.is_admin
    except (ChatAdminRequiredError, UserNotParticipantError):
        # البوت ليس مشرفاً أو المستخدم ليس عضواً، لذا لا يمكن التحقق من الصلاحيات
        pass
    except Exception as e:
        print(f"خطأ أثناء التحقق من صلاحيات المشرف: {e}")
    return False

async def delete_messages_safely(chat_id, message_ids: list):
    """حذف الرسائل بأمان مع معالجة الأخطاء."""
    try:
        await client.delete_messages(chat_id, message_ids)
    except MessageDeleteForbiddenError:
        print(f"لا يمكن حذف الرسائل في الدردشة {chat_id}. قد لا يكون البوت مشرفاً.")
    except Exception as e:
        print(f"خطأ أثناء حذف الرسائل: {e}")

# --- 6. المزخرفات (Decorators) ---

def admin_only(func):
    """مزخرف (Decorator) للتحقق من أن المستخدم هو المالك أو مشرف قبل تنفيذ الأمر."""
    @wraps(func)
    async def wrapped(event, *args, **kwargs):
        if await is_admin_check(event):
            return await func(event, *args, **kwargs)
        return await event.reply("عذراً، هذا الأمر خاص بالمشرفين والمالك فقط 🚫")
    return wrapped

# --- 7. معالجات أحداث البوت (Event Handlers) ---

@client.on(events.ChatAction)
async def welcome_handler(event):
    """يرحب بالأعضاء الجدد عند انضمامهم للمجموعة."""
    if event.user_joined:
        user = await event.get_user()
        if user.bot: return # تجاهل البوتات
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
    """يقوم بعمل منشن لجميع أعضاء المجموعة (غير البوتات)."""
    extra_text = event.pattern_match.group(1) or ""
    mentions = []
    
    try:
        # استخدام iter_participants للحصول على جميع الأعضاء
        async for user in client.iter_participants(event.chat_id):
            if not user.bot and user.first_name:
                mentions.append(f"[{user.first_name}](tg://user?id={user.id})")
    except ChatAdminRequiredError:
        return await event.reply("لا أستطيع عمل منشن للجميع. يرجى التأكد من أنني مشرف في المجموعة. ⚠️")
    except Exception as e:
        print(f"خطأ في جلب المشاركين للمنشن: {e}")
        return await event.reply("حدث خطأ أثناء محاولة عمل منشن للجميع. ❌")

    if not mentions:
        return await event.reply("لا يوجد أعضاء يمكن عمل منشن لهم في هذه المجموعة. ❌")

    # تقسيم المنشن إلى مجموعات صغيرة لتجنب تجاوز حدود الرسالة
    for i in range(0, len(mentions), 5):
        chunk = mentions[i:i+5]
        msg = f"{extra_text}\n" + " ".join(chunk)
        try:
            await client.send_message(event.chat_id, msg, link_preview=False) # تعطيل معاينة الروابط
            await asyncio.sleep(1.5)  # انتظار لتقليل احتمالية الحظر من تيليجرام
        except Exception as e:
            print(f"خطأ أثناء إرسال رسالة المنشن: {e}")
            await asyncio.sleep(3) # انتظار أطول في حال حدوث خطأ
    await delete_messages_safely(event.chat_id, [event.id]) # حذف رسالة الأمر

@client.on(events.NewMessage(pattern=r'(?s)^رد\s*\((.*?)\)\s*\((.*)\)'))
@admin_only
async def add_text_reply_handler(event):
    """يضيف رد نصي مخصص لكلمة معينة، ويدعم الأقواس الحرة والأسطر المتعددة."""
    word_raw = event.pattern_match.group(1)
    reply_text = event.pattern_match.group(2)
    
    word = normalize_text(word_raw) # تنظيف الكلمة للمقارنة
    
    if not word or not reply_text:
        return await event.reply("صيغة الأمر غير صحيحة. مثال: `رد (الكلمة) (الرد)` ❌")

    custom_responses[word] = reply_text
    if word in custom_media: 
        del custom_media[word] # حذف الرد الميديا إذا كان موجوداً لنفس الكلمة
    await save_data() # حفظ البيانات بعد التعديل
    await event.reply(f"تمت إضافة الرد النصي للكلمة: **{word_raw.strip()}** ✅")
    await delete_messages_safely(event.chat_id, [event.id]) # حذف رسالة الأمر

@client.on(events.NewMessage(pattern=r'(?i)^(صوره|فيديو)\s*\((.*?)\)'))
@admin_only
async def add_media_reply_handler(event):
    """يضيف رد ميديا (صورة/فيديو) مخصص لكلمة معينة، ويدعم الأقواس الحرة."""
    media_type_cmd = event.pattern_match.group(1)
    trigger_text_raw = event.pattern_match.group(2)
    
    trigger_text = normalize_text(trigger_text_raw) # تنظيف الكلمة للمقارنة

    if not trigger_text:
        return await event.reply(f"صيغة الأمر غير صحيحة. مثال: `{media_type_cmd} (الكلمة)` ❌")

    async with client.conversation(event.chat_id, timeout=60) as conv:
        await conv.send_message(f"حسناً، أرسل الآن الـ **{media_type_cmd}** للكلمة `{trigger_text_raw.strip()}`")
        try:
            response = await conv.get_response()
        except asyncio.TimeoutError:
            return await conv.send_message("انتهى الوقت، حاول مرة أخرى. ⏳")

        if not response.media:
            return await conv.send_message("يجب إرسال ملف ميديا (صورة أو فيديو). ❌")

        # تخزين file_id للميديا بدلاً من كائن الميديا نفسه
        # هذا يضمن استمرارية البيانات بعد إعادة تشغيل البوت
        if isinstance(response.media, types.MessageMediaPhoto):
            custom_media[trigger_text] = {'type': 'photo', 'id': response.media.photo.id}
        elif isinstance(response.media, types.MessageMediaDocument) and response.media.document.mime_type.startswith('video'):
            custom_media[trigger_text] = {'type': 'video', 'id': response.media.document.id}
        else:
            return await conv.send_message("النوع المدعوم هو صورة أو فيديو فقط. ❌")

        if trigger_text in custom_responses: 
            del custom_responses[trigger_text] # حذف الرد النصي إذا كان موجوداً
        await save_data() # حفظ البيانات بعد التعديل
        await response.reply(f"تمت إضافة الـ **{media_type_cmd}** للكلمة: **{trigger_text_raw.strip()}** ✅")
    await delete_messages_safely(event.chat_id, [event.id]) # حذف رسالة الأمر

@client.on(events.NewMessage(pattern=r'(?i)^تعديل\s*\((.*?)\)'))
@admin_only
async def edit_reply_handler(event):
    """يعدل رد موجود مسبقاً (نص أو ميديا)."""
    word_raw = event.pattern_match.group(1)
    word = normalize_text(word_raw) # تنظيف الكلمة للمقارنة

    if not word:
        return await event.reply("صيغة الأمر غير صحيحة. مثال: `تعديل (الكلمة)` ❌")

    if word not in custom_responses and word not in custom_media:
        return await event.reply(f"الكلمة **{word_raw.strip()}** غير موجودة أصلاً لتعديلها. ❌")

    async with client.conversation(event.chat_id, timeout=60) as conv:
        await conv.send_message(f"حسناً، أرسل الرد الجديد للكلمة **{word_raw.strip()}** (نص أو صورة أو فيديو):")
        try:
            response = await conv.get_response()
        except asyncio.TimeoutError:
            return await conv.send_message("انتهى الوقت، حاول مرة أخرى. ⏳")

        if response.media:
            if isinstance(response.media, types.MessageMediaPhoto):
                custom_media[word] = {'type': 'photo', 'id': response.media.photo.id}
            elif isinstance(response.media, types.MessageMediaDocument) and response.media.document.mime_type.startswith('video'):
                custom_media[word] = {'type': 'video', 'id': response.media.document.id}
            else:
                return await conv.send_message("النوع المدعوم هو صورة أو فيديو فقط. ❌")
            if word in custom_responses: del custom_responses[word]
        else:
            custom_responses[word] = response.text
            if word in custom_media: del custom_media[word]
        
        await save_data() # حفظ البيانات بعد التعديل
        await response.reply("تمت إضافة التعديل بنجاح. 👍🏼")
    await delete_messages_safely(event.chat_id, [event.id]) # حذف رسالة الأمر

@client.on(events.NewMessage(pattern=r'^[اأإآ]$'))
async def profile_stats_handler(event):
    """يعرض الملف الشخصي والإحصائيات للمستخدم."""
    user = await event.get_sender()
    user_id = user.id
    
    # زيادة عدد الرسائل
    stats[user_id] = stats.get(user_id, 0) + 1
    msg_count = stats[user_id]
    await save_data() # حفظ الإحصائيات

    # حساب الترتيب
    sorted_users = sorted(stats.items(), key=lambda item: item[1], reverse=True)
    rank = next((i + 1 for i, (uid, _) in enumerate(sorted_users) if uid == user_id), 1)

    # جلب تاريخ الانضمام
    join_date = "غير متوفر"
    try:
        user_entity = await client.get_entity(user_id)
        if hasattr(user_entity, 'date'): # بعض الكائنات قد لا تحتوي على تاريخ
            join_date = user_entity.date.strftime("%Y-%m-%d")
    except Exception as e:
        print(f"خطأ في جلب تاريخ انضمام المستخدم {user_id}: {e}")

    caption = (
        f"✨ **ملفك الشخصي في فجـر جـديد** ✨\n\n"
        f"**إحصائياتك:**\n"
        f"  ✉️ عدد رسائلك: `{msg_count}`\n"
        f"  🏆 ترتيبك في المتفاعلين: `{rank}`\n"
        f"  📅 تاريخ انضمامك: `{join_date}`\n\n"
        f"استمر في التفاعل والمشاركة لتصنع فرقاً وتزيد من ترتيبك! 🚀"
    )

    try:
        # محاولة تحميل صورة البروفايل كـ bytes ثم إرسالها
        photo = await client.download_profile_photo(user_id, file=bytes)
        await client.send_file(event.chat_id, photo, caption=caption, reply_to=event.id)
    except Exception as e:
        print(f"خطأ في تحميل أو إرسال صورة البروفايل للمستخدم {user_id}: {e}")
        await event.reply(caption) # إذا فشل إرسال الصورة، أرسل النص فقط

@client.on(events.NewMessage)
async def main_message_handler(event):
    """المعالج الرئيسي لجميع الرسائل الواردة، يدير أوامر الإشراف والردود المخصصة."""
    if not event.text or event.sender_id == (await client.get_me()).id: 
        return # تجاهل الرسائل الفارغة أو رسائل البوت نفسه

    # --- 8.1. معالجة أوامر الإشراف (تتطلب الرد على رسالة) ---
    if event.is_reply:
        text = event.text.strip()
        is_admin_user = await is_admin_check(event)
        
        # أمر الحذف الذكي
        if text == "حذف" and is_admin_user:
            reply_msg = await event.get_reply_message()
            me = await client.get_me()
            if reply_msg and reply_msg.sender_id == me.id: # تأكد أن البوت هو من أرسل الرسالة التي يتم الرد عليها
                to_delete = [event.id, reply_msg.id] # رسالة الحذف ورسالة البوت
                if reply_msg.is_reply: # إذا كانت رسالة البوت رداً على رسالة أخرى
                    to_delete.append(reply_msg.reply_to_msg_id) # أضف الرسالة الأصلية للحذف
                await delete_messages_safely(event.chat_id, to_delete)
                return # تم التعامل مع الأمر، لا تكمل
            else:
                await event.reply("لا يمكنني حذف هذه الرسالة. يجب أن تكون رداً على رسالة مني. ❌")
                await delete_messages_safely(event.chat_id, [event.id]) # حذف رسالة الأمر
                return

        # أوامر الكتم والإنذار
        if text in ("كتم", "الغاء كتم", "انذار") and is_admin_user:
            reply_msg = await event.get_reply_message()
            user_id = reply_msg.sender_id
            target_user = await client.get_entity(user_id)
            if target_user.bot: # لا يمكن كتم البوتات
                await event.reply("لا يمكنني كتم البوتات. 🚫")
                await delete_messages_safely(event.chat_id, [event.id])
                return

            try:
                if text == "كتم":
                    await client.edit_permissions(event.chat_id, user_id, send_messages=False)
                    await event.reply("تم كتم العضو لمدة 24 ساعة. 🔇")
                elif text == "الغاء كتم":
                    await client.edit_permissions(event.chat_id, user_id, send_messages=True)
                    await event.reply("تم إلغاء كتم العضو. ✅")
                elif text == "انذار":
                    count = warns.get(user_id, 0) + 1
                    warns[user_id] = count
                    await save_data() # حفظ الإنذارات
                    if count >= 3:
                        await client.edit_permissions(event.chat_id, user_id, until_date=datetime.timedelta(hours=6), send_messages=False)
                        await event.reply(f"الإنذار 3/3.. تم كتم العضو 6 ساعات تلقائياً. ⚠️")
                        warns[user_id] = 0 # إعادة تعيين الإنذارات بعد الكتم
                        await save_data() # حفظ الإنذارات بعد إعادة التعيين
                    else:
                        await event.reply(f"تم إعطاء إنذار للعضو ({count}/3). ⚠️")
            except ChatAdminRequiredError:
                await event.reply("لا أستطيع تنفيذ الأمر. يرجى التأكد من أنني مشرف في المجموعة ولدي الصلاحيات اللازمة. ⚠️")
            except Exception as e:
                print(f"خطأ في أمر الإشراف ({text}): {e}")
                await event.reply("حدث خطأ أثناء تنفيذ أمر الإشراف. ❌")
            await delete_messages_safely(event.chat_id, [event.id]) # حذف رسالة الأمر
            return # تم التعامل مع الأمر

    # --- 8.2. معالجة الردود الذكية وزيادة الإحصائيات ---
    # تجاهل الرسائل التي تبدأ بأوامر البوت لتجنب تكرار المعالجة
    if event.text.startswith((
        'رد (', 'تعديل (', 'صوره (', 'فيديو (', 'all',
        'رد (', 'تعديل (', 'صوره (', 'فيديو (', 'all',
        'كيف احذف', 'ا', 'أ', 'إ', 'آ'
    )):
        return

    input_text = normalize_text(event.text) # تنظيف النص للمقارنة
    
    # زيادة الإحصائيات لكل رسالة عادية
    stats[event.sender_id] = stats.get(event.sender_id, 0) + 1
    await save_data() # حفظ الإحصائيات

    # الردود النصية
    if input_text in custom_responses:
        await event.reply(custom_responses[input_text])
        return
    
    # الردود الميديا
    if input_text in custom_media:
        media_info = custom_media[input_text]
        media_type = media_info['type']
        media_id = media_info['id']
        try:
            if media_type == 'photo':
                await client.send_file(event.chat_id, types.InputPhoto(media_id, 0, 0, b''), reply_to=event.id)
            elif media_type == 'video':
                await client.send_file(event.chat_id, types.InputDocument(media_id, 0, b'', b''), reply_to=event.id)
        except Exception as e:
            print(f"خطأ في إرسال الميديا للكلمة {input_text}: {e}")
            await event.reply("حدث خطأ أثناء إرسال الميديا. ❌")
        return

# --- 9. أمر المساعدة ---
@client.on(events.NewMessage(pattern=r'(?i)^كيف احذف$'))
async def help_edit_delete_handler(event):
    """يقدم مساعدة حول كيفية التعديل والحذف."""
    help_text = (
        "💡 **طريقة الحذف والتعديل:**\n\n"
        "1️⃣ **للتعديل:** اضغط مطولاً على رسالتك واختر (Edit) أو (تعديل).\n"
        "2️⃣ **للحذف:** اضغط مطولاً على الرسالة واختر (Delete) ثم حدد 'حذف للكل'.\n\n"
        "ملاحظة: يمكنك تعديل رسائلك خلال 48 ساعة فقط."
    )
    await event.reply(help_text)
    await delete_messages_safely(event.chat_id, [event.id]) # حذف رسالة الأمر

# --- 10. تشغيل البوت ---

async def main():
    """الدالة الرئيسية لتشغيل البوت."""
    await load_data() # تحميل البيانات عند بدء التشغيل
    await client.start(bot_token=BOT_TOKEN)
    print("البوت يعمل الآن بنجاح...")
    await client.run_until_disconnected()
    await save_data() # حفظ البيانات عند إيقاف التشغيل (قد لا تعمل دائماً في حالات الإيقاف المفاجئ)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("تم إيقاف البوت يدوياً.")
    except Exception as e:
        print(f"حدث خطأ غير متوقع في التشغيل الرئيسي: {e}")

