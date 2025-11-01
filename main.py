import os
import asyncio
import aiohttp
from collections import deque
from telethon import TelegramClient, events
from dotenv import load_dotenv
from prompt import LAZIZ_PROMPT

# 🌿 Env faylni yuklaymiz
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
MAX_HISTORY = int(os.getenv("MAX_HISTORY", 10))
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
OPENROUTER_MODEL = "x-ai/grok-code-fast-1"

client = TelegramClient('session_name', API_ID, API_HASH)

# 📚 Foydalanuvchi kontekstini saqlash
user_contexts = {}

# 🌐 Global AI holati
AI_ENABLED = False

# 🚀 OpenRouter API javob olish
async def get_openrouter_response(messages):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 600
    }
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=20)) as session:
            async with session.post(url, json=payload, headers=headers, timeout=15) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data['choices'][0]['message']['content']
    except Exception as e:
        print(f"[ERROR] OpenRouter API: {e}")
        return "🤖 AI javob olishda xatolik yuz berdi."

# 📩 Faqat shaxsiy chatlar uchun handler
@client.on(events.NewMessage(incoming=True))
async def handler(event):
    global AI_ENABLED

    if not event.is_private:
        return

    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False):
        return

    text = event.message.message
    if not text:
        return

    # 🔹 Buyruqlarni tekshirish
    if text.lower() == "/on":
        AI_ENABLED = True
        await event.reply("🤖 AI endi barcha private chatlarda ishlaydi.")
        return
    elif text.lower() == "/off":
        AI_ENABLED = False
        await event.reply("🤖 AI barcha private chatlarda to‘xtatildi.")
        return

    # Agar AI yoqilmagan bo‘lsa, javob bermaymiz
    if not AI_ENABLED:
        return

    user_id = event.sender_id
    if user_id not in user_contexts:
        user_contexts[user_id] = deque(maxlen=MAX_HISTORY)

    user_contexts[user_id].append({"role": "user", "content": text})

    try:
        messages = LAZIZ_PROMPT.copy()
        messages.extend(user_contexts[user_id])

        reply_text = await get_openrouter_response(messages)
        await event.reply(reply_text)

        user_contexts[user_id].append({"role": "assistant", "content": reply_text})

        print(f"[INFO] Javob berildi: {user_id}")

    except Exception as e:
        print(f"[ERROR] Xabarni qayta ishlashda xato: {e}")
        await event.reply("🤖 Xatolik yuz berdi, keyinroq urinib ko‘ring.")

# 🔥 Bot ishga tushishi
if __name__ == "__main__":
    print("[INFO] Telegram AI userbot ishga tushdi (lichniy chatlar, OpenRouter + multi-turn)...")
    client.start()
    client.run_until_disconnected()
