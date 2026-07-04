# -*- coding: utf-8 -*-
from telethon import TelegramClient, events, types, Button
from telethon.tl import functions
import asyncio
import json
import os
import datetime
import re

try:
    from anthropic import AsyncAnthropic
except ImportError:
    AsyncAnthropic = None

# ──────────────────────────────────────────────────────────────────────────────
# =========================
# القسم 1
# الإعدادات الأساسية
# =========================
# ──────────────────────────────────────────────────────────────────────────────


api_id = 34257542
api_hash = '614a1b5c5b712ac6de5530d5c571c42a'
bot_token = '7957660443:AAH3cDCqtKcXHeAh01k044M6ghypxCAO1TA'
owner_id = 1486879970

# مفتاح Claude API لفهم صيغ التكرار الحرة (مرتين بالأسبوع، كل خميسين، إلخ).
# لازم تضيف المفتاح كمتغير بيئة قبل تشغيل البوت:
#   export ANTHROPIC_API_KEY="sk-ant-..."
# إذا ما توفر المفتاح أو فشل الاتصال، البوت يرجع تلقائياً لتحليل القواعد
# اليدوية (parse_recurrence_rules) حتى لا يتعطل.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if (AsyncAnthropic and ANTHROPIC_API_KEY) else None

client = TelegramClient('bot_session', api_id, api_hash).start(bot_token=bot_token)

DATA_FILE = 'bot_data.json'

# ──────────────────────────────────────────────────────────────────────────────
# =========================
# القسم 2
# قاعدة البيانات (JSON)
# =========================
# ──────────────────────────────────────────────────────────────────────────────


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
                if "authorized_users" not in data:
                    data["authorized_users"] = []
                if "known_groups" not in data:
                    data["known_groups"] = {}
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
        # قائمة معرّفات (IDs) الأشخاص المسموح لهم باستخدام أوامر التحكم
        # بالمجموعات من الخاص (جدولة / رسالة فورية)، بالإضافة إلى الأونر.
        "authorized_users": [],
        # سجل المجموعات التي البوت عضو فيها: {str(chat_id): title}.
        # البوتات ممنوعة من استخدام GetDialogsRequest (خطأ BotMethodInvalidError)،
        # فلا نقدر نستعرض محادثات البوت مباشرة من API كما يفعل حساب مستخدم عادي.
        # الحل: نسجّل كل مجموعة تلقائياً وقت دخول البوت لها أو أول رسالة يرصدها
        # فيها، ونحدّث هذا السجل بدلاً من الاعتماد على iter_dialogs.
        "known_groups": {},
        "meta": {"created": str(datetime.datetime.now())}
    }

db = load_db()

def save_db():
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(db, f, ensure_ascii=False, indent=4, default=lambda x: str(x))
    except:
        pass

# ──────────────────────────────────────────────────────────────────────────────
# =========================
# القسم 3
# أدوات مساعدة
# =========================
# ──────────────────────────────────────────────────────────────────────────────


last_actions = {}
waiting_for_media = {}
bot_id = None

# كاش لصور الملف الشخصي (لأمر "ا") لتسريع الرد المتكرر
_profile_photo_cache = {}
PROFILE_PHOTO_CACHE_TTL = 300  # 5 دقائق

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

# كاش للأدمنية: (chat_id, sender_id) -> (is_admin: bool, expires_at: float)
# بدون هذا الكاش، كل رسالة عادية (مثل "ا") تضطر تنتظر عدة طلبات شبكة
# متتالية لتيليجرام (get_permissions) قبل ما يوصل الرد للمستخدم، وهذا
# هو السبب الرئيسي لتأخر الردود.
_admin_cache = {}
ADMIN_CACHE_TTL = 300  # 5 دقائق

async def is_admin(event):
    if event.sender_id == owner_id:
        return True
    if event.is_private:
        return False

    cache_key = (event.chat_id, event.sender_id)
    now = asyncio.get_event_loop().time()
    cached = _admin_cache.get(cache_key)
    if cached and cached[1] > now:
        return cached[0]

    try:
        perms = await client.get_permissions(event.chat_id, event.sender_id)
        result = bool(perms.is_admin)
    except:
        result = False

    _admin_cache[cache_key] = (result, now + ADMIN_CACHE_TTL)
    return result


