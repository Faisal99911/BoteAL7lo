# -*- coding: utf-8 -*-
"""
بوت تيليجرام (Telethon) - النسخة المحدّثة

متغيرات البيئة:
  API_ID / API_HASH / BOT_TOKEN   (إجبارية)
  OWNER_ID                        (اختياري، الافتراضي معرّفك الحالي)
  BOT_DATA_DIR                    (اختياري: مجلد حفظ البيانات. اجعله مجلد دائم لو الاستضافة تمسح الملفات)
  BOT_TIMEZONE                    (اختياري: مثل Asia/Riyadh إذا سيرفرك بتوقيت مختلف)
  ANTHROPIC_API_KEY               (اختياري: لفهم صيغ التكرار الحرة)
"""
import asyncio
import copy
import datetime
import json
import os
import re
import shutil
import time

from telethon import TelegramClient, events, types, Button
from telethon.tl import functions
from telethon.errors import MessageNotModifiedError

try:
    from anthropic import AsyncAnthropic
except ImportError:
    AsyncAnthropic = None

# ══════════════════════════════════════════════════════════════════════════════
# القسم 1: الإعدادات الأساسية
# ══════════════════════════════════════════════════════════════════════════════

api_id = int(os.environ.get("API_ID") or 0)
api_hash = os.environ.get("API_HASH") or ""
bot_token = os.environ.get("BOT_TOKEN") or ""
owner_id = int(os.environ.get("OWNER_ID") or 1486879970)

if not (api_id and api_hash and bot_token):
    raise SystemExit("❌ لازم تحدد API_ID و API_HASH و BOT_TOKEN كمتغيرات بيئة قبل التشغيل.")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if (AsyncAnthropic and ANTHROPIC_API_KEY) else None

# التوقيت: افتراضياً توقيت السيرفر. حدّد BOT_TIMEZONE=Asia/Riyadh مثلاً لو السيرفر UTC.
LOCAL_TZ = None
_tz_name = os.environ.get("BOT_TIMEZONE")
if _tz_name:
    try:
        from zoneinfo import ZoneInfo
        LOCAL_TZ = ZoneInfo(_tz_name)
    except Exception as _e:
        print(f"⚠️ تعذّر ضبط المنطقة الزمنية {_tz_name}: {_e}")


def now_local():
    if LOCAL_TZ:
        return datetime.datetime.now(LOCAL_TZ).replace(tzinfo=None)
    return datetime.datetime.now()


def to_local_naive(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(LOCAL_TZ).replace(tzinfo=None) if LOCAL_TZ else dt.astimezone().replace(tzinfo=None)


# مسارات التخزين: مطلقة (بجانب السكربت) حتى لا تتغير بتغيّر مجلد التشغيل
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.environ.get("BOT_DATA_DIR") or BASE_DIR)
DATA_FILE = os.path.join(DATA_DIR, "bot_data.json")
MEDIA_DIR = os.path.join(DATA_DIR, "bot_media")
PHOTO_DIR = os.path.join(DATA_DIR, "profile_photos")
for _d in (DATA_DIR, MEDIA_DIR, PHOTO_DIR):
    os.makedirs(_d, exist_ok=True)

# ترحيل: لو الملف القديم كان بمجلد التشغيل وليس بجانب السكربت
_legacy = os.path.join(os.getcwd(), "bot_data.json")
if not os.path.exists(DATA_FILE) and os.path.exists(_legacy) and os.path.abspath(_legacy) != DATA_FILE:
    shutil.copy2(_legacy, DATA_FILE)

client = TelegramClient(os.path.join(DATA_DIR, "bot_session"), api_id, api_hash).start(bot_token=bot_token)

# ══════════════════════════════════════════════════════════════════════════════
# القسم 2: قاعدة البيانات (JSON) - حفظ آمن + نسخة احتياطية
# ══════════════════════════════════════════════════════════════════════════════

ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')


def normalize_text(s):
    return (s or "").translate(ARABIC_DIGITS).replace('ـ', '')


_last_id = 0


def new_id(prefix):
    global _last_id
    n = int(time.time() * 1000)
    if n <= _last_id:
        n = _last_id + 1
    _last_id = n
    return f"{prefix}{n}"


DB_DEFAULTS = {
    "replies": {},            # rid -> {"keyword", "content", "created"}
    "stats": {},              # user_id -> عدد الرسائل
    "warnings": {},
    "muted": {},
    "schedules": {},
    "authorized_users": [],   # مخوّلين بأوامر الخاص (غير الأونر)
    "known_groups": {},       # str(chat_id) -> title (البوتات ما تقدر تستعرض المحادثات)
    "profile_overrides": {},  # str(user_id) -> {name,id,rank,join,dur}
    "first_seen": {},         # "chat:user" -> أول ظهور (احتياطي لتاريخ الانضمام)
    "meta": {},
}
LOST_MEDIA_WORDS = []


def ensure_schema(data):
    for k, v in DB_DEFAULTS.items():
        if k not in data:
            data[k] = copy.deepcopy(v)
    # ترحيل الردود النصية القديمة
    old_responses = data.pop("responses", None)
    if old_responses:
        for word, text in old_responses.items():
            data["replies"][new_id("r")] = {
                "keyword": word,
                "content": {"type": "text", "text": text},
                "created": now_local().isoformat(),
            }
    # ردود الوسائط القديمة كانت محفوظة كنص (str) غير قابل للاستعادة
    old_media = data.pop("media", None)
    if old_media:
        LOST_MEDIA_WORDS.extend(old_media.keys())
    return data


def load_db():
    for path in (DATA_FILE, DATA_FILE + ".bak"):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    if path != DATA_FILE:
                        print("⚠️ الملف الرئيسي تالف، تم الاسترجاع من النسخة الاحتياطية.")
                    return ensure_schema(data)
            except Exception as e:
                print(f"⚠️ فشل قراءة {path}: {e}")
                try:  # لا نمسح الملف التالف أبداً، نحتفظ بنسخة منه
                    shutil.copy2(path, f"{path}.corrupt-{int(time.time())}")
                except Exception:
                    pass
    return ensure_schema({})


db = load_db()
_dirty = False


def mark_dirty():
    global _dirty
    _dirty = True


def save_db():
    """حفظ ذري: نكتب بملف مؤقت ثم نستبدل، مع الاحتفاظ بنسخة .bak من الحفظة السابقة."""
    global _dirty
    try:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=1, default=str)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(DATA_FILE):
            shutil.copy2(DATA_FILE, DATA_FILE + ".bak")
        os.replace(tmp, DATA_FILE)
        _dirty = False
    except Exception as e:
        print(f"❌ فشل حفظ قاعدة البيانات: {e}")


async def autosave_loop():
    while True:
        await asyncio.sleep(30)
        if _dirty:
            save_db()


reply_lookup = {}


def rebuild_reply_lookup():
    reply_lookup.clear()
    for r in db["replies"].values():
        reply_lookup[r["keyword"]] = r["content"]


rebuild_reply_lookup()

# ══════════════════════════════════════════════════════════════════════════════
# القسم 3: أدوات مساعدة (صلاحيات، وسائط، حالات المحادثة)
# ══════════════════════════════════════════════════════════════════════════════

bot_id = None


async def get_bot_id():
    global bot_id
    if bot_id is None:
        me = await client.get_me()
        bot_id = me.id
    return bot_id


_admin_cache = {}
ADMIN_CACHE_TTL = 300


async def is_admin(event):
    if event.sender_id == owner_id:
        return True
    if event.is_private:
        return False
    key = (event.chat_id, event.sender_id)
    now = time.monotonic()
    cached = _admin_cache.get(key)
    if cached and cached[1] > now:
        return cached[0]
    try:
        perms = await client.get_permissions(event.chat_id, event.sender_id)
        result = bool(perms.is_admin)
    except Exception:
        result = False
    _admin_cache[key] = (result, now + ADMIN_CACHE_TTL)
    return result


def is_authorized_dm(sender_id):
    return sender_id == owner_id or sender_id in db.get("authorized_users", [])


async def can_manage(event):
    """بالخاص: الأونر + المخوّلين. بالمجموعة: الأدمن."""
    if event.is_private:
        return is_authorized_dm(event.sender_id)
    return await is_admin(event)


def register_known_group(chat_id, title):
    key = str(chat_id)
    title = title or "بدون اسم"
    if db["known_groups"].get(key) != title:
        db["known_groups"][key] = title
        save_db()


def get_groups():
    items = [(int(cid), title) for cid, title in db.get("known_groups", {}).items()]
    return sorted(items, key=lambda x: x[1])


def group_title(chat_id):
    return db["known_groups"].get(str(chat_id)) or str(chat_id)


def full_name(u):
    parts = [getattr(u, "first_name", None), getattr(u, "last_name", None)]
    return " ".join(p for p in parts if p) or getattr(u, "title", None) or "بدون اسم"


def truncate_preview(text, limit=60):
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit - 3] + "..."


# ---------- الوسائط: تُحفظ كملفات على القرص (وليس كائنات تيليجرام) ----------

_media_cache = {}  # مسار الملف -> كائن media جاهز للإرسال السريع (ذاكرة فقط)


def media_full_path(rel):
    return os.path.abspath(os.path.join(DATA_DIR, rel))


async def store_media(event, prefix):
    msg = event.message
    if msg.photo:
        kind = "photo"
    elif msg.video or msg.gif:
        kind = "video"
    else:
        return None
    base = os.path.join(MEDIA_DIR, f"{prefix}_{int(time.time() * 1000)}")
    path = await msg.download_media(file=base)
    if not path:
        return None
    path = os.path.abspath(path)
    _media_cache[path] = msg.media
    return {"kind": kind, "path": os.path.relpath(path, DATA_DIR)}


