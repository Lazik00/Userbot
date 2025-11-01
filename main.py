import os
import asyncio
import aiohttp
import json
from collections import deque
from pathlib import Path
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
OWNER_ID = int(os.getenv("OWNER_ID"))  # faqat shu IDga ruxsat

client = TelegramClient('session_name', API_ID, API_HASH)

# 📚 Foydalanuvchi kontekstini saqlash
user_contexts = {}

# 🌐 Global AI holati faylga saqlab qo'yamiz (restartdan keyin ham qoladi)
STATE_FILE = Path("ai_state.json")
state_lock = asyncio.Lock()

def load_state():
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return bool(data.get("ai_enabled", False))
        except Exception as e:
            print(f"[WARN] state fayl yuklanmadi: {e}")
    return False

async def save_state(enabled: bool):
    async with state_lock:
        try:
            STATE_FILE.write_text(json.dumps({"ai_enabled": bool(enabled)}), encoding="utf-8")
        except Exception as e:
            print(f"[ERROR] state fayl saqlanmadi: {e}")

AI_ENABLED = load_state()

# 🚀 OpenRouter API javob olish
async def get_openrouter_response(messages):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
    payload = {"model": OPENROUTER_MODEL, "messages": messages, "temperature": 0.7, "max_tokens": 600}
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=20)) as session:
            async with session.post(url, json=payload, headers=headers, timeout=15) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data['choices'][0]['message']['content']
    except Exception as e:
        print(f"[ERROR] OpenRouter API: {e}")
        return "🤖 AI javob olishda xatolik yuz berdi."

# 📩 Faqat shaxsiy chatlar uchun handler (global /on va /off faqat OWNER ga)
@client.on(events.NewMessage(incoming=True))
async def handler(event):
    global AI_ENABLED

    # faqat private chatlar
    if not event.is_private:
        return

    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False):
        return

    text = (event.message.message or "").strip()
    if not text:
        return

    user_id = event.sender_id

    # ---------- /on va /off komandalar (faqat OWNER_ID) ----------
    if text.lower() == "/on":
        if user_id != OWNER_ID:
            await event.reply("❌ Bu komandani faqat bot egasi ishlatishi mumkin.")
            return
        AI_ENABLED = True
        await save_state(AI_ENABLED)
        await event.reply("✅ Global AI holati: ON. Endi barcha private chatlar uchun AI javob beradi.")
        print("[INFO] AI turned ON by OWNER.")
        return

    if text.lower() == "/off":
        if user_id != OWNER_ID:
            await event.reply("❌ Bu komandani faqat bot egasi ishlatishi mumkin.")
            return
        AI_ENABLED = False
        await save_state(AI_ENABLED)
        await event.reply("⛔ Global AI holati: OFF. Endi hech kimga avtomatik javob berilmaydi.")
        print("[INFO] AI turned OFF by OWNER.")
        return

    # agar AI globalda o'chirilgan bo'lsa, javob bermaymiz
    if not AI_ENABLED:
        return

    # ---------- agar AI yoqilgan bo'lsa, oddiy xabarlarni qayta ishlash ----------
    # kontekstni yaratish
    if user_id not in user_contexts:
        user_contexts[user_id] = deque(maxlen=MAX_HISTORY)

    user_contexts[user_id].append({"role": "user", "content": text})

    try:
        messages = LAZIZ_PROMPT.copy()
        messages.extend(user_contexts[user_id])

        reply_text = await get_openrouter_response(messages)
        await event.reply(reply_text)

        # kontekstga AI javobini qo'shish
        user_contexts[user_id].append({"role": "assistant", "content": reply_text})
        print(f"[INFO] Javob berildi: {user_id}")

    except Exception as e:
        print(f"[ERROR] Xabarni qayta ishlashda xato: {e}")
        await event.reply("🤖 Xatolik yuz berdi, keyinroq urinib ko‘ring.")

# 🔥 Bot ishga tushishi
if __name__ == "__main__":
    print("[INFO] Telegram AI userbot ishga tushdi (global ON/OFF — faqat OWNER boshqaradi).")
    client.start()
    client.run_until_disconnected()
