import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
from pyrogram.enums import ParseMode, ChatMemberStatus
from pyrogram.errors import FloodWait, RPCError

# --- إعدادات البيانات الخاصة بك ---
API_ID = 34257542
API_HASH = "614a1b5c5b712ac6de5530d5c571c42a"
BOT_TOKEN = "7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw"
MY_USER_ID = 1486879970 

# ملفات البيانات
REPLIES_FILE = "auto_replies.json"
WARNS_FILE = "user_warns.json"
MEDIA_FILE = "media_replies.json"
MEDIA_INDEX_FILE = "media_index.json"

def load_data(file_path, default_value):
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            try: return json.load(f)
            except: return default_value
    return default_value

def save_data(file_path, data):
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e: print(f"Error saving data: {e}")

# تحميل البيانات
auto_replies = load_data(REPLIES_FILE, {"السلام عليكم": "وعليكم السلام"})
user_warns = load_data(WARNS_FILE, {})
media_replies = load_data(MEDIA_FILE, {})
media_indices = load_data(MEDIA_INDEX_FILE, {})

waiting_for_media = {}
active_mentions = set()

# إعداد البوت
app = Client(
    "mention_session_v16", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN,
    workers=100, 
    ipv6=False   
)

async def is_admin(client, user_id, chat_id):
    if user_id == MY_USER_ID: return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR]
    except: return False

# --- ميزة الإنذارات ---
@app.on_message(filters.command(["warn", "انذار"], prefixes=["", "/", "!"]) & filters.group)
async def warn_user(client, message):
    if not message.from_user or not await is_admin(client, message.from_user.id, message.chat.id):
        return await message.reply("للمشرفين فقط! 🚫")
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply("رد على رسالة الشخص! ⚠️")
    target = message.reply_to_message.from_user
    
    cid, uid = str(message.chat.id), str(target.id)
    if cid not in user_warns: user_warns[cid] = {}
    user_warns[cid][uid] = user_warns[cid].get(uid, 0) + 1
    save_data(WARNS_FILE, user_warns)

    if user_warns[cid][uid] >= 3:
        try:
            await client.restrict_chat_member(message.chat.id, target.id, ChatPermissions(can_send_messages=False), until_date=datetime.now() + timedelta(hours=2))
            user_warns[cid][uid] = 0
            save_data(WARNS_FILE, user_warns)
            await message.reply(f"تم كتم {target.first_name} لمدة ساعتين (3 إنذارات). 🚫")
        except: await message.reply("فشل الكتم! ❌")
    else:
        await message.reply(f"إنذار لـ {target.first_name} ({user_warns[cid][uid]}/3) ⚠️")

# --- ميزة الميديا والردود ---
@app.on_message(filters.regex(r"^(فيديو|صورة)\s*\((.*?)\)") & filters.group)
async def start_add_media(client, message):
    if not message.from_user or not await is_admin(client, message.from_user.id, message.chat.id): return
    m_type, name = ("video" if "فيديو" in message.text else "photo"), message.matches[0].group(2).strip()
    if name:
        waiting_for_media[message.from_user.id] = {"name": name, "type": m_type}
        await message.reply(f"أرسل ال{'فيديو' if m_type == 'video' else 'صورة'} الآن. 🔃")

@app.on_message((filters.video | filters.photo) & filters.group)
async def receive_media(client, message):
    uid = message.from_user.id if message.from_user else None
    if uid in waiting_for_media:
        info = waiting_for_media[uid]
        fid = message.video.file_id if info["type"] == "video" and message.video else message.photo.file_id if info["type"] == "photo" and message.photo else None
        if fid:
            if info["name"] not in media_replies: media_replies[info["name"]] = {"type": info["type"], "ids": []}
            media_replies[info["name"]]["ids"].append(fid)
            save_data(MEDIA_FILE, media_replies)
            del waiting_for_media[uid]
            await message.reply("تم ✅")

@app.on_message(filters.command("اضف رد", prefixes=["", "/", "!"]) & filters.group)
async def add_reply_cmd(client, message):
    if not message.from_user or not await is_admin(client, message.from_user.id, message.chat.id): return
    m = re.search(r"\((.*?)\)\s*\((.*?)\)", message.text, re.DOTALL)
    if m:
        word = m.group(1).strip()
        rep = m.group(2).strip()
        auto_replies[word] = rep
        save_data(REPLIES_FILE, auto_replies)
        await message.reply("تم ✅")

@app.on_message(filters.command("حذف رد", prefixes=["", "/", "!"]) & filters.group)
async def del_reply_cmd(client, message):
    if not message.from_user or not await is_admin(client, message.from_user.id, message.chat.id): return
    m = re.search(r"\((.*?)\)", message.text, re.DOTALL)
    if m:
        k = m.group(1).strip()
        
        # إذا كان ميديا (فيديو أو صورة) نعتبره تذكير
        if k in media_replies:
            del media_replies[k]
            save_data(MEDIA_FILE, media_replies)
            return await message.reply("تم حذف التذكير ✅")
        
        # إذا كان نص عادي نعتبره رد
        if k in auto_replies:
            del auto_replies[k]
            save_data(REPLIES_FILE, auto_replies)
            return await message.reply("حذف رد ✅")
            
        await message.reply("غير موجود! ❌")

# --- الردود التلقائية ---
@app.on_message(filters.text & filters.group, group=1)
async def auto_reply_handler(client, message):
    if not message.text: return
    t = message.text.strip()
    if t in auto_replies: await message.reply(auto_replies[t])
    elif t in media_replies:
        d = media_replies[t]
        ids = d["ids"]
        if ids:
            idx = media_indices.get(t, 0) % len(ids)
            try:
                if d["type"] == "video": await message.reply_video(ids[idx])
                else: await message.reply_photo(ids[idx])
                media_indices[t] = idx + 1
                save_data(MEDIA_INDEX_FILE, media_indices)
            except Exception: pass

# --- المنشن (all) ---
async def mention_task(client, chat_id, msg, members):
    for i in range(0, len(members), 5):
        if chat_id not in active_mentions: break
        try:
            await client.send_message(chat_id, " ".join(members[i:i+5]) + f"\n\n**{msg}**")
            await asyncio.sleep(4) 
        except FloodWait as e: await asyncio.sleep(e.value)
        except: break
    active_mentions.discard(chat_id)

@app.on_message(filters.command(["all", "mentionall"], prefixes=["", "/", "."]) & filters.group)
async def mentionall(client, message):
    if not message.from_user or not await is_admin(client, message.from_user.id, message.chat.id): return
    if message.chat.id in active_mentions: return await message.reply("جاري المنشن بالفعل! ⚠️")
    
    msg = message.text.split(None, 1)[1] if len(message.command) > 1 else "نداء للجميع! 📣"
    active_mentions.add(message.chat.id)
    
    members = []
    async for m in client.get_chat_members(message.chat.id):
        if m.user and not m.user.is_bot:
            members.append(f"@{m.user.username}" if m.user.username else f"[{m.user.first_name}](tg://user?id={m.user.id})")
    
    asyncio.create_task(mention_task(client, message.chat.id, msg, members))
    await message.reply(f"بدأ المنشن لـ {len(members)} عضو. ✅")

# --- التشغيل ---
if __name__ == "__main__":
    try:
        print("Bot v16 LIVE!")
        app.run()
    except KeyboardInterrupt:
        pass