async def content_from_event(event, prefix):
    """يحوّل رسالة (نص / صورة / فيديو) إلى content قابل للحفظ بـ JSON."""
    text = (event.text or "").strip()
    if event.photo or event.video or event.gif:
        media = await store_media(event, prefix)
        if not media:
            return None
        return {"type": "media", "kind": media["kind"], "path": media["path"], "caption": text}
    if text:
        return {"type": "text", "text": text}
    return None


async def send_content(chat_id, content, reply_to=None):
    if content.get("type") == "media":
        rel = content.get("path")
        if not rel:
            raise ValueError("الوسائط غير محفوظة (جدولة/رد قديم) - أعد إضافتها")
        full = media_full_path(rel)
        if not os.path.exists(full):
            raise FileNotFoundError("ملف الوسائط غير موجود على السيرفر")
        caption = content.get("caption") or None
        cached = _media_cache.get(full)
        if cached is not None:
            try:
                return await client.send_file(chat_id, cached, caption=caption, reply_to=reply_to)
            except Exception:
                _media_cache.pop(full, None)
        sent = await client.send_file(
            chat_id, full, caption=caption, reply_to=reply_to,
            supports_streaming=(content.get("kind") == "video"),
        )
        try:
            _media_cache[full] = sent.media
        except Exception:
            pass
        return sent
    return await client.send_message(chat_id, content.get("text", ""), reply_to=reply_to)


def remove_media_file(content):
    try:
        rel = (content or {}).get("path")
        if rel:
            full = media_full_path(rel)
            _media_cache.pop(full, None)
            if os.path.exists(full):
                os.remove(full)
    except Exception as e:
        print(f"Media remove error: {e}")


def content_preview(content, limit=50):
    if not content:
        return "—"
    if content.get("type") == "media":
        kind = content.get("kind") or ("photo" if content.get("media_kind") == "صورة" else "video")
        label = "🖼️ صورة" if kind == "photo" else "🎬 فيديو"
        if not content.get("path"):
            return f"{label} ⚠️ (تالف - أعد إضافته)"
        cap = truncate_preview(content.get("caption", ""), limit)
        return label + (f" — {cap}" if cap else "")
    return "📝 " + truncate_preview(content.get("text", ""), limit)


# ---------- حالات المحادثة (flows): حالة واحدة لكل مستخدم ----------

FLOW_TTL = 300
flows = {}


def set_flow(sender_id, chat_id, kind, panel_id=None, prompt="", cancel=None, **kw):
    f = {"kind": kind, "chat_id": chat_id, "panel_id": panel_id,
         "prompt": prompt, "cancel": cancel, "ts": time.monotonic()}
    f.update(kw)
    flows[sender_id] = f
    return f


def get_flow(sender_id, chat_id=None):
    f = flows.get(sender_id)
    if not f:
        return None
    if time.monotonic() - f["ts"] > FLOW_TTL:
        flows.pop(sender_id, None)
        return None
    if chat_id is not None and f["chat_id"] != chat_id:
        return None
    return f


async def cb_edit(event, text, buttons=None):
    try:
        await event.answer()
    except Exception:
        pass
    try:
        await event.edit(text, buttons=buttons, parse_mode=None)
    except MessageNotModifiedError:
        pass


async def panel_edit(f, text, buttons=None):
    try:
        await client.edit_message(f["chat_id"], f["panel_id"], text, buttons=buttons, parse_mode=None)
    except MessageNotModifiedError:
        pass
    except Exception:
        try:
            m = await client.send_message(f["chat_id"], text, buttons=buttons, parse_mode=None)
            f["panel_id"] = m.id
        except Exception as e:
            print(f"panel_edit error: {e}")


async def flow_show(f, prompt, cancel=None, warn=None):
    f["prompt"], f["cancel"] = prompt, cancel
    await panel_edit(f, (f"⚠️ {warn}\n\n" if warn else "") + prompt, cancel)


async def flow_warn(f, warn):
    await flow_show(f, f["prompt"], f["cancel"], warn=warn)


async def begin_flow(event, kind, prompt, cancel, **kw):
    """يبدأ محادثة من زر: يعدّل نفس رسالة اللوحة."""
    set_flow(event.sender_id, event.chat_id, kind, panel_id=event.query.msg_id,
             prompt=prompt, cancel=cancel, **kw)
    await cb_edit(event, prompt, cancel)


async def finish_flow_with_reply(event, f, text, buttons=None):
    flows.pop(event.sender_id, None)
    try:
        await client.delete_messages(f["chat_id"], f["panel_id"])
    except Exception:
        pass
    await event.reply(text, buttons=buttons, parse_mode=None)


# ---------- تسجيل المجموعات (البوتات ممنوعة من iter_dialogs) ----------

@client.on(events.NewMessage)
async def group_registry_handler(event):
    if event.is_private or not event.is_group or not event.sender_id:
        return
    title = getattr(event.chat, "title", None) if event.chat else None
    register_known_group(event.chat_id, title)
    key = f"{event.chat_id}:{event.sender_id}"
    if key not in db["first_seen"]:
        db["first_seen"][key] = now_local().isoformat()
        mark_dirty()


# ══════════════════════════════════════════════════════════════════════════════
# القسم 4: معالج المحادثات التفاعلية (يُسجَّل مبكراً ليلتقط الرسائل قبل غيره)
# ══════════════════════════════════════════════════════════════════════════════

ADD_REPLY_RE = re.compile(r'^(?:اضف|أضف|اضافة|إضافة)\s+رد$')
MENU_WORDS = {"جدولة", "رسالة", "لوحة", "لوحه", "القائمة", "قائمة", "الردود", "قائمة الردود"}
CANCEL_WORDS = {"الغاء", "إلغاء", "/cancel"}
FLOW_HANDLERS = {}  # يُملأ بنهاية الملف


@client.on(events.NewMessage)
async def flow_handler(event):
    if event.out or not event.sender_id:
        return
    f = get_flow(event.sender_id, event.chat_id)
    if not f:
        return
    text = (event.text or "").strip()

    if text in CANCEL_WORDS:
        flows.pop(event.sender_id, None)
        await panel_edit(f, "❌ تم الإلغاء.")
        raise events.StopPropagation

    # لو كتب أمر قائمة جديد نلغي المحادثة الحالية ونترك الأمر يمر
    if text.startswith("/") or text in MENU_WORDS or ADD_REPLY_RE.match(text):
        flows.pop(event.sender_id, None)
        return

    f["ts"] = time.monotonic()
    handler = FLOW_HANDLERS.get(f["kind"])
    if handler:
        try:
            await handler(event, f)
        except events.StopPropagation:
            raise
        except Exception as e:
            print(f"Flow error ({f['kind']}): {e}")
            try:
                await event.reply(f"❌ حدث خطأ: {e}")
            except Exception:
                pass
    raise events.StopPropagation


# ══════════════════════════════════════════════════════════════════════════════
# القسم 5: الترحيب
# ══════════════════════════════════════════════════════════════════════════════

_photo_cache = {}
PHOTO_TTL = 300


async def get_profile_photo(user):
    uid = getattr(user, "id", user)
    now = time.monotonic()
    c = _photo_cache.get(uid)
    if c and c[1] > now and (c[0] is None or os.path.exists(c[0])):
        return c[0]
    path = None
    try:
        path = await client.download_profile_photo(user, file=os.path.join(PHOTO_DIR, f"{uid}.jpg"))
    except Exception as e:
        print(f"Profile Photo Error: {e}")
    _photo_cache[uid] = (path, now + PHOTO_TTL)
    return path


@client.on(events.ChatAction)
async def welcome(event):
    my_id = await get_bot_id()

    if event.user_left or event.user_kicked:
        try:
            if my_id in (event.user_ids or []):
                if db["known_groups"].pop(str(event.chat_id), None) is not None:
                    save_db()
        except Exception:
            pass
        return

    if not (event.user_joined or event.user_added):
        return
    try:
        users = await event.get_users()
    except Exception:
        users = []

    for user in users or []:
        if user.id == my_id:  # البوت انضاف لمجموعة جديدة: نسجّلها بدون ترحيب
            try:
                chat = await event.get_chat()
                register_known_group(event.chat_id, getattr(chat, "title", None))
            except Exception:
                pass
            continue
        if getattr(user, "bot", False):
            continue

        db["first_seen"][f"{event.chat_id}:{user.id}"] = now_local().isoformat()
        mark_dirty()

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
            photo = await get_profile_photo(user)
            if photo:
                await client.send_file(event.chat_id, photo, caption=welcome_text)
            else:
                await client.send_message(event.chat_id, welcome_text)
        except Exception as e:
            print(f"Welcome Error: {e}")
            try:
                await client.send_message(event.chat_id, welcome_text)
            except Exception:
                pass

# ══════════════════════════════════════════════════════════════════════════════
# القسم 6: الردود التلقائية (إضافة / قائمة تفاعلية / تعديل / حذف)
# ══════════════════════════════════════════════════════════════════════════════

RP_PAGE = 6
RP_ADD_PROMPT = "📝 قم بإضافة الرد:\nأرسل أولاً الكلمة اللي تبي البوت يرد عليها."
RP_CONTENT_PROMPT = "💬 أرسل الآن الرد (نص / صورة / فيديو):"
CANCEL_TO_LIST = [[Button.inline("❌ إلغاء", b"rp:l:0")]]