async def is_admin_in_chat(chat_id, sender_id):
    """
    نفس فكرة is_admin لكنها تتحقق من صلاحية شخص بمجموعة محدّدة بدلاً من
    الاعتماد على event.chat_id الحالي. تُستخدم في أوامر التحكم من الخاص
    (جدولة/رسالة لمجموعة معيّنة)، حيث تكون المحادثة الحالية (الخاص) غير
    المجموعة المستهدفة.
    """
    if sender_id == owner_id:
        return True

    cache_key = (chat_id, sender_id)
    now = asyncio.get_event_loop().time()
    cached = _admin_cache.get(cache_key)
    if cached and cached[1] > now:
        return cached[0]

    try:
        perms = await client.get_permissions(chat_id, sender_id)
        result = bool(perms.is_admin)
    except:
        result = False

    _admin_cache[cache_key] = (result, now + ADMIN_CACHE_TTL)
    return result


def is_authorized_dm(sender_id):
    """
    يتحقق إذا كان الشخص مسموح له باستخدام أوامر التحكم من الخاص
    (جدولة / رسالة فورية لمجموعة معيّنة). الأونر مخوّل دائماً، بالإضافة
    لأي شخص أضافه الأونر للقائمة المخوّلة (db["authorized_users"]).
    """
    if sender_id == owner_id:
        return True
    return sender_id in db.get("authorized_users", [])


def register_known_group(chat_id, title):
    """
    يسجّل/يحدّث مجموعة بسجل known_groups. تُستدعى من أي حدث يصل من
    مجموعة (رسالة جديدة أو دخول البوت)، لأن البوتات ممنوعة من استخدام
    GetDialogsRequest ولا تقدر "تستعرض" قائمة محادثاتها مباشرة من API.
    """
    key = str(chat_id)
    title = title or "بدون اسم"
    if db["known_groups"].get(key) != title:
        db["known_groups"][key] = title
        save_db()


@client.on(events.NewMessage)
async def group_registry_handler(event):
    """
    معالج خفيف جداً (بدون أي await أو شبكة) يسجّل كل مجموعة يصل منها
    البوت أي رسالة، لتعويض عدم إمكانية استخدام iter_dialogs مع البوتات.
    """
    if event.is_private or not event.is_group:
        return
    chat = event.chat
    title = getattr(chat, "title", None) if chat else None
    register_known_group(event.chat_id, title)

# ──────────────────────────────────────────────────────────────────────────────
# =========================
# القسم 4
# الترحيب (صورة العضو + منشن)
# =========================
# ──────────────────────────────────────────────────────────────────────────────


@client.on(events.ChatAction)
async def welcome(event):
    if event.user_joined:
        user = await event.get_user()

        # لو المنضم هو البوت نفسه (تمت إضافته لمجموعة جديدة): نسجّل
        # المجموعة فوراً بسجل known_groups، ولا نرسل رسالة ترحيب له.
        my_id = await get_bot_id()
        if user.id == my_id:
            chat = await event.get_chat()
            title = getattr(chat, "title", None)
            register_known_group(event.chat_id, title)
            return

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

# ──────────────────────────────────────────────────────────────────────────────
# =========================
# القسم 5
# إضافة رد نصي
# =========================
# ──────────────────────────────────────────────────────────────────────────────


@client.on(events.NewMessage(pattern=r'(?s)^رد\s+\((.*?)\)\s+\((.*)\)'))
async def add_text_reply(event):
    if not await is_admin(event): return
    
    word = event.pattern_match.group(1).strip()
    reply = event.pattern_match.group(2).strip()
    
    db["responses"][word] = reply
    save_db()
    
    m = await event.reply(f"✅ تمت إضافة الرد بنجاح\nالكلمة: ({word})\nالرد: ({reply})")
    last_actions[(event.chat_id, m.id)] = ("text", word, event.id)

# ──────────────────────────────────────────────────────────────────────────────
# =========================
# القسم 6
# إضافة رد وسائط (صور / فيديو)
# =========================
# ──────────────────────────────────────────────────────────────────────────────


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
    # فلتر فوري بدون await: نتجاهل أي رسالة من مستخدم ما طلب صورة/فيديو،
    # وهذا يغطي 99% من الرسائل العادية فوراً بدون أي تأخير.
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

# ──────────────────────────────────────────────────────────────────────────────
# =========================
# القسم 7
# تعديل عدد رسائل مستخدم
# =========================
# ──────────────────────────────────────────────────────────────────────────────


@client.on(events.NewMessage(pattern=r'^تعديل رسائل$'))
async def edit_messages_prompt(event):
    if not await is_admin(event): return
    await event.reply("يرجى إرسال المنشن (أو المعرف) متبوعاً بالعدد الجديد.\nمثال: `@username 286` أو قم بالرد على رسالة الشخص واكتب العدد.")

