# -*- coding: utf-8 -*-

import asyncio
import datetime
import json
from telethon import TelegramClient, events
from functools import wraps

# ===== إعداداتك (لم يتم التعديل عليها) =====
API_ID = 34257542
API_HASH = '614a1b5c5b712ac6de5530d5c571c42a'
BOT_TOKEN = '7957660443:AAFOZTMcDv-eg9mKLtkvK01Trv-zzRQbwWw'
OWNER_ID = 1486879970

# ===== ملفات =====
AUTO_REPLIES_FILE = 'auto_replies.json'

client = TelegramClient('activity_session', API_ID, API_HASH)

# ===== بيانات =====
auto_replies = {}
last_added_reply = None


# ===== تحميل / حفظ =====
async def load_data():
    global auto_replies
    try:
        with open(AUTO_REPLIES_FILE, 'r', encoding='utf-8') as f:
            auto_replies = json.load(f)
    except:
        auto_replies = {}


async def save_data():
    with open(AUTO_REPLIES_FILE, 'w', encoding='utf-8') as f:
        json.dump(auto_replies, f, ensure_ascii=False, indent=4)


# ===== صلاحية المالك =====
def owner_only(func):
    @wraps(func)
    async def wrapper(event):
        if event.sender_id == OWNER_ID:
            return await func(event)
        else:
            return await event.reply("❌ للمالك فقط")
    return wrapper


# =====================================================
# ✅ 1. إضافة رد (نص / صورة / فيديو)
# =====================================================
@client.on(events.NewMessage(pattern=r'^رد (.+)'))
@owner_only
async def add_reply(event):
    global last_added_reply

    trigger = event.pattern_match.group(1).strip()

    if not event.is_reply:
        return await event.reply("❌ لازم ترد على رسالة")

    reply_msg = await event.get_reply_message()

    if reply_msg.video:
        auto_replies[trigger] = {
            "type": "video",
            "data": reply_msg.video.id
        }

    elif reply_msg.photo:
        auto_replies[trigger] = {
            "type": "photo",
            "data": reply_msg.photo.id
        }

    elif reply_msg.text:
        auto_replies[trigger] = {
            "type": "text",
            "data": reply_msg.text
        }

    else:
        return await event.reply("❌ نوع غير مدعوم")

    last_added_reply = trigger
    await save_data()

    await event.reply(f"✅ تم ربط الرد بـ: {trigger}")


# =====================================================
# ✅ 2. حذف بالريبلاي (يحذف الرد + الرسائل)
# =====================================================
@client.on(events.NewMessage(pattern=r'^حذف$'))
@owner_only
async def delete_reply(event):
    global last_added_reply

    if not event.is_reply:
        return await event.reply("❌ لازم ترد على رسالة البوت")

    if last_added_reply and last_added_reply in auto_replies:
        del auto_replies[last_added_reply]
        await save_data()

        # حذف رسالة الأمر + رسالة البوت
        reply_msg = await event.get_reply_message()
        await reply_msg.delete()
        await event.delete()

        return

    await event.reply("❌ ما فيه رد ينحذف")


# =====================================================
# ✅ 3. الرد التلقائي
# =====================================================
@client.on(events.NewMessage)
async def auto_reply_handler(event):
    if event.is_private:
        return

    if not event.text:
        return

    text = event.text.strip()

    # ===== الردود =====
    if text in auto_replies:
        data = auto_replies[text]

        if data["type"] == "text":
            await event.reply(data["data"])

        elif data["type"] in ["photo", "video"]:
            await client.send_file(
                event.chat_id,
                data["data"],
                reply_to=event.id
            )

    # ===== منشن all =====
    if "all" in text.lower():
        participants = await client.get_participants(event.chat_id)

        mentions = []
        for user in participants:
            if user.bot:
                continue
            mentions.append(f"[{user.first_name}](tg://user?id={user.id})")

        message = text.replace("all", "").strip()
        final = f"{message}\n\n" + " ".join(mentions)

        await event.reply(final, parse_mode="md")


# =====================================================
# ✅ تشغيل
# =====================================================
async def main():
    await load_data()
    await client.start(bot_token=BOT_TOKEN)
    print("✅ البوت شغال")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