def upsert_reply(keyword, content):
    rid = next((k for k, r in db["replies"].items() if r["keyword"] == keyword), None)
    if rid:
        remove_media_file(db["replies"][rid]["content"])
    else:
        rid = new_id("r")
    db["replies"][rid] = {"keyword": keyword, "content": content, "created": now_local().isoformat()}
    rebuild_reply_lookup()
    save_db()
    return rid


def reply_icon(content):
    if content.get("type") == "media":
        return "🖼️" if content.get("kind") == "photo" else "🎬"
    return "📝"


def replies_list_view(page=0, private=False):
    items = list(db["replies"].items())
    total = len(items)
    pages = max(1, (total + RP_PAGE - 1) // RP_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = items[page * RP_PAGE:(page + 1) * RP_PAGE]

    if total == 0:
        text = "💬 لا توجد ردود مسجّلة بعد.\nاضغط (➕ إضافة رد) للبدء."
    else:
        text = f"💬 الردود المسجّلة ({total}) — صفحة {page + 1}/{pages}\nاضغط على أي رد لتعديله أو حذفه:"

    rows = [[Button.inline(f"{reply_icon(r['content'])} {truncate_preview(r['keyword'], 28)}",
                           f"rp:v:{rid}".encode())] for rid, r in chunk]
    nav = []
    if page > 0:
        nav.append(Button.inline("◀️ السابق", f"rp:l:{page - 1}".encode()))
    if page < pages - 1:
        nav.append(Button.inline("التالي ▶️", f"rp:l:{page + 1}".encode()))
    if nav:
        rows.append(nav)
    rows.append([Button.inline("➕ إضافة رد", b"rp:add")])
    rows.append([Button.inline("🏠 القائمة الرئيسية", b"dm:home")] if private
                else [Button.inline("❌ إغلاق", b"rp:close")])
    return text, rows


def reply_detail_view(rid, notice=""):
    r = db["replies"].get(rid)
    if not r:
        return "❌ هذا الرد غير موجود.", [[Button.inline("🔙 رجوع", b"rp:l:0")]]
    text = (notice + f"🔤 الكلمة: {r['keyword']}\n"
            f"💬 الرد: {content_preview(r['content'], 120)}")
    rows = [
        [Button.inline("✏️ تعديل الرد", f"rp:ec:{rid}".encode()),
         Button.inline("🔤 تعديل الكلمة", f"rp:ek:{rid}".encode())],
        [Button.inline("👁️ معاينة", f"rp:pv:{rid}".encode()),
         Button.inline("🗑️ حذف", f"rp:d:{rid}".encode())],
        [Button.inline("🔙 رجوع للقائمة", b"rp:l:0")],
    ]
    return text, rows


# إضافة رد بالأمر النصي القديم: رد (كلمة) (رد)
@client.on(events.NewMessage(pattern=r'(?s)^رد\s+\((.*?)\)\s+\((.*)\)'))
async def add_text_reply(event):
    if not await can_manage(event):
        return
    word = event.pattern_match.group(1).strip()
    reply = event.pattern_match.group(2).strip()
    if not word or not reply:
        return
    upsert_reply(word, {"type": "text", "text": reply})
    await event.reply(f"✅ تمت إضافة الرد بنجاح\nالكلمة: ({word})\nالرد: ({reply})", parse_mode=None)


# إضافة رد بالطريقة الجديدة: "اضف رد"
@client.on(events.NewMessage(pattern=r'^(?:اضف|أضف|اضافة|إضافة)\s+رد$'))
async def add_reply_cmd(event):
    if not await can_manage(event):
        return
    m = await event.reply(RP_ADD_PROMPT, buttons=CANCEL_TO_LIST, parse_mode=None)
    set_flow(event.sender_id, event.chat_id, "rp_add", panel_id=m.id, step="keyword",
             prompt=RP_ADD_PROMPT, cancel=CANCEL_TO_LIST)


@client.on(events.NewMessage(pattern=r'^(?:الردود|قائمة الردود)$'))
async def replies_menu_cmd(event):
    if not await can_manage(event):
        return
    text, buttons = replies_list_view(0, event.is_private)
    await event.reply(text, buttons=buttons, parse_mode=None)


async def flow_rp_add(event, f):
    text = (event.text or "").strip()
    if f["step"] == "keyword":
        if not text or event.media:
            return await flow_warn(f, "أرسل الكلمة نصاً.")
        f["keyword"] = text
        f["step"] = "content"
        exists = text in reply_lookup
        note = "\n(الكلمة موجودة مسبقاً، سيتم استبدال ردها)" if exists else ""
        return await flow_show(f, f"🔤 الكلمة: {truncate_preview(text, 40)}{note}\n\n{RP_CONTENT_PROMPT}", CANCEL_TO_LIST)

    content = await content_from_event(event, "reply")
    if not content:
        return await flow_warn(f, "أرسل نص أو صورة أو فيديو.")
    upsert_reply(f["keyword"], content)
    await finish_flow_with_reply(
        event, f,
        f"✅ تمت إضافة الرد بنجاح\n🔤 الكلمة: {f['keyword']}\n💬 الرد: {content_preview(content, 80)}",
        [[Button.inline("➕ إضافة رد آخر", b"rp:add"), Button.inline("📋 قائمة الردود", b"rp:l:0")]],
    )


async def flow_rp_edit(event, f):
    rid = f["rid"]
    r = db["replies"].get(rid)
    if not r:
        flows.pop(event.sender_id, None)
        return await panel_edit(f, "❌ هذا الرد غير موجود.")

    if f["kind"] == "rp_ek":
        kw = (event.text or "").strip()
        if not kw or event.media:
            return await flow_warn(f, "أرسل الكلمة نصاً.")
        if any(k != rid and x["keyword"] == kw for k, x in db["replies"].items()):
            return await flow_warn(f, "هذي الكلمة مستخدمة لرد آخر.")
        r["keyword"] = kw
    else:
        content = await content_from_event(event, "reply")
        if not content:
            return await flow_warn(f, "أرسل نص أو صورة أو فيديو.")
        remove_media_file(r["content"])
        r["content"] = content

    rebuild_reply_lookup()
    save_db()
    flows.pop(event.sender_id, None)
    text, buttons = reply_detail_view(rid, "✅ تم التحديث\n\n")
    await panel_edit(f, text, buttons)


@client.on(events.CallbackQuery(pattern=rb"^rp:([a-z]+)(?::(.*))?$"))
async def rp_callback(event):
    if not await can_manage(event):
        return await event.answer("⚠️ ما عندك صلاحية.", alert=True)
    action = event.pattern_match.group(1).decode()
    arg = (event.pattern_match.group(2) or b"").decode()
    private = event.is_private
    flows.pop(event.sender_id, None)

    if action == "close":
        try:
            await event.delete()
        except Exception:
            pass
        return
    if action == "l":
        text, buttons = replies_list_view(int(arg or 0), private)
        return await cb_edit(event, text, buttons)
    if action == "add":
        return await begin_flow(event, "rp_add", RP_ADD_PROMPT, CANCEL_TO_LIST, step="keyword")

    rid = arg
    r = db["replies"].get(rid)
    if not r:
        await event.answer("❌ هذا الرد غير موجود.", alert=True)
        text, buttons = replies_list_view(0, private)
        return await cb_edit(event, text, buttons)

    back = [[Button.inline("🔙 إلغاء", f"rp:v:{rid}".encode())]]
    if action == "v":
        text, buttons = reply_detail_view(rid)
        await cb_edit(event, text, buttons)
    elif action == "pv":
        try:
            await send_content(event.chat_id, r["content"])
            await event.answer("👁️ تمت المعاينة")
        except Exception as e:
            await event.answer(f"❌ تعذّر الإرسال: {e}"[:190], alert=True)
    elif action == "ec":
        await begin_flow(event, "rp_ec", "✏️ أرسل الرد الجديد (نص / صورة / فيديو):", back, rid=rid)
    elif action == "ek":
        await begin_flow(event, "rp_ek", f"🔤 الكلمة الحالية: {r['keyword']}\n\nأرسل الكلمة الجديدة:", back, rid=rid)
    elif action == "d":
        await cb_edit(
            event, f"⚠️ متأكد تبي تحذف الرد الخاص بـ ({r['keyword']})؟",
            [[Button.inline("✅ نعم، احذف", f"rp:dok:{rid}".encode()),
              Button.inline("❌ لا", f"rp:v:{rid}".encode())]],
        )
    elif action == "dok":
        remove_media_file(r["content"])
        db["replies"].pop(rid, None)
        rebuild_reply_lookup()
        save_db()
        await event.answer("🗑️ تم حذف الرد.")
        text, buttons = replies_list_view(0, private)
        await cb_edit(event, text, buttons)

# ══════════════════════════════════════════════════════════════════════════════
# القسم 7: تعديل عدد رسائل مستخدم (النسخة القديمة تعمل كما هي)
# ══════════════════════════════════════════════════════════════════════════════


@client.on(events.NewMessage(pattern=r'^تعديل رسائل$'))
async def edit_messages_prompt(event):
    if not await is_admin(event):
        return
    await event.reply("يرجى إرسال المنشن (أو المعرف) متبوعاً بالعدد الجديد.\nمثال: `@username 286` أو قم بالرد على رسالة الشخص واكتب العدد.")


@client.on(events.NewMessage)
async def edit_messages_handler(event):
    text = event.text.strip() if event.text else ""
    if not text:
        return
    match = re.match(r'^(?:@(\w+)|\[.*?\]\(tg://user\?id=(\d+)\))\s+(\d+)$', text)
    is_reply_digit = event.is_reply and text.isdigit()
    if not match and not is_reply_digit:
        return
    if not await is_admin(event):
        return

    target_id = None
    new_count = None
    if match:
        username, uid_mention, new_count = match.group(1), match.group(2), int(match.group(3))
        try:
            target_id = str((await client.get_entity(username)).id) if username else str(uid_mention)
        except Exception:
            return
    else:
        reply_msg = await event.get_reply_message()
        target_id = str(reply_msg.sender_id)
        new_count = int(text)

    if target_id and new_count is not None:
        db["stats"][target_id] = new_count
        save_db()
        await event.reply(f"✅ تم تحديث عدد رسائل المستخدم إلى: {new_count}")

# ══════════════════════════════════════════════════════════════════════════════
# القسم 8: حذف آخر X رسالة بالقروب
# ══════════════════════════════════════════════════════════════════════════════


@client.on(events.NewMessage(pattern=r'(?i)^حذف\s+(?:ا|أ)خر\s*([\d٠-٩]+)\s*(?:رساله|رسالة|رسائل)\s*$'))
async def delete_last_n_messages(event):
    if not await is_admin(event):
        return
    if event.is_private:
        return

    count = int(normalize_text(event.pattern_match.group(1)))
    if count <= 0:
        return await event.reply("⚠️ العدد يجب أن يكون أكبر من صفر.")
    count = min(count, 5000)
    chat_id = event.chat_id
    status_msg = await event.reply(f"🗑️ جاري حذف آخر {count} رسالة...")

    ids_to_delete = [event.id]
    try:
        async for msg in client.iter_messages(chat_id, offset_id=event.id, limit=count):
            ids_to_delete.append(msg.id)
    except Exception as e:
        return await status_msg.edit(
            f"❌ تعذّر قراءة سجل الرسائل: {e}\n"
            "غالباً البوت ما عنده صلاحية كافية لقراءة/حذف الرسائل في هذه المجموعة."
        )

    if len(ids_to_delete) - 1 == 0:
        return await status_msg.edit(
            "⚠️ ما لقيت رسائل قبل هذا الأمر للحذف.\n"
            "تأكد إن فيه رسائل سابقة بالمجموعة، أو إن البوت أدمن وعنده صلاحية حذف الرسائل."
        )

    deleted_total = 0
    failed_chunks = 0
    try:
        for i in range(0, len(ids_to_delete), 100):
            chunk = ids_to_delete[i:i + 100]
            try:
                await client.delete_messages(chat_id, chunk)
                deleted_total += len(chunk)
            except Exception as chunk_err:
                failed_chunks += 1
                print(f"Bulk Delete Chunk Error: {chunk_err}")
            await asyncio.sleep(0.3)

        if failed_chunks > 0 and deleted_total == 0:
            return await status_msg.edit(
                "❌ فشل الحذف بالكامل. السبب الأرجح: البوت ليس أدمن، أو ليس لديه صلاحية "
                "'حذف الرسائل' (Delete Messages) في إعدادات صلاحيات المجموعة."
            )

        await status_msg.delete()
        note = "" if failed_chunks == 0 else "\n⚠️ بعض الرسائل لم تُحذف (قد تكون قديمة جداً أو محذوفة مسبقاً)."
        confirm = await client.send_message(chat_id, f"✅ تم حذف {deleted_total} رسالة بنجاح.{note}")
        await asyncio.sleep(3)
        await confirm.delete()
    except Exception as e:
        try:
            await status_msg.edit(f"❌ حدث خطأ أثناء الحذف: {e}")
        except Exception:
            print(f"Bulk Delete Error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# القسم 9: المنشن الجماعي
# ══════════════════════════════════════════════════════════════════════════════


@client.on(events.NewMessage(pattern=r'(?i)^all(?:\s+(.*))?'))
async def mention_all(event):
    if not await is_admin(event):
        return
    extra_text = event.pattern_match.group(1) or ""
    mentions = []
    async for user in client.iter_participants(event.chat_id):
        if not user.bot:
            mentions.append(f"[{user.first_name}](tg://user?id={user.id})")
    for i in range(0, len(mentions), 5):
        await client.send_message(event.chat_id, f"{extra_text}\n" + " ".join(mentions[i:i + 5]))
        await asyncio.sleep(0.5)

# ══════════════════════════════════════════════════════════════════════════════
# القسم 10: الكتم والإنذار
# (تيليجرام يفك الكتم تلقائياً عند until_date، فما نحتاج sleep داخل الأمر)
# ══════════════════════════════════════════════════════════════════════════════


@client.on(events.NewMessage(pattern=r'^كتم$'))
async def mute_command(event):
    if not await is_admin(event):
        return
    if not event.is_reply:
        return await event.reply("⚠️ يرجى الرد على رسالة المستخدم المراد كتمه.")

    reply_msg = await event.get_reply_message()
    user = await reply_msg.get_sender()
    until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=6)
    try:
        await client(functions.channels.EditBannedRequest(
            event.chat_id, user.id, types.ChatBannedRights(until_date=until, send_messages=True)))
        db["muted"][str(user.id)] = str(until)
        save_db()
        await event.reply(f"🔇 تم كتم [{user.first_name}](tg://user?id={user.id}) لمدة 6 ساعات.", parse_mode='md')
    except Exception as e:
        await event.reply(f"❌ فشل الكتم: {e}")


@client.on(events.NewMessage(pattern=r'^انذار$'))
async def warn_command(event):
    if not await is_admin(event):
        return
    if not event.is_reply:
        return await event.reply("⚠️ يرجى الرد على رسالة المستخدم المراد إنذاره.")

    reply_msg = await event.get_reply_message()
    user = await reply_msg.get_sender()
    user_id = str(user.id)
    current = db["warnings"].get(user_id, 0) + 1
    db["warnings"][user_id] = current
    save_db()

    if current == 1:
        await event.reply(
            f"⚠️ إنذار 1/2 لـ [{user.first_name}](tg://user?id={user.id})\n"
            f"تحذير: إنذار آخر سيؤدي إلى كتمك 6 ساعات!", parse_mode='md')
    elif current >= 2:
        until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=6)
        try:
            await client(functions.channels.EditBannedRequest(
                event.chat_id, user.id, types.ChatBannedRights(until_date=until, send_messages=True)))
            db["muted"][user_id] = str(until)
            db["warnings"][user_id] = 0
            save_db()
            await event.reply(
                f"🔇 [{user.first_name}](tg://user?id={user.id}) وصل إلى إنذار 2/2\n"
                f"تم كتمه تلقائياً لمدة 6 ساعات! 🚫", parse_mode='md')
        except Exception as e:
            await event.reply(f"❌ فشل الكتم: {e}")