@client.on(events.NewMessage)
async def edit_messages_handler(event):
    text = event.text.strip() if event.text else ""
    if not text:
        return

    # نفحص شكل النص أولاً (بدون أي طلب شبكة) قبل ما نستدعي is_admin،
    # عشان رسائل عادية كثير زي "ا" أو أي كلام آخر ما تنتظر شبكة بدون فايدة.
    match = re.match(r'^(?:@(\w+)|\[.*?\]\(tg://user\?id=(\d+)\))\s+(\d+)$', text)
    is_reply_digit = event.is_reply and text.isdigit()

    if not match and not is_reply_digit:
        return

    if not await is_admin(event):
        return

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

# ──────────────────────────────────────────────────────────────────────────────
# =========================
# القسم 8
# الحذف الذكي (نصوص ووسائط)
# =========================
# ──────────────────────────────────────────────────────────────────────────────


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

# ──────────────────────────────────────────────────────────────────────────────
# =========================
# القسم 9
# حذف آخر X رسالة بالقروب
# =========================
# ──────────────────────────────────────────────────────────────────────────────


@client.on(events.NewMessage(pattern=r'(?i)^حذف\s+(?:ا|أ)خر\s*([\d٠-٩]+)\s*(?:رساله|رسالة|رسائل)\s*$'))
async def delete_last_n_messages(event):
    if not await is_admin(event): return
    if event.is_private:
        return

    count_str = normalize_text(event.pattern_match.group(1))
    count = int(count_str)

    if count <= 0:
        return await event.reply("⚠️ العدد يجب أن يكون أكبر من صفر.")

    # حد أقصى احترازي عشان ما نضغط على حدود تيليجرام
    count = min(count, 5000)

    chat_id = event.chat_id

    status_msg = await event.reply(f"🗑️ جاري حذف آخر {count} رسالة...")

    # نجمع المعرفات: من رسالة الأمر نفسها للخلف
    ids_to_delete = [event.id]  # نضيف رسالة الأمر نفسها ضمن الحذف

    try:
        async for msg in client.iter_messages(chat_id, offset_id=event.id, limit=count):
            ids_to_delete.append(msg.id)
    except Exception as e:
        return await status_msg.edit(
            f"❌ تعذّر قراءة سجل الرسائل: {e}\n"
            "غالباً البوت ما عنده صلاحية كافية لقراءة/حذف الرسائل في هذه المجموعة."
        )

    found_count = len(ids_to_delete) - 1  # بدون رسالة الأمر نفسها
    if found_count == 0:
        return await status_msg.edit(
            "⚠️ ما لقيت رسائل قبل هذا الأمر للحذف.\n"
            "تأكد إن فيه رسائل سابقة بالمجموعة، أو إن البوت أدمن وعنده صلاحية حذف الرسائل."
        )

    deleted_total = 0
    failed_chunks = 0
    try:
        # الحذف على دفعات (تيليجرام يسمح بحذف عدة رسائل بنفس الاستدعاء، لكن نقسمها احترازاً)
        chunk_size = 100
        for i in range(0, len(ids_to_delete), chunk_size):
            chunk = ids_to_delete[i:i + chunk_size]
            try:
                result = await client.delete_messages(chat_id, chunk)
                # Telethon يرجع قائمة AffectedMessages؛ لو فاضية يعني الحذف لم يُطبّق فعلياً
                deleted_total += len(chunk)
            except Exception as chunk_err:
                failed_chunks += 1
                print(f"Bulk Delete Chunk Error: {chunk_err}")
            await asyncio.sleep(0.3)

        if failed_chunks > 0 and deleted_total == 0:
            await status_msg.edit(
                "❌ فشل الحذف بالكامل. السبب الأرجح: البوت ليس أدمن، أو ليس لديه صلاحية "
                "'حذف الرسائل' (Delete Messages) في إعدادات صلاحيات المجموعة."
            )
            return

        await status_msg.delete()
        note = "" if failed_chunks == 0 else "\n⚠️ بعض الرسائل لم تُحذف (قد تكون قديمة جداً أو محذوفة مسبقاً)."
        confirm = await client.send_message(chat_id, f"✅ تم حذف {deleted_total} رسالة بنجاح.{note}")
        await asyncio.sleep(3)
        await confirm.delete()
    except Exception as e:
        try:
            await status_msg.edit(f"❌ حدث خطأ أثناء الحذف: {e}")
        except:
            print(f"Bulk Delete Error: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# =========================
# القسم 10
# المنشن الجماعي (تاق الكل)
# =========================
# ──────────────────────────────────────────────────────────────────────────────


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

# ──────────────────────────────────────────────────────────────────────────────
# =========================
# القسم 11
# الكتم والإنذار
# =========================
# ──────────────────────────────────────────────────────────────────────────────


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

# ──────────────────────────────────────────────────────────────────────────────
# =========================
# القسم 12
# جدولة الرسائل (وقت + تكرار + نص/صورة/فيديو)
# =========================
# ──────────────────────────────────────────────────────────────────────────────


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


def parse_recurrence_rules(raw_text):
    """
    [نسخة احتياطية - قواعد يدوية] تُستخدم فقط إذا تعذّر الوصول لـ Claude API.
    يحاول استخراج نوع التكرار من نص حر. يرجع dict بالشكل:
      {"type": "daily"}
      {"type": "weekly", "weekday": 4}
      {"type": "weekly_count", "times": 2}
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

    # مرات في الأسبوع (مرتين بالأسبوع، 3 مرات في الاسبوع...)
    m = re.search(r'(\d+)\s*مر(?:ات|ة|ه)?\s*(?:في\s*ال|بال|كل\s*)?(?:اسبوع|أسبوع)', text)
    if m:
        return {"type": "weekly_count", "times": int(m.group(1))}
    if "مرتين بالاسبوع" in text or "مرتين في الاسبوع" in text or "مرتين بالأسبوع" in text or "مرتين في الأسبوع" in text:
        return {"type": "weekly_count", "times": 2}

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


RECURRENCE_AI_SYSTEM_PROMPT = """أنت محلل صيغ تكرار زمنية لبوت تيليجرام عربي. مهمتك تحويل أي
جملة عربية (بأي لهجة خليجية أو مصرية أو شامية أو فصحى، حتى لو فيها أخطاء
إملائية أو مختصرة) تصف تكرار رسالة، إلى JSON واحد فقط بدون أي شرح إضافي
وبدون Markdown.

الأنواع المسموحة فقط:
{"type": "daily"}
{"type": "interval_days", "days": <رقم>}
{"type": "weekly", "weekday": <0-6 أو null>}   // 0=الإثنين ... 6=الأحد، null = نفس يوم الإنشاء
{"type": "weekly_count", "times": <رقم>}        // مرتين/ثلاث/أربع مرات أسبوعياً بدون تحديد أيام
{"type": "monthly", "day": <1-31 أو null>}      // null = نفس يوم الإنشاء بالشهر
{"type": "monthly_count", "times": <رقم>}       // عدد مرات بالشهر

أمثلة:
"يومي" -> {"type": "daily"}
"كل يومين" -> {"type": "interval_days", "days": 2}
"مرتين بالاسبوع" أو "مرتين كل اسبوع" أو "2 مرات أسبوعيا" -> {"type": "weekly_count", "times": 2}
"الجمعة" أو "كل جمعة" -> {"type": "weekly", "weekday": 4}
"اسبوعي" بدون تحديد يوم -> {"type": "weekly", "weekday": null}
"شهري" -> {"type": "monthly", "day": null}
"يوم 15 من كل شهر" -> {"type": "monthly", "day": 15}
"3 مرات بالشهر" -> {"type": "monthly_count", "times": 3}
"تخطي" أو نص غير مفهوم -> {"type": "daily"}

أرجع فقط كائن JSON صحيح واحد، بدون أي نص أو تعليق آخر."""


async def parse_recurrence_ai(raw_text):
    """يستخدم Claude API لفهم صيغة التكرار بأي لهجة أو احتمال صياغة."""
    if not anthropic_client:
        return None
    try:
        response = await anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            system=RECURRENCE_AI_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": raw_text}],
        )
        raw = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)

        allowed_types = {"daily", "interval_days", "weekly", "weekly_count", "monthly", "monthly_count"}
        if data.get("type") not in allowed_types:
            return None

        # تحقق وتنظيف بسيط للحقول حسب النوع
        t = data["type"]
        if t == "interval_days":
            data["days"] = max(1, int(data.get("days", 1)))
        elif t == "weekly":
            wd = data.get("weekday")
            data["weekday"] = int(wd) if wd is not None and 0 <= int(wd) <= 6 else None
        elif t == "weekly_count":
            data["times"] = max(2, int(data.get("times", 2)))
        elif t == "monthly":
            day = data.get("day")
            data["day"] = int(day) if day is not None and 1 <= int(day) <= 31 else None
        elif t == "monthly_count":
            data["times"] = max(1, int(data.get("times", 1)))

        return data
    except Exception as e:
        print(f"Recurrence AI Error: {e}")
        return None


async def parse_recurrence(raw_text):
    """
    يحاول فهم صيغة التكرار عبر Claude API أولاً (يدعم أي لهجة واحتمال صياغة).
    إذا فشل (لا يوجد مفتاح API، أو خطأ شبكة، أو رد غير متوقع)، يرجع تلقائياً
    لتحليل القواعد اليدوية البسيط حتى لا يتعطل البوت.
    """
    ai_result = await parse_recurrence_ai(raw_text)
    if ai_result:
        return ai_result
    return parse_recurrence_rules(raw_text)


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
    if t == "weekly_count":
        return f"{rec['times']} مرات بالأسبوع"
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

    if t == "weekly_count":
        times = max(1, rec.get("times", 2))
        interval_days = max(1, 7 // times)
        candidate = base
        if created_dt:
            ref = created_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            elapsed = (now - ref).days
            cycles = (elapsed // interval_days) + 1
            candidate = ref + datetime.timedelta(days=interval_days * cycles)
        if candidate <= now:
            candidate += datetime.timedelta(days=interval_days)
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

def schedule_list_keyboard(sched_ids):
    """
    لوحة مفاتيح موحّدة لرسالة عرض كل الجدولات: زر حذف وزر تعديل لكل جدولة
    (مرقّمة بترتيب ظهورها بالرسالة)، وفي الأسفل زر رجوع واحد للقائمة الرئيسية.
    """
    rows = []
    for idx, sid in enumerate(sched_ids, start=1):
        rows.append([
            Button.inline(f"✏️ تعديل #{idx}", f"sched_edit_{sid}".encode()),
            Button.inline(f"🗑️ حذف #{idx}", f"sched_del_{sid}".encode()),
        ])
    rows.append([Button.inline("🔙 رجوع", b"sched_back")])
    return rows


def truncate_preview(text, limit=60):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."


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
    if event.is_private:
        return  # تُعالج بمعالج dm_schedule_menu بالقسم 13 (التحكم من الخاص)
    if not await is_admin(event): return
    await event.reply("⏰ قائمة جدولة الرسائل التلقائية:", buttons=schedule_keyboard())


@client.on(events.CallbackQuery(data=b"sched_new"))
async def schedule_new(event):
    if not await is_admin(event):
        return await event.answer("ليس لديك صلاحية.", alert=True)

    state = {
        "step": "time",
        "chat_id": event.chat_id,
        "setup_chat_id": event.chat_id,  # محادثة الإعداد = نفس المجموعة هنا
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

    sched_ids = list(chat_schedules.keys())
    lines = ["📋 الجدولات الحالية:\n"]

    for idx, sid in enumerate(sched_ids, start=1):
        s = chat_schedules[sid]
        times_str = " / ".join(f"{t['hour']:02d}:{t['minute']:02d}" for t in s.get("times", []))
        content = s.get("content", {})
        if content.get("type") == "media":
            kind = content.get("media_kind", "وسائط")
            caption_preview = truncate_preview(content.get("caption", ""), 40)
            preview = f"[{kind}]" + (f" — {caption_preview}" if caption_preview else "")
        else:
            preview = truncate_preview(content.get("text", ""), 60)
        rec_desc = recurrence_description(s.get("recurrence", {"type": "daily"}))

        lines.append(
            f"#{idx} ⏰ {times_str} | 🔁 {rec_desc}\n"
            f"   📝 {preview}"
        )

    full_message = "\n\n".join(lines)
    await event.edit(full_message, buttons=schedule_list_keyboard(sched_ids))


@client.on(events.CallbackQuery(data=b"sched_back"))
async def schedule_back(event):
    if not await is_admin(event):
        return await event.answer("ليس لديك صلاحية.", alert=True)
    await event.edit("⏰ قائمة جدولة الرسائل التلقائية:", buttons=schedule_keyboard())


@client.on(events.CallbackQuery(pattern=rb"^sched_del_(.+)$"))
async def schedule_delete(event):
    if not await is_admin(event):
        return await event.answer("ليس لديك صلاحية.", alert=True)

    sched_id = event.pattern_match.group(1).decode()
    sched = db["schedules"].get(sched_id)

    if sched:
        # حذف كل رسائل ضبط الجدولة المرتبطة (من لحظة الضغط على "جدولة جديدة" حتى التأكيد)
        # ملاحظة: محادثة الإعداد (setup_chat_id) قد تختلف عن المجموعة الهدف
        # (chat_id) في حال أُنشئت الجدولة من الخاص لمجموعة بعيدة.
        setup_ids = sched.get("setup_msg_ids", [])
        setup_chat_id = int(sched.get("setup_chat_id", sched["chat_id"]))
        db["schedules"].pop(sched_id, None)
        save_db()
        stop_schedule_task(sched_id)

        try:
            if setup_ids:
                await client.delete_messages(setup_chat_id, setup_ids)
        except Exception as e:
            print(f"Setup messages delete error: {e}")

        await event.answer("🗑️ تم حذف الجدولة.")
        # نحدّث رسالة القائمة الموحدة نفسها بدل حذفها أو إرسال رسالة جديدة
        await schedule_list(event)
    else:
        await event.answer("❌ هذه الجدولة محذوفة مسبقاً.", alert=True)
        await schedule_list(event)


@client.on(events.CallbackQuery(pattern=rb"^sched_edit_(.+)$"))
async def schedule_edit(event):
    if not await is_admin(event):
        return await event.answer("ليس لديك صلاحية.", alert=True)

    sched_id = event.pattern_match.group(1).decode()
    if sched_id not in db["schedules"]:
        await event.answer("❌ هذه الجدولة محذوفة مسبقاً.", alert=True)
        return await schedule_list(event)

    scheduling_state[event.sender_id] = {
        "step": "edit_time",
        "chat_id": event.chat_id,
        "sched_id": sched_id,
        "conv_msg_ids": [],
    }
    await event.edit(
        "🕖 أرسل الوقت/الأوقات الجديدة (نفس الصيغ المرنة مدعومة):\n"
        "مثال: 7 صباحا — 19:30 — 7 صباحا و7 مساء",
        buttons=[[Button.inline("🔙 إلغاء", b"sched_list")]],
    )


@client.on(events.NewMessage)
async def schedule_conversation_handler(event):
    """يلتقط الرسائل أثناء عملية إنشاء/تعديل الجدولة (وقت → تكرار → محتوى)."""
    if event.sender_id not in scheduling_state:
        return

    # الصلاحية: بالمجموعات نتحقق بـ is_admin كالمعتاد، وبالخاص (تحكم بمجموعة
    # مختارة عن بُعد) نتحقق من القائمة المخوّلة بدلاً من ذلك.
    if event.is_private:
        if not is_authorized_dm(event.sender_id):
            return
    elif not await is_admin(event):
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
            rec = await parse_recurrence(text)
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
            "setup_chat_id": state.get("setup_chat_id", state["chat_id"]),
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

# ──────────────────────────────────────────────────────────────────────────────
# =========================
# القسم 13
# التحكم بالمجموعات من الخاص (قائمة مخوّلين + جدولة / رسالة فورية)
# =========================
# ──────────────────────────────────────────────────────────────────────────────

# حالة محادثة "رسالة فورية لمجموعة" من الخاص: sender_id -> dict
# {"step": "content"/..., "chat_id": <معرف المجموعة المختارة>}
dm_instant_state = {}

DM_GROUPS_PAGE_SIZE = 8


async def get_bot_groups():
    """
    يرجع قائمة (chat_id, title) لكل المجموعات/السوبرجروبات المسجّلة في
    db["known_groups"].

    ملاحظة مهمة: تيليجرام يمنع حسابات البوتات من استخدام GetDialogsRequest
    (الطريقة التي يستخدمها iter_dialogs)، ويرمي BotMethodInvalidError عند
    أي محاولة استخدامها. لذلك لا توجد طريقة لـ"استعراض" محادثات البوت
    مباشرة من الـ API كما يفعل حساب مستخدم عادي. الحل المعتمد هنا: نسجّل
    كل مجموعة فور دخول البوت لها أو أول رسالة تصل منها (عبر
    register_known_group بالقسم 3 ومعالج welcome بالقسم 4)، ونقرأ هذي
    القائمة المحفوظة هنا بدل تصفّحها من الـ API.
    """
    return [
        (int(chat_id), title)
        for chat_id, title in db.get("known_groups", {}).items()
    ]


def dm_groups_keyboard(groups, action_prefix, page=0):
    """
    يبني لوحة أزرار لاختيار مجموعة من قائمة، مع ترقيم صفحات لو كانت
    القائمة طويلة. action_prefix يحدد الإجراء التالي بعد الاختيار
    (مثلاً "dmsched" للجدولة أو "dminstant" للرسالة الفورية).
    """
    start = page * DM_GROUPS_PAGE_SIZE
    end = start + DM_GROUPS_PAGE_SIZE
    page_groups = groups[start:end]

    rows = []
    for chat_id, title in page_groups:
        label = title if len(title) <= 30 else title[:27] + "..."
        rows.append([Button.inline(f"👥 {label}", f"{action_prefix}_pick_{chat_id}".encode())])

    nav_row = []
    if start > 0:
        nav_row.append(Button.inline("◀️ السابق", f"{action_prefix}_page_{page-1}".encode()))
    if end < len(groups):
        nav_row.append(Button.inline("التالي ▶️", f"{action_prefix}_page_{page+1}".encode()))
    if nav_row:
        rows.append(nav_row)

    rows.append([Button.inline("❌ إلغاء", f"{action_prefix}_cancel".encode())])
    return rows


# قاموس مؤقت يخزّن آخر قائمة مجموعات تم عرضها لكل مستخدم (لدعم الصفحات
# بدون إعادة استدعاء iter_dialogs في كل ضغطة "التالي/السابق")
_dm_groups_cache = {}


@client.on(events.NewMessage(pattern=r'^جدولة$', func=lambda e: e.is_private))
async def dm_schedule_menu(event):
    if not is_authorized_dm(event.sender_id):
        return await event.reply("⚠️ ما عندك صلاحية استخدام هذا الأمر من الخاص.")

    groups = await get_bot_groups()
    if not groups:
        return await event.reply(
            "❌ لا توجد مجموعات مسجّلة عند البوت حالياً.\n"
            "اكتب أي رسالة عادية (مثل: مرحبا) داخل كل مجموعة تريد التحكم بها، "
            "ثم جرّب هذا الأمر مرة أخرى."
        )

    _dm_groups_cache[event.sender_id] = groups
    await event.reply(
        "👥 اختر المجموعة التي تريد جدولة رسالة فيها:",
        buttons=dm_groups_keyboard(groups, "dmsched", page=0),
    )


@client.on(events.NewMessage(pattern=r'^رسالة$', func=lambda e: e.is_private))
async def dm_instant_menu(event):
    if not is_authorized_dm(event.sender_id):
        return await event.reply("⚠️ ما عندك صلاحية استخدام هذا الأمر من الخاص.")

    groups = await get_bot_groups()
    if not groups:
        return await event.reply(
            "❌ لا توجد مجموعات مسجّلة عند البوت حالياً.\n"
            "اكتب أي رسالة عادية (مثل: مرحبا) داخل كل مجموعة تريد التحكم بها، "
            "ثم جرّب هذا الأمر مرة أخرى."
        )

    _dm_groups_cache[event.sender_id] = groups
    await event.reply(
        "👥 اختر المجموعة التي تريد إرسال رسالة فورية فيها:",
        buttons=dm_groups_keyboard(groups, "dminstant", page=0),
    )


@client.on(events.CallbackQuery(pattern=rb"^(dmsched|dminstant)_page_(\d+)$"))
async def dm_groups_page(event):
    if not is_authorized_dm(event.sender_id):
        return await event.answer("⚠️ ما عندك صلاحية.", alert=True)

    prefix = event.pattern_match.group(1).decode()
    page = int(event.pattern_match.group(2))
    groups = _dm_groups_cache.get(event.sender_id, [])
    if not groups:
        return await event.edit("❌ انتهت صلاحية هذه القائمة، أرسل الأمر من جديد.")

    label = "جدولة رسالة" if prefix == "dmsched" else "إرسال رسالة فورية"
    await event.edit(
        f"👥 اختر المجموعة التي تريد {label} فيها:",
        buttons=dm_groups_keyboard(groups, prefix, page=page),
    )


@client.on(events.CallbackQuery(pattern=rb"^(dmsched|dminstant)_cancel$"))
async def dm_groups_cancel(event):
    await event.edit("❌ تم الإلغاء.")


@client.on(events.CallbackQuery(pattern=rb"^dmsched_pick_(-?\d+)$"))
async def dm_schedule_pick_group(event):
    if not is_authorized_dm(event.sender_id):
        return await event.answer("⚠️ ما عندك صلاحية.", alert=True)

    target_chat_id = int(event.pattern_match.group(1))

    # نبدأ نفس تدفق الجدولة المستخدم بالمجموعات (وقت → تكرار → محتوى)،
    # لكن chat_id هنا هو المجموعة المختارة، و setup_chat_id هو محادثة
    # الخاص الحالية (حيث تجري كل خطوات الإعداد فعلياً).
    state = {
        "step": "time",
        "chat_id": target_chat_id,
        "setup_chat_id": event.chat_id,
        "conv_msg_ids": [],
    }
    scheduling_state[event.sender_id] = state

    msg = await event.get_message()
    state["conv_msg_ids"].append(msg.id)

    await event.edit(
        "🕖 أرسل وقت/أوقات الإرسال (يقبل صيغ متعددة):\n"
        "مثال: 7 صباحا — ٧:٣٠ — 19:30 — 7 صباحا و7 مساء"
    )


@client.on(events.CallbackQuery(pattern=rb"^dminstant_pick_(-?\d+)$"))
async def dm_instant_pick_group(event):
    if not is_authorized_dm(event.sender_id):
        return await event.answer("⚠️ ما عندك صلاحية.", alert=True)

    target_chat_id = int(event.pattern_match.group(1))

    dm_instant_state[event.sender_id] = {
        "chat_id": target_chat_id,
    }

    await event.edit(
        "📝 أرسل الآن نص الرسالة، أو صورة/فيديو (مع كابشن اختياري)، "
        "وسيتم إرسالها فوراً للمجموعة المختارة."
    )


@client.on(events.NewMessage(func=lambda e: e.is_private))
async def dm_instant_content_handler(event):
    """يستقبل محتوى الرسالة الفورية بعد اختيار المجموعة من dm_instant_menu."""
    if event.sender_id not in dm_instant_state:
        return
    if not is_authorized_dm(event.sender_id):
        return

    state = dm_instant_state.pop(event.sender_id)
    target_chat_id = state["chat_id"]
    text = event.text.strip() if event.text else ""

    try:
        if event.photo or event.video:
            await client.send_file(target_chat_id, event.media, caption=text or None)
        elif text:
            await client.send_message(target_chat_id, text)
        else:
            dm_instant_state[event.sender_id] = state  # نرجّع الحالة، المحتوى غير صالح
            return await event.reply("⚠️ أرسل نص الرسالة أو صورة/فيديو.")

        await event.reply("✅ تم إرسال الرسالة للمجموعة بنجاح.")
    except Exception as e:
        await event.reply(f"❌ فشل إرسال الرسالة: {e}")


# -------- إدارة القائمة المخوّلة (للأونر فقط) -------- #

@client.on(events.NewMessage(pattern=r'(?i)^اضافة\s+(\d+)$|^إضافة\s+(\d+)$', func=lambda e: e.is_private))
async def add_authorized_user(event):
    if event.sender_id != owner_id:
        return

    raw_id = event.pattern_match.group(1) or event.pattern_match.group(2)
    new_id = int(raw_id)

    if new_id == owner_id:
        return await event.reply("ℹ️ أنت الأونر بالفعل، عندك كل الصلاحيات.")

    if new_id in db["authorized_users"]:
        return await event.reply("ℹ️ هذا المعرف مخوّل بالفعل.")

    db["authorized_users"].append(new_id)
    save_db()
    await event.reply(f"✅ تمت إضافة {new_id} للقائمة المخوّلة بأوامر الجدولة/الرسالة من الخاص.")


@client.on(events.NewMessage(pattern=r'(?i)^حذف\s+مخول\s+(\d+)$', func=lambda e: e.is_private))
async def remove_authorized_user(event):
    if event.sender_id != owner_id:
        return

    target_id = int(event.pattern_match.group(1))
    if target_id not in db["authorized_users"]:
        return await event.reply("ℹ️ هذا المعرف غير موجود بالقائمة.")

    db["authorized_users"].remove(target_id)
    save_db()
    await event.reply(f"🗑️ تمت إزالة {target_id} من القائمة المخوّلة.")


@client.on(events.NewMessage(pattern=r'(?i)^المخولين$', func=lambda e: e.is_private))
async def list_authorized_users(event):
    if event.sender_id != owner_id:
        return

    authorized = db.get("authorized_users", [])
    if not authorized:
        return await event.reply(
            "📋 لا يوجد أشخاص مخوّلون حالياً (بالإضافة للأونر).\n"
            "لإضافة أحد، اكتب: إضافة <ID>"
        )

    lines = ["📋 القائمة المخوّلة بأوامر الخاص:\n"]
    for uid in authorized:
        lines.append(f"• {uid}")
    lines.append("\nلإضافة: إضافة <ID>\nللحذف: حذف مخول <ID>")
    await event.reply("\n".join(lines))

# ──────────────────────────────────────────────────────────────────────────────
# =========================
# القسم 14
# معالج الرسائل العام (الردود التلقائية + بروفايل)
# =========================
# ──────────────────────────────────────────────────────────────────────────────


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

        # كاش لصورة الملف الشخصي (5 دقائق) لتجنب تحميل الصورة من تيليجرام
        # في كل مرة يكتب فيها المستخدم "ا"، وهذا كان مصدر تأخير ملحوظ.
        now = asyncio.get_event_loop().time()
        cached_photo = _profile_photo_cache.get(event.sender_id)
        photo = None
        if cached_photo and cached_photo[1] > now:
            photo = cached_photo[0]
        else:
            try:
                photo = await client.download_profile_photo(event.sender_id)
            except Exception as e:
                print(f"Profile Photo Error: {e}")
                photo = None
            _profile_photo_cache[event.sender_id] = (photo, now + PROFILE_PHOTO_CACHE_TTL)

        try:
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

# ──────────────────────────────────────────────────────────────────────────────
# =========================
# القسم 15
# تشغيل البوت
# =========================
# ──────────────────────────────────────────────────────────────────────────────


print("🚀 البوت يعمل الآن...")
restart_all_schedules()
client.run_until_disconnected()
