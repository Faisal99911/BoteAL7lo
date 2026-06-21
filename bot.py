@client.on(events.NewMessage(pattern=r'(?i)^حذف\s+(?:ا|أ)خر\s*([\d٠-٩]+)\s*(?:رساله|رسالة|رسائل)\s*$'))
async def delete_last_n_messages(event):
    if not await is_admin(event): return
    if event.is_private: return

    # تحويل الأرقام إلى إنجليزية
    count_str = normalize_text(event.pattern_match.group(1))
    count = int(count_str)

    if count <= 0: 
        return await event.reply("⚠️ العدد يجب أن يكون أكبر من صفر.")

    count = min(count, 1000)
    chat_id = event.chat_id

    # إرسال رسالة جاري الحذف
    status_msg = await event.reply(f"🗑️ جاري حذف آخر {count} رسالة...")
    
    # نجمع معرفات الرسائل للحذف (ونبدأ برسالة الأمر نفسها)
    ids_to_delete = [event.id]

    try:
        # المحاولة بالطريقة الرسمية
        async for msg in client.iter_messages(chat_id, offset_id=event.id, limit=count):
            ids_to_delete.append(msg.id)
    except:
        # الحل البديل للجروبات العادية بالتخمين المتسلسل
        current_id = event.id
        for _ in range(count):
            current_id -= 1
            if current_id > 0:
                ids_to_delete.append(current_id)

    # تنفيذ الحذف الفعلي
    deleted_total = 0
    chunk_size = 100
    for i in range(0, len(ids_to_delete), chunk_size):
        chunk = ids_to_delete[i:i + chunk_size]
        try:
            await client.delete_messages(chat_id, chunk)
            deleted_total += len(chunk)
        except:
            pass
        await asyncio.sleep(0.3)

    # حذف رسالة "جاري الحذف" بعد الانتهاء
    try:
        await status_msg.delete()
    except:
        pass

    # إرسال رسالة التأكيد وحذفها تلقائياً بعد 3 ثواني
    try:
        confirm = await client.send_message(chat_id, f"✅ تم حذف الرسائل بنجاح.")
        await asyncio.sleep(3)
        await confirm.delete()
    except:
        pass