@client.on(events.NewMessage(pattern=r'^الغاء كتم$'))
async def unmute_by_reply(event):
    if not await is_admin(event):
        return
    if not event.is_reply:
        return await event.reply("⚠️ يرجى الرد على رسالة المستخدم المراد إلغاء كتمه.")

    reply_msg = await event.get_reply_message()
    my_bot_id = await get_bot_id()
    if reply_msg.sender_id == my_bot_id:
        match = re.search(r'tg://user\?id=(\d+)', reply_msg.text or "")
        if not match:
            return await event.reply("❌ لم أتمكن من تحديد المستخدم من رسالة البوت.")
        target_user_id, target_name = int(match.group(1)), "المستخدم"
    else:
        sender = await reply_msg.get_sender()
        target_user_id, target_name = sender.id, sender.first_name

    try:
        await client(functions.channels.EditBannedRequest(
            event.chat_id, target_user_id, types.ChatBannedRights(until_date=None, send_messages=False)))
        db["muted"].pop(str(target_user_id), None)
        save_db()
        await event.reply(f"✅ تم إلغاء كتم [{target_name}](tg://user?id={target_user_id}) بنجاح.", parse_mode='md')
    except Exception as e:
        await event.reply(f"❌ فشل إلغاء الكتم: {e}")


@client.on(events.NewMessage(pattern=r'^الغاء كتم @(\w+)$'))
async def unmute_by_username(event):
    if not await is_admin(event):
        return
    username = event.pattern_match.group(1)
    try:
        user = None
        async for participant in client.iter_participants(event.chat_id):
            if participant.username and participant.username.lower() == username.lower():
                user = participant
                break
        if not user:
            return await event.reply(f"❌ لم يتم العثور على @{username} في المجموعة.")
        await client(functions.channels.EditBannedRequest(
            event.chat_id, user.id, types.ChatBannedRights(until_date=None, send_messages=False)))
        db["muted"].pop(str(user.id), None)
        save_db()
        await event.reply(f"✅ تم إلغاء كتم [{user.first_name}](tg://user?id={user.id}) بنجاح.", parse_mode='md')
    except Exception as e:
        await event.reply(f"❌ فشل إلغاء الكتم: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# القسم 11: فهم الوقت والتكرار
# ══════════════════════════════════════════════════════════════════════════════

WEEKDAY_NAMES = {
    "السبت": 5, "الأحد": 6, "الاحد": 6, "الإثنين": 0, "الاثنين": 0,
    "الثلاثاء": 1, "الثلاثا": 1, "الأربعاء": 2, "الاربعاء": 2, "الاربعا": 2,
    "الخميس": 3, "الجمعة": 4, "الجمعه": 4,
}


def parse_times(raw_text):
    """يستخرج وقت أو وقتين من نص حر: 7 صباحا، 7:30، 19:30، 7 صباحا و7 مساء ..."""
    text = normalize_text(raw_text).strip()
    text = text.replace("الساعة", "").replace("الساعه", "").replace("ساعة", "").replace("ساعه", "")
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
        results.append({"hour": hour, "minute": minute})
    return results


def parse_recurrence_rules(raw_text):
    """[احتياطي - قواعد يدوية] تُستخدم إذا تعذّر الوصول لـ Claude API."""
    text = normalize_text(raw_text).strip()

    m = re.search(r'كل\s*(\d+)\s*(?:يوم|أيام|ايام)', text)
    if m:
        return {"type": "interval_days", "days": int(m.group(1))}
    if "كل يومين" in text or "يوم بعد يوم" in text or "يوم وبعد يوم" in text:
        return {"type": "interval_days", "days": 2}
    if "كل ثلاث ايام" in text or "كل ثلاثة ايام" in text or "كل ثلاثة أيام" in text:
        return {"type": "interval_days", "days": 3}

    m = re.search(r'(\d+)\s*مر(?:ات|ة|ه)?\s*(?:في\s*ال|بال|كل\s*)?(?:اسبوع|أسبوع)', text)
    if m:
        return {"type": "weekly_count", "times": int(m.group(1))}
    if "مرتين بالاسبوع" in text or "مرتين في الاسبوع" in text or "مرتين بالأسبوع" in text or "مرتين في الأسبوع" in text:
        return {"type": "weekly_count", "times": 2}

    for name, wd in WEEKDAY_NAMES.items():
        if name in text:
            return {"type": "weekly", "weekday": wd}
    if ("اسبوعي" in text or "أسبوعي" in text or "كل اسبوع" in text or "كل أسبوع" in text
            or "بالاسبوع مره" in text or "بالاسبوع مرة" in text or "مرة بالاسبوع" in text or "مره بالاسبوع" in text):
        return {"type": "weekly", "weekday": None}

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
        return {"type": "monthly", "day": None}

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
    if not anthropic_client:
        return None
    try:
        response = await anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            system=RECURRENCE_AI_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": raw_text}],
        )
        raw = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)

        allowed = {"daily", "interval_days", "weekly", "weekly_count", "monthly", "monthly_count"}
        if data.get("type") not in allowed:
            return None
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
    ai_result = await parse_recurrence_ai(raw_text)
    return ai_result or parse_recurrence_rules(raw_text)


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
    now = now or now_local()
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
            remainder = (candidate.date() - ref.date()).days % days
            if remainder != 0:
                candidate += datetime.timedelta(days=(days - remainder))
        return candidate

    if t == "weekly":
        wd = rec.get("weekday")
        if wd is None and created_dt:
            wd = created_dt.weekday()
        if wd is None:
            wd = now.weekday()
        candidate = base + datetime.timedelta(days=(wd - base.weekday()) % 7)
        if candidate <= now:
            candidate += datetime.timedelta(days=7)
        return candidate

    if t in ("weekly_count", "monthly_count"):
        if t == "weekly_count":
            interval_days = max(1, 7 // max(1, rec.get("times", 2)))
        else:
            interval_days = max(1, 30 // max(1, rec.get("times", 1)))
        candidate = base
        if created_dt:
            ref = created_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            cycles = ((now - ref).days // interval_days) + 1
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
        for _ in range(48):
            try:
                candidate = datetime.datetime(year, month, day, hour, minute)
                if candidate > now:
                    return candidate
            except ValueError:
                pass
            month += 1
            if month > 12:
                month, year = 1, year + 1

    if base <= now:
        base += datetime.timedelta(days=1)
    return base

# ══════════════════════════════════════════════════════════════════════════════
# القسم 12: محرّك الجدولة
# ══════════════════════════════════════════════════════════════════════════════

schedule_tasks = {}  # sched_id -> [tasks]


async def schedule_loop(sched_id, time_index):
    while True:
        try:
            sched = db["schedules"].get(sched_id)
            if not sched or time_index >= len(sched.get("times", [])):
                return
            t = sched["times"][time_index]
            rec = sched.get("recurrence", {"type": "daily"})
            try:
                created_dt = datetime.datetime.fromisoformat(sched["created_at"])
            except Exception:
                created_dt = None

            now = now_local()
            target = next_run_datetime(t["hour"], t["minute"], rec, now=now, created_dt=created_dt)
            wait_seconds = (target - now).total_seconds()
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)

            sched = db["schedules"].get(sched_id)
            if not sched or time_index >= len(sched.get("times", [])):
                return
            try:
                await send_content(int(sched["chat_id"]), sched.get("content", {}))
            except Exception as e:
                print(f"Schedule Send Error ({sched_id}#{time_index}): {e}")
            await asyncio.sleep(2)  # حتى لا يتكرر الإرسال لو صحا اللوب مبكراً بأجزاء من الثانية
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"Schedule loop error ({sched_id}#{time_index}): {e}")
            await asyncio.sleep(30)


def stop_schedule_task(sched_id):
    for task in schedule_tasks.pop(sched_id, []):
        task.cancel()


def start_schedule_task(sched_id):
    stop_schedule_task(sched_id)
    sched = db["schedules"].get(sched_id)
    if not sched:
        return
    schedule_tasks[sched_id] = [
        asyncio.create_task(schedule_loop(sched_id, i)) for i in range(len(sched.get("times", [])))
    ]


def restart_all_schedules():
    for sched_id in list(db["schedules"].keys()):
        start_schedule_task(sched_id)

# ══════════════════════════════════════════════════════════════════════════════
# القسم 13: لوحة الجدولة التفاعلية (بالخاص: اختيار مجموعة / بالمجموعة: نفس المجموعة)
# ══════════════════════════════════════════════════════════════════════════════

SC_PAGE = 6
GROUPS_PAGE = 8
SC_TIME_PROMPT = ("🕖 أرسل وقت/أوقات الإرسال (يقبل صيغ متعددة):\n"
                  "مثال: 7 صباحا — ٧:٣٠ — 19:30 — 7 صباحا و7 مساء")
SC_REC_PROMPT = ("🔁 خلال كم تتكرر الرسالة؟ اكتب مثلاً:\n"
                 "يومي — كل يومين — كل 3 ايام — اسبوعي — الجمعة — شهري — يوم 15 من كل شهر — مرتين بالشهر\n"
                 "أو اضغط (يومياً) للتكرار الافتراضي.")
SC_REC_EDIT_PROMPT = ("🔁 أرسل التكرار الجديد، مثلاً:\n"
                      "يومي — كل يومين — اسبوعي — الجمعة — شهري — يوم 15 من كل شهر — مرتين بالشهر")
SC_CONTENT_PROMPT = "📝 الآن أرسل نص الرسالة، أو صورة/فيديو (مع كابشن اختياري) لتُرسل تلقائياً."
SC_CANCEL = [[Button.inline("❌ إلغاء", b"sc:home")]]
SC_REC_BUTTONS = [[Button.inline("📅 يومياً (افتراضي)", b"sc:daily")], [Button.inline("❌ إلغاء", b"sc:home")]]
SKIP_WORDS = ("تخطي", "تجاوز", "لا", "-")
NO_GROUPS_TEXT = ("❌ لا توجد مجموعات مسجّلة عند البوت حالياً.\n"
                  "أضف البوت للمجموعة واكتب أي رسالة عادية فيها (مثل: مرحبا) ثم جرّب مرة ثانية.")


def sched_times_str(s):
    return " / ".join(f"{t['hour']:02d}:{t['minute']:02d}" for t in s.get("times", []))


def sched_rec_str(s):
    try:
        created = datetime.datetime.fromisoformat(s["created_at"])
    except Exception:
        created = None
    return recurrence_description(s.get("recurrence", {"type": "daily"}), created)


def sched_menu_keyboard(private):
    rows = [[Button.inline("➕ جدولة جديدة", b"sc:new")],
            [Button.inline("📋 الرسائل المجدولة", b"sc:l:0")]]
    if private:
        rows.append([Button.inline("🏠 القائمة الرئيسية", b"dm:home")])
    return rows


def groups_keyboard(kind, page=0):
    groups = get_groups()
    start = page * GROUPS_PAGE
    rows = []
    for cid, title in groups[start:start + GROUPS_PAGE]:
        rows.append([Button.inline(f"👥 {truncate_preview(title, 28)}", f"{kind}:pick:{cid}".encode())])
    nav = []
    if start > 0:
        nav.append(Button.inline("◀️ السابق", f"{kind}:gp:{page - 1}".encode()))
    if start + GROUPS_PAGE < len(groups):
        nav.append(Button.inline("التالي ▶️", f"{kind}:gp:{page + 1}".encode()))
    if nav:
        rows.append(nav)
    rows.append([Button.inline("🔙 رجوع", b"dm:home")])
    return rows


async def show_group_picker(event, kind, page=0):
    if not get_groups():
        return await cb_edit(event, NO_GROUPS_TEXT, [[Button.inline("🔙 رجوع", b"dm:home")]])
    label = "جدولة رسالة" if kind == "sc" else "إرسال رسالة فورية"
    await cb_edit(event, f"👥 اختر المجموعة التي تريد {label} فيها:", groups_keyboard(kind, page))


def sched_list_view(chat_filter, page, private):
    items = [(sid, s) for sid, s in db["schedules"].items()
             if chat_filter is None or str(s.get("chat_id")) == str(chat_filter)]
    total = len(items)
    back = [Button.inline("🔙 رجوع", b"sc:home")]
    if not total:
        return "📋 لا توجد جدولات حالياً.", [[Button.inline("➕ جدولة جديدة", b"sc:new")], back]

    pages = (total + SC_PAGE - 1) // SC_PAGE
    page = max(0, min(page, pages - 1))
    start = page * SC_PAGE
    lines = [f"📋 الرسائل المجدولة ({total}) — صفحة {page + 1}/{pages}\nاضغط على الجدولة لعرضها وتعديلها:\n"]
    rows = []
    for i, (sid, s) in enumerate(items[start:start + SC_PAGE], start=start + 1):
        head = f"#{i}" + (f" 👥 {group_title(s['chat_id'])}" if private else "")
        lines.append(f"{head}\n⏰ {sched_times_str(s)} | 🔁 {sched_rec_str(s)}\n{content_preview(s.get('content'), 40)}\n")
        rows.append([Button.inline(f"✏️ #{i} — ⏰ {sched_times_str(s)}", f"sc:v:{sid}".encode())])
    nav = []
    if page > 0:
        nav.append(Button.inline("◀️ السابق", f"sc:l:{page - 1}".encode()))
    if page < pages - 1:
        nav.append(Button.inline("التالي ▶️", f"sc:l:{page + 1}".encode()))
    if nav:
        rows.append(nav)
    rows.append(back)
    return "\n".join(lines), rows


def sched_detail_view(sid, notice=""):
    s = db["schedules"].get(sid)
    if not s:
        return "❌ هذه الجدولة غير موجودة (ربما حُذفت).", [[Button.inline("🔙 رجوع", b"sc:l:0")]]
    text = (notice +
            f"📌 رسالة مجدولة\n\n"
            f"👥 المجموعة: {group_title(s['chat_id'])}\n"
            f"⏰ الأوقات: {sched_times_str(s)}\n"
            f"🔁 التكرار: {sched_rec_str(s)}\n"
            f"{content_preview(s.get('content'), 120)}")
    rows = [
        [Button.inline("⏰ تعديل الوقت", f"sc:et:{sid}".encode()),
         Button.inline("🔁 تعديل التكرار", f"sc:er:{sid}".encode())],
        [Button.inline("📝 تعديل المحتوى", f"sc:ec:{sid}".encode()),
         Button.inline("🗑️ حذف", f"sc:d:{sid}".encode())],
        [Button.inline("🔙 رجوع للقائمة", b"sc:l:0")],
    ]
    return text, rows


async def start_new_sched(event, target_chat_id):
    prompt = f"👥 المجموعة: {group_title(target_chat_id)}\n\n{SC_TIME_PROMPT}"
    await begin_flow(event, "sc_new", prompt, SC_CANCEL, step="time", target=target_chat_id)


@client.on(events.NewMessage(pattern=r'^جدولة$'))
async def schedule_menu(event):
    if not await can_manage(event):
        if event.is_private:
            await event.reply("⚠️ ما عندك صلاحية استخدام هذا الأمر من الخاص.")
        return
    await event.reply("⏰ جدولة الرسائل التلقائية:", buttons=sched_menu_keyboard(event.is_private), parse_mode=None)


@client.on(events.CallbackQuery(pattern=rb"^sc:([a-z]+)(?::(.*))?$"))
async def sc_callback(event):
    if not await can_manage(event):
        return await event.answer("⚠️ ما عندك صلاحية.", alert=True)
    action = event.pattern_match.group(1).decode()
    arg = (event.pattern_match.group(2) or b"").decode()
    private = event.is_private
    chat_filter = None if private else event.chat_id

    if action == "daily":  # زر "يومياً" أثناء خطوة التكرار
        f = get_flow(event.sender_id, event.chat_id)
        if f and f["kind"] == "sc_new" and f["step"] == "recurrence":
            f["recurrence"] = {"type": "daily"}
            f["step"] = "content"
            await event.answer()
            return await flow_show(f, SC_CONTENT_PROMPT, SC_CANCEL)
        return await event.answer()

    flows.pop(event.sender_id, None)

    if action in ("home", "cancel"):
        return await cb_edit(event, "⏰ جدولة الرسائل التلقائية:", sched_menu_keyboard(private))
    if action == "new":
        if private:
            return await show_group_picker(event, "sc", 0)
        return await start_new_sched(event, event.chat_id)
    if action == "gp":
        return await show_group_picker(event, "sc", int(arg or 0))
    if action == "pick":
        return await start_new_sched(event, int(arg))
    if action == "l":
        text, buttons = sched_list_view(chat_filter, int(arg or 0), private)
        return await cb_edit(event, text, buttons)

    sid = arg
    s = db["schedules"].get(sid)
    if not s or not (private or str(s["chat_id"]) == str(event.chat_id)):
        await event.answer("❌ هذه الجدولة غير موجودة.", alert=True)
        text, buttons = sched_list_view(chat_filter, 0, private)
        return await cb_edit(event, text, buttons)

    back = [[Button.inline("🔙 إلغاء", f"sc:v:{sid}".encode())]]
    if action == "v":
        text, buttons = sched_detail_view(sid)
        await cb_edit(event, text, buttons)
    elif action == "et":
        await begin_flow(event, "sc_et", "⏰ أرسل الوقت/الأوقات الجديدة:\nمثال: 7 صباحا — 19:30 — 7 صباحا و7 مساء", back, sid=sid)
    elif action == "er":
        await begin_flow(event, "sc_er", SC_REC_EDIT_PROMPT, back, sid=sid)
    elif action == "ec":
        await begin_flow(event, "sc_ec", "📝 أرسل المحتوى الجديد (نص أو صورة/فيديو مع كابشن):", back, sid=sid)
    elif action == "d":
        await cb_edit(
            event, "⚠️ متأكد تبي تحذف هذي الجدولة؟",
            [[Button.inline("✅ نعم، احذف", f"sc:dok:{sid}".encode()),
              Button.inline("❌ لا", f"sc:v:{sid}".encode())]],
        )
    elif action == "dok":
        stop_schedule_task(sid)
        remove_media_file(s.get("content"))
        db["schedules"].pop(sid, None)
        save_db()
        await event.answer("🗑️ تم حذف الجدولة.")
        text, buttons = sched_list_view(chat_filter, 0, private)
        await cb_edit(event, text, buttons)


async def flow_sc_new(event, f):
    text = (event.text or "").strip()
    step = f["step"]

    if step == "time":
        times = parse_times(text)
        if not times:
            return await flow_warn(f, "ما قدرت أفهم الوقت. جرّب مثلاً: 7 صباحا — 19:30 — 7 صباحا و7 مساء")
        f["times"] = times
        f["step"] = "recurrence"
        return await flow_show(f, SC_REC_PROMPT, SC_REC_BUTTONS)

    if step == "recurrence":
        f["recurrence"] = {"type": "daily"} if text in SKIP_WORDS else await parse_recurrence(text)
        f["step"] = "content"
        return await flow_show(f, SC_CONTENT_PROMPT, SC_CANCEL)

    content = await content_from_event(event, "sched")
    if not content:
        return await flow_warn(f, "أرسل نص الرسالة أو صورة/فيديو.")

    sid = new_id("s")
    db["schedules"][sid] = {
        "chat_id": f["target"],
        "times": f["times"],
        "recurrence": f["recurrence"],
        "content": content,
        "created_at": now_local().isoformat(),
        "created_by": event.sender_id,
    }
    save_db()
    start_schedule_task(sid)

    s = db["schedules"][sid]
    rows = [[Button.inline("📋 الرسائل المجدولة", b"sc:l:0"), Button.inline("➕ جدولة أخرى", b"sc:new")]]
    if event.is_private:
        rows.append([Button.inline("🏠 القائمة الرئيسية", b"dm:home")])
    await finish_flow_with_reply(
        event, f,
        f"✅ تم جدولة الرسالة بنجاح.\n👥 المجموعة: {group_title(s['chat_id'])}\n"
        f"⏰ الأوقات: {sched_times_str(s)}\n🔁 التكرار: {sched_rec_str(s)}",
        rows,
    )


async def flow_sc_edit(event, f):
    sid = f["sid"]
    s = db["schedules"].get(sid)
    if not s:
        flows.pop(event.sender_id, None)
        return await panel_edit(f, "❌ هذه الجدولة غير موجودة (ربما حُذفت).")
    text = (event.text or "").strip()

    if f["kind"] == "sc_et":
        times = parse_times(text)
        if not times:
            return await flow_warn(f, "ما قدرت أفهم الوقت. جرّب مثلاً: 7 صباحا — 19:30")
        s["times"] = times
    elif f["kind"] == "sc_er":
        s["recurrence"] = {"type": "daily"} if text in SKIP_WORDS else await parse_recurrence(text)
        s["created_at"] = now_local().isoformat()  # نقطة الانطلاق لحساب التكرار
    else:
        content = await content_from_event(event, "sched")
        if not content:
            return await flow_warn(f, "أرسل نص أو صورة/فيديو.")
        remove_media_file(s.get("content"))
        s["content"] = content

    save_db()
    start_schedule_task(sid)
    flows.pop(event.sender_id, None)
    detail, buttons = sched_detail_view(sid, "✅ تم التحديث\n\n")
    await panel_edit(f, detail, buttons)

# ══════════════════════════════════════════════════════════════════════════════
# القسم 14: رسالة فورية لمجموعة (من الخاص) + لوحة الخاص الرئيسية + المخوّلين
# ══════════════════════════════════════════════════════════════════════════════

MAIN_PANEL_TEXT = "🎛️ لوحة التحكم\nاختر ما تريد:"


def main_panel_keyboard(sender_id):
    rows = [
        [Button.inline("➕ جدولة رسالة جديدة", b"sc:new")],
        [Button.inline("📋 الرسائل المجدولة", b"sc:l:0")],
        [Button.inline("⚡ إرسال رسالة فورية", b"im:new")],
        [Button.inline("💬 إدارة الردود", b"rp:l:0")],
    ]
    if sender_id == owner_id:
        rows.append([Button.inline("👤 تعديل ملفات الأعضاء", b"pf:pick")])
    return rows


@client.on(events.NewMessage(pattern=r'(?i)^(?:/start(?:\s.*)?|/panel|/menu|لوحة|لوحه|القائمة|قائمة)$',
                             func=lambda e: e.is_private))
async def dm_main_panel(event):
    if not is_authorized_dm(event.sender_id):
        return await event.reply("⚠️ هذا البوت للإدارة فقط.")
    await event.reply(MAIN_PANEL_TEXT, buttons=main_panel_keyboard(event.sender_id), parse_mode=None)


@client.on(events.NewMessage(pattern=r'^رسالة$', func=lambda e: e.is_private))
async def dm_instant_menu(event):
    if not is_authorized_dm(event.sender_id):
        return await event.reply("⚠️ ما عندك صلاحية استخدام هذا الأمر من الخاص.")
    if not get_groups():
        return await event.reply(NO_GROUPS_TEXT)
    await event.reply("👥 اختر المجموعة التي تريد إرسال رسالة فورية فيها:",
                      buttons=groups_keyboard("im", 0), parse_mode=None)


@client.on(events.CallbackQuery(pattern=rb"^dm:([a-z]+)$"))
async def dm_callback(event):
    if not is_authorized_dm(event.sender_id):
        return await event.answer("⚠️ ما عندك صلاحية.", alert=True)
    flows.pop(event.sender_id, None)
    await cb_edit(event, MAIN_PANEL_TEXT, main_panel_keyboard(event.sender_id))


@client.on(events.CallbackQuery(pattern=rb"^im:([a-z]+)(?::(.*))?$"))
async def im_callback(event):
    if not is_authorized_dm(event.sender_id):
        return await event.answer("⚠️ ما عندك صلاحية.", alert=True)
    action = event.pattern_match.group(1).decode()
    arg = (event.pattern_match.group(2) or b"").decode()
    flows.pop(event.sender_id, None)

    if action == "new":
        await show_group_picker(event, "im", 0)
    elif action == "gp":
        await show_group_picker(event, "im", int(arg or 0))
    elif action == "pick":
        target = int(arg)
        await begin_flow(
            event, "im",
            f"👥 المجموعة: {group_title(target)}\n\n📝 أرسل الآن نص الرسالة، أو صورة/فيديو (مع كابشن اختياري) "
            "وسيتم إرسالها فوراً.",
            [[Button.inline("❌ إلغاء", b"dm:home")]], target=target,
        )


async def flow_im(event, f):
    target = f["target"]
    text = (event.text or "").strip()
    try:
        if event.photo or event.video or event.gif:
            await client.send_file(target, event.media, caption=text or None)
        elif text:
            await client.send_message(target, text)
        else:
            return await flow_warn(f, "أرسل نص الرسالة أو صورة/فيديو.")
    except Exception as e:
        return await finish_flow_with_reply(event, f, f"❌ فشل إرسال الرسالة: {e}",
                                            [[Button.inline("🏠 القائمة الرئيسية", b"dm:home")]])
    await finish_flow_with_reply(
        event, f, f"✅ تم إرسال الرسالة إلى «{group_title(target)}».",
        [[Button.inline("⚡ رسالة أخرى", b"im:new")], [Button.inline("🏠 القائمة الرئيسية", b"dm:home")]],
    )


# -------- إدارة القائمة المخوّلة (للأونر فقط) -------- #

@client.on(events.NewMessage(pattern=r'(?i)^اضافة\s+(\d+)$|^إضافة\s+(\d+)$', func=lambda e: e.is_private))
async def add_authorized_user(event):
    if event.sender_id != owner_id:
        return
    new_id_ = int(event.pattern_match.group(1) or event.pattern_match.group(2))
    if new_id_ == owner_id:
        return await event.reply("ℹ️ أنت الأونر بالفعل، عندك كل الصلاحيات.")
    if new_id_ in db["authorized_users"]:
        return await event.reply("ℹ️ هذا المعرف مخوّل بالفعل.")
    db["authorized_users"].append(new_id_)
    save_db()
    await event.reply(f"✅ تمت إضافة {new_id_} للقائمة المخوّلة بأوامر الجدولة/الرسالة من الخاص.")


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
        return await event.reply("📋 لا يوجد أشخاص مخوّلون حالياً (بالإضافة للأونر).\nلإضافة أحد، اكتب: إضافة <ID>")
    lines = ["📋 القائمة المخوّلة بأوامر الخاص:\n"] + [f"• {uid}" for uid in authorized]
    lines.append("\nلإضافة: إضافة <ID>\nللحذف: حذف مخول <ID>")
    await event.reply("\n".join(lines))

# ══════════════════════════════════════════════════════════════════════════════
# القسم 15: الملف الشخصي (أمر "ا") + تعديل كل الحقول للمالك
# ══════════════════════════════════════════════════════════════════════════════

PROFILE_FIELDS = {
    "name": "📝 الاسم",
    "id": "🆔 الآيدي",
    "msgs": "💬 عدد الرسائل",
    "rank": "🎖️ الرتبة",
    "join": "📅 تاريخ الانضمام",
    "dur": "⏳ مدة العضوية",
}

# رتب الأعضاء العاديين حسب عدد الرسائل (عدّلها كما تحب): (الحد الأدنى, اللقب)
RANK_TIERS = [
    (3000, "👑 أسطورة"),
    (1000, "💎 عضو مميز"),
    (300, "🔥 متفاعل"),
    (50, "⭐ عضو نشيط"),
    (0, "🌱 عضو جديد"),
]

_member_cache = {}
MEMBER_CACHE_TTL = 300


def format_duration(start, end=None):
    end = end or now_local()
    if start >= end:
        return "أقل من يوم"
    years, months, days = end.year - start.year, end.month - start.month, end.day - start.day
    if days < 0:
        months -= 1
        days += (end.replace(day=1) - datetime.timedelta(days=1)).day
    if months < 0:
        years -= 1
        months += 12
    parts = []
    if years:
        parts.append(f"{years} سنة")
    if months:
        parts.append(f"{months} شهر")
    if days:
        parts.append(f"{days} يوم")
    return " و".join(parts) or "أقل من يوم"


def parse_date_text(s):
    m = re.search(r'(\d{4})\D(\d{1,2})\D(\d{1,2})', normalize_text(s))
    if not m:
        return None
    try:
        return datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


async def get_member_info(chat_id, user_id):
    key = (chat_id, user_id)
    now = time.monotonic()
    c = _member_cache.get(key)
    if c and c[1] > now:
        return c[0]
    info = {"role": "member", "title": None, "join_dt": None}
    try:
        perms = await client.get_permissions(chat_id, user_id)
        part = getattr(perms, "participant", None)
        if perms.is_creator:
            info["role"] = "creator"
        elif perms.is_admin:
            info["role"] = "admin"
        info["title"] = getattr(part, "rank", None)
        d = getattr(part, "date", None)
        if d:
            info["join_dt"] = to_local_naive(d)
    except Exception as e:
        print(f"Member info error: {e}")
    _member_cache[key] = (info, now + MEMBER_CACHE_TTL)
    return info


def compute_rank(uid, info, count):
    if uid == owner_id:
        return "👑 المالك"
    if info["role"] == "creator":
        return "👑 مالك المجموعة"
    if info["role"] == "admin":
        return "🛡️ " + (info["title"] or "مشرف")
    for threshold, label in RANK_TIERS:
        if count >= threshold:
            return label
    return RANK_TIERS[-1][1]


async def build_profile_text(chat_id, user, private=False):
    uid = user.id
    ov = db["profile_overrides"].get(str(uid), {})
    count = int(db["stats"].get(str(uid), 0) or 0)
    info = {"role": "member", "title": None, "join_dt": None} if private else await get_member_info(chat_id, uid)

    join_dt = info["join_dt"]
    if not join_dt:
        fs = db["first_seen"].get(f"{chat_id}:{uid}")
        if fs:
            try:
                join_dt = datetime.datetime.fromisoformat(fs)
            except Exception:
                join_dt = None

    if ov.get("join"):
        join_text = ov["join"]
        dur_dt = parse_date_text(ov["join"]) or join_dt
    else:
        join_text = join_dt.strftime("%Y-%m-%d") if join_dt else "غير معروف"
        dur_dt = join_dt
    duration = ov.get("dur") or (format_duration(dur_dt) if dur_dt else "غير معروف")

    return (
        "👤 معلومات العضو\n\n"
        f"📝 الاسم: {ov.get('name') or full_name(user)}\n"
        f"🆔 الآيدي: {ov.get('id') or uid}\n"
        f"💬 عدد رسائلك: {count}\n"
        f"🎖️ رتبتك: {ov.get('rank') or compute_rank(uid, info, count)}\n"
        f"📅 تاريخ انضمامك: {join_text}\n"
        f"⏳ مدة عضويتك: {duration}"
    )


async def send_profile(event):
    target = await event.get_sender()
    if event.is_reply:  # الرد بـ "ا" على رسالة شخص يعرض ملفه
        try:
            rm = await event.get_reply_message()
            rs = await rm.get_sender() if rm else None
            if rs:
                target = rs
        except Exception:
            pass
    if not target:
        return

    caption = await build_profile_text(event.chat_id, target, private=event.is_private)
    buttons = ([[Button.inline("✏️ تعديل (للمالك)", f"pf:e:{target.id}".encode())]]
               if event.sender_id == owner_id else None)
    photo = await get_profile_photo(target)
    try:
        if photo:
            await client.send_file(event.chat_id, photo, caption=caption, reply_to=event.id,
                                   buttons=buttons, parse_mode=None)
        else:
            await event.reply(caption, buttons=buttons, parse_mode=None)
    except Exception as e:
        print(f"Profile send error: {e}")
        try:
            await event.reply(caption, parse_mode=None)
        except Exception:
            pass


# ---------- لوحة تعديل الملف (للمالك فقط، بالخاص أو بالمجموعة) ----------

def profile_panel(uid, name=None, notice="", private=False):
    ov = db["profile_overrides"].get(str(uid), {})
    lines = [notice + "🛠️ تعديل ملف العضو", f"🆔 {uid}" + (f" — {name}" if name else ""), ""]
    lines.append(f"💬 عدد الرسائل الحالي: {db['stats'].get(str(uid), 0)}")
    changed = [f"• {PROFILE_FIELDS[k]}: {v}" for k, v in ov.items() if k in PROFILE_FIELDS]
    if changed:
        lines.append("\nالقيم المعدّلة يدوياً:")
        lines.extend(changed)
    lines.append("\nاختر الحقل المراد تعديله:")

    def b(field):
        return Button.inline(PROFILE_FIELDS[field], f"pf:f:{field}:{uid}".encode())

    rows = [[b("name"), b("id")], [b("msgs"), b("rank")], [b("join"), b("dur")],
            [Button.inline("♻️ إرجاع الكل للتلقائي", f"pf:ra:{uid}".encode())]]
    rows.append([Button.inline("🏠 القائمة الرئيسية", b"dm:home")] if private
                else [Button.inline("❌ إغلاق", b"pf:x")])
    return "\n".join(lines), rows


async def resolve_user(raw):
    raw = normalize_text(raw or "").strip()
    m = re.search(r'tg://user\?id=(\d+)', raw) or re.fullmatch(r'(\d{5,})', raw)
    try:
        if m:
            uid = int(m.group(1))
            try:
                return uid, full_name(await client.get_entity(uid))
            except Exception:
                return uid, None
        uname = raw.lstrip('@')
        if not re.fullmatch(r'\w{4,32}', uname):
            return None, None
        ent = await client.get_entity(uname)
        return ent.id, full_name(ent)
    except Exception:
        return None, None


@client.on(events.NewMessage(pattern=r'^تعديل ملف(?:\s+(.+))?$'))
async def edit_profile_cmd(event):
    if event.sender_id != owner_id:
        return
    uid = name = None
    if event.is_reply:
        rm = await event.get_reply_message()
        if rm and rm.sender_id:
            uid = rm.sender_id
            try:
                name = full_name(await rm.get_sender())
            except Exception:
                pass
    elif event.pattern_match.group(1):
        uid, name = await resolve_user(event.pattern_match.group(1))
    if not uid:
        return await event.reply("↩️ رد على رسالة العضو واكتب: تعديل ملف\nأو اكتب: تعديل ملف @username (أو الآيدي)")
    text, buttons = profile_panel(uid, name, private=event.is_private)
    await event.reply(text, buttons=buttons, parse_mode=None)


@client.on(events.CallbackQuery(pattern=rb"^pf:([a-z]+)(?::(.*))?$"))
async def pf_callback(event):
    if event.sender_id != owner_id:
        return await event.answer("⚠️ هذا الخيار للمالك فقط.", alert=True)
    action = event.pattern_match.group(1).decode()
    arg = (event.pattern_match.group(2) or b"").decode()
    private = event.is_private
    flows.pop(event.sender_id, None)

    if action == "x":
        try:
            await event.delete()
        except Exception:
            pass
        return
    if action == "pick":
        return await begin_flow(
            event, "pf_pick", "👤 أرسل آيدي العضو (رقم) أو يوزره (@username):",
            [[Button.inline("🔙 رجوع", b"dm:home")]],
        )
    if action == "e":  # من زر تحت رسالة البروفايل: نفتح اللوحة برسالة جديدة
        uid = int(arg)
        text, buttons = profile_panel(uid, private=private)
        await event.answer()
        return await event.respond(text, buttons=buttons, parse_mode=None)

    if action in ("b", "ra"):
        uid = int(arg)
        notice = ""
        if action == "ra":
            db["profile_overrides"].pop(str(uid), None)
            save_db()
            notice = "♻️ تم إرجاع كل الحقول للتلقائي\n\n"
        text, buttons = profile_panel(uid, notice=notice, private=private)
        return await cb_edit(event, text, buttons)

    field, uid = arg.split(":", 1)
    uid = int(uid)
    if field not in PROFILE_FIELDS:
        return await event.answer()

    if action == "r":
        db["profile_overrides"].get(str(uid), {}).pop(field, None)
        save_db()
        text, buttons = profile_panel(uid, notice="♻️ تم الإرجاع للتلقائي\n\n", private=private)
        return await cb_edit(event, text, buttons)

    if action == "f":
        if field == "msgs":
            cur = db["stats"].get(str(uid), 0)
            hint = "أرسل رقم فقط."
        else:
            cur = db["profile_overrides"].get(str(uid), {}).get(field) or "تلقائي"
            hint = "للتاريخ استخدم صيغة 2024-05-17 وتنحسب المدة تلقائياً." if field == "join" else ""
        buttons = []
        if field != "msgs":
            buttons.append([Button.inline("♻️ إرجاع للتلقائي", f"pf:r:{field}:{uid}".encode())])
        buttons.append([Button.inline("🔙 رجوع", f"pf:b:{uid}".encode())])
        await begin_flow(
            event, "pf_edit",
            f"✏️ تعديل {PROFILE_FIELDS[field]}\nالقيمة الحالية: {cur}\n\nأرسل القيمة الجديدة:" + (f"\n{hint}" if hint else ""),
            buttons, uid=uid, field=field,
        )


async def flow_pf_pick(event, f):
    uid, name = await resolve_user(event.text or "")
    if not uid:
        return await flow_warn(f, "ما قدرت ألقى العضو. أرسل آيدي رقمي أو @username.")
    flows.pop(event.sender_id, None)
    text, buttons = profile_panel(uid, name, private=f["chat_id"] > 0)
    await panel_edit(f, text, buttons)


async def flow_pf_edit(event, f):
    uid, field = f["uid"], f["field"]
    value = (event.text or "").strip()
    if not value:
        return await flow_warn(f, "أرسل القيمة نصاً.")
    if field == "msgs":
        digits = normalize_text(value)
        if not digits.isdigit():
            return await flow_warn(f, "لازم رقم فقط.")
        db["stats"][str(uid)] = int(digits)
    else:
        db["profile_overrides"].setdefault(str(uid), {})[field] = value[:100]
    save_db()
    flows.pop(event.sender_id, None)
    text, buttons = profile_panel(uid, notice="✅ تم التحديث\n\n", private=f["chat_id"] > 0)
    await panel_edit(f, text, buttons)

# ══════════════════════════════════════════════════════════════════════════════
# القسم 16: المعالج العام (عدّاد الرسائل + "ا" + الردود التلقائية)
# ══════════════════════════════════════════════════════════════════════════════

FLOW_HANDLERS.update({
    "sc_new": flow_sc_new, "sc_et": flow_sc_edit, "sc_er": flow_sc_edit, "sc_ec": flow_sc_edit,
    "rp_add": flow_rp_add, "rp_ec": flow_rp_edit, "rp_ek": flow_rp_edit,
    "pf_pick": flow_pf_pick, "pf_edit": flow_pf_edit, "im": flow_im,
})

IGNORED_PREFIXES = (
    'رد ', 'حذف', 'تعديل رسائل', 'تعديل ملف', 'all', 'كتم', 'انذار', 'الغاء كتم', 'جدولة',
    'اضف رد', 'أضف رد', 'اضافة رد', 'إضافة رد', 'الردود', 'قائمة الردود',
)


@client.on(events.NewMessage)
async def global_handler(event):
    if not event.text or event.out:
        return
    if get_flow(event.sender_id, event.chat_id):
        return
    text = event.text.strip()

    if not event.is_private and not text.startswith(IGNORED_PREFIXES):
        uid = str(event.sender_id)
        db["stats"][uid] = db["stats"].get(uid, 0) + 1
        mark_dirty()

    if text == "ا":
        return await send_profile(event)

    content = reply_lookup.get(text)
    if content is not None:
        try:
            await send_content(event.chat_id, content, reply_to=event.id)  # يرد بمنشن (ريبلاي) على رسالته
        except Exception as e:
            print(f"Auto-reply error ({text}): {e}")

# ══════════════════════════════════════════════════════════════════════════════
# القسم 17: تشغيل البوت
# ══════════════════════════════════════════════════════════════════════════════


async def on_startup():
    await get_bot_id()
    restart_all_schedules()
    asyncio.create_task(autosave_loop())
    if LOST_MEDIA_WORDS:
        words = "، ".join(LOST_MEDIA_WORDS[:30])
        try:
            await client.send_message(
                owner_id,
                "⚠️ ردود الوسائط (صور/فيديو) القديمة لم تكن تُحفظ بشكل صحيح بالنسخة السابقة، "
                f"لذلك ما قدرت أسترجعها. أعد إضافتها بـ «اضف رد»:\n{words}",
            )
        except Exception:
            pass
        LOST_MEDIA_WORDS.clear()
        save_db()


print("🚀 البوت يعمل الآن...")
print(f"📁 مجلد البيانات: {DATA_DIR}")
client.loop.run_until_complete(on_startup())
try:
    client.run_until_disconnected()
finally:
    save_db()
