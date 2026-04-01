import os
import asyncio
import aiohttp
import json
import getpass
import ssl
from contextlib import suppress
from collections import deque
from io import StringIO
from pathlib import Path
from telethon import TelegramClient, events
from telethon.errors import (
    ApiIdInvalidError,
    AuthRestartError,
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeEmptyError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberFloodError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from dotenv import load_dotenv
from prompt import LAZIZ_PROMPT

try:
    import certifi
except ImportError:
    certifi = None

try:
    import qrcode
except ImportError:
    qrcode = None

# 🌿 Env faylni yuklaymiz
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
MAX_HISTORY = int(os.getenv("MAX_HISTORY", 10))
OPENROUTER_KEY = (os.getenv("OPENROUTER_KEY") or "").strip()
OPENROUTER_MODEL = "x-ai/grok-code-fast-1"
SESSION_NAME = os.getenv("SESSION_NAME", "session_name")

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# 📚 Foydalanuvchi kontekstini saqlash
user_contexts = {}

# 🌐 Global AI holati faylga saqlanadi (restartdan keyin ham qoladi)
STATE_FILE = Path("ai_state.json")
QR_FILE = Path("telegram_login_qr.png")
state_lock = asyncio.Lock()

def load_state():
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return bool(data.get("ai_enabled", False))
        except Exception as e:
            print(f"[WARN] State fayl yuklanmadi: {e}")
    return False

async def save_state(enabled: bool):
    async with state_lock:
        try:
            STATE_FILE.write_text(json.dumps({"ai_enabled": bool(enabled)}), encoding="utf-8")
        except Exception as e:
            print(f"[ERROR] State fayl saqlanmadi: {e}")

AI_ENABLED = load_state()

def build_ssl_context():
    cafile = os.getenv("SSL_CERT_FILE")
    if cafile:
        return ssl.create_default_context(cafile=cafile)
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()

def openrouter_key_hint():
    if not OPENROUTER_KEY:
        return "OPENROUTER_KEY topilmadi."
    if OPENROUTER_KEY.startswith("sk-proj-"):
        return "Joriy kalit `sk-proj-` bilan boshlanadi; bu OpenAI project key ko‘rinadi, OpenRouter key emas."
    return "OPENROUTER_KEY noto‘g‘ri, bekor qilingan yoki OpenRouter panelida cheklangan bo‘lishi mumkin."

def ask_login_method():
    choice = input("Login usulini tanlang: [qr/phone] (default: qr): ").strip().lower()
    return choice or "qr"

def print_qr_login_help(url):
    print("[INFO] QR login tanlandi.")
    print("[INFO] Telefoningizdagi rasmiy Telegram ilovasida Settings > Devices > Link Desktop Device bo‘limini oching.")
    if qrcode is not None:
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)

        buffer = StringIO()
        qr.print_ascii(out=buffer, tty=False, invert=True)
        print("[INFO] Quyidagi ASCII QR kodni ham skaner qilishingiz mumkin:")
        print(buffer.getvalue())

        image = qr.make_image(fill_color="black", back_color="white")
        image.save(QR_FILE)
        print(f"[INFO] QR rasm fayli yaratildi: {QR_FILE.resolve()}")
    else:
        print("[WARN] `qrcode` kutubxonasi topilmadi, shu sabab QR rasm chizilmadi.")

    print("[INFO] Quyidagi QR havolani zarurat bo‘lsa oching:")
    print(url)
    print("[INFO] QR tasdiqlangandan keyin bu terminal avtomatik davom etadi.")

def handle_password_error(exc):
    raise RuntimeError("2-bosqichli parol noto‘g‘ri.") from exc

async def complete_2fa_sign_in():
    password = getpass.getpass("2-bosqichli parolni kiriting: ").strip()
    if not password:
        raise RuntimeError("2-bosqichli parol kiritilmadi.")
    try:
        await client.sign_in(password=password)
    except PasswordHashInvalidError as exc:
        handle_password_error(exc)

async def authorize_via_qr():
    qr_login = await client.qr_login()
    print_qr_login_help(qr_login.url)
    try:
        await qr_login.wait()
    except SessionPasswordNeededError:
        await complete_2fa_sign_in()
    except asyncio.TimeoutError as exc:
        raise RuntimeError("QR login vaqti tugadi. Dasturini qayta ishga tushirib yangi QR oling.") from exc

    if not await client.is_user_authorized():
        raise RuntimeError("QR login yakunlanmadi. Telegram tasdiqlanmagan ko‘rinadi.")

    print("[INFO] QR login muvaffaqiyatli yakunlandi.")

def describe_code_delivery(sent_code):
    sent_type = type(sent_code.type).__name__
    next_type = getattr(sent_code, "next_type", None)
    next_type_name = type(next_type).__name__ if next_type else None
    timeout = getattr(sent_code, "timeout", None)
    length = getattr(sent_code.type, "length", None)

    messages = {
        "SentCodeTypeApp": "Kod Telegram ichidagi servis xabari sifatida boshqa login qilingan sessiyalarga yuborildi. 777000 chatini tekshiring.",
        "SentCodeTypeSms": "Kod SMS orqali yuborildi.",
        "SentCodeTypeFirebaseSms": "Telegram ushbu login uchun Firebase SMS oqimini tanladi. Bu usul odatda faqat rasmiy mobil Telegram ilovalarida ishlaydi.",
        "SentCodeTypeCall": "Kod telefon qo‘ng‘irog‘i orqali yuboriladi.",
        "SentCodeTypeFlashCall": "Kod flash-call usuli bilan yuboriladi.",
        "SentCodeTypeMissedCall": "Kod missed-call usuli bilan yuboriladi.",
        "SentCodeTypeEmailCode": "Kod email orqali yuborildi.",
        "SentCodeTypeFragmentSms": "Kod Fragment orqali yuborildi.",
        "SentCodeTypeSetUpEmailRequired": "Telegram loginni davom ettirish uchun email tasdiqlashni talab qildi.",
        "SentCodeTypeSmsWord": "Kod bitta so‘z ko‘rinishidagi SMS sifatida yuborildi.",
        "SentCodeTypeSmsPhrase": "Kod bir nechta so‘zli SMS ibora sifatida yuborildi.",
    }
    next_messages = {
        "CodeTypeSms": "SMS",
        "CodeTypeCall": "qo‘ng‘iroq",
        "CodeTypeFlashCall": "flash-call",
        "CodeTypeMissedCall": "missed-call",
        "CodeTypeFragmentSms": "Fragment",
        "CodeTypeEmailCode": "email",
        "CodeTypeSmsWord": "SMS word",
        "CodeTypeSmsPhrase": "SMS phrase",
    }

    details = [f"[INFO] {messages.get(sent_type, f'Kod yuborildi. Yetkazish turi: {sent_type}.')}"]

    if sent_type == "SentCodeTypeEmailCode":
        email_pattern = getattr(sent_code.type, "email_pattern", None)
        if email_pattern:
            details.append(f"[INFO] Email manzil namunasi: {email_pattern}")

    if sent_type == "SentCodeTypeFragmentSms":
        url = getattr(sent_code.type, "url", None)
        if url:
            details.append(f"[INFO] Fragment havolasi: {url}")

    if length:
        details.append(f"[INFO] Kutilayotgan kod uzunligi: {length}")

    if next_type_name and timeout:
        fallback = next_messages.get(next_type_name, next_type_name)
        details.append(f"[INFO] Agar kod {timeout} soniya ichida kelmasa, keyingi usul: {fallback}.")

    if sent_type == "SentCodeTypeFirebaseSms":
        details.append("[INFO] Third-party Telethon klientida SMS kelmasligi mumkin; rasmiy Telegram mobil ilovasini tekshiring.")

    return "\n".join(details)

async def request_login_code(phone):
    try:
        return await client.send_code_request(phone)
    except AuthRestartError:
        print("[WARN] Telegram auth jarayonini qayta boshlashni so‘radi. Kod so‘rovi qayta yuborilmoqda.")
        return await client.send_code_request(phone)

async def ensure_authorized():
    await client.connect()
    if await client.is_user_authorized():
        print("[INFO] Mavjud sessiya topildi. Qayta login talab qilinmadi.")
        return

    session_path = Path(f"{SESSION_NAME}.session")
    if session_path.exists():
        print(f"[WARN] {session_path.name} sessiya fayli topildi, lekin u hali avtorizatsiyalanmagan.")
        print("[WARN] Agar kod kelmasa yoki login osilib qolsa, shu sessiya faylini o‘chirib qayta urinib ko‘ring.")

    login_method = ask_login_method()
    if login_method == "qr":
        await authorize_via_qr()
        return
    if login_method not in {"phone", "sms", "code"}:
        raise RuntimeError("Login usuli noto‘g‘ri. `qr` yoki `phone` kiriting.")

    phone = input("Telefon raqamingizni xalqaro formatda kiriting (+998901234567): ").strip()
    if not phone:
        raise RuntimeError("Telefon raqami kiritilmadi.")

    try:
        sent_code = await request_login_code(phone)
    except ApiIdInvalidError as exc:
        raise RuntimeError("API_ID yoki API_HASH noto‘g‘ri. my.telegram.org dagi qiymatlarni tekshiring.") from exc
    except PhoneNumberInvalidError as exc:
        raise RuntimeError("Telefon raqami noto‘g‘ri formatda. Uni +998901234567 ko‘rinishida kiriting.") from exc
    except PhoneNumberBannedError as exc:
        raise RuntimeError("Bu telefon raqami Telegram tomonidan login uchun bloklangan.") from exc
    except PhoneNumberFloodError as exc:
        raise RuntimeError("Bu raqam bo‘yicha juda ko‘p login urinishlari bo‘lgan. Biroz kutib qayta urinib ko‘ring.") from exc
    except FloodWaitError as exc:
        raise RuntimeError(f"Telegram vaqtincha cheklov qo‘ydi. {exc.seconds} soniyadan keyin qayta urinib ko‘ring.") from exc

    print(describe_code_delivery(sent_code))

    if type(sent_code.type).__name__ == "SentCodeTypeSetUpEmailRequired":
        raise RuntimeError("Telegram bu akkaunt uchun avval email verifikatsiyasini yakunlashni talab qildi. Buni rasmiy ilovada bajaring.")

    code = input("Olingan kodni kiriting: ").strip()
    if not code:
        raise RuntimeError("Tasdiqlash kodi kiritilmadi.")

    try:
        await client.sign_in(phone=phone, code=code)
    except SessionPasswordNeededError:
        await complete_2fa_sign_in()
    except PhoneCodeEmptyError as exc:
        raise RuntimeError("Tasdiqlash kodi bo‘sh yuborildi.") from exc
    except PhoneCodeInvalidError as exc:
        raise RuntimeError("Tasdiqlash kodi noto‘g‘ri.") from exc
    except PhoneCodeExpiredError as exc:
        raise RuntimeError("Tasdiqlash kodi eskirib qolgan. Dasturini qayta ishga tushirib yangi kod so‘rang.") from exc

    if not await client.is_user_authorized():
        raise RuntimeError("Login yakunlanmadi. Sessiya hali avtorizatsiyalanmagan.")

    print("[INFO] Login muvaffaqiyatli yakunlandi.")

# 🚀 OpenRouter API javob olish
async def get_openrouter_response(messages):
    if not OPENROUTER_KEY:
        return "🤖 OPENROUTER_KEY sozlanmagan. `.env` ichiga haqiqiy OpenRouter API key yozing."

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
        timeout = aiohttp.ClientTimeout(total=20, connect=10)
        connector = aiohttp.TCPConnector(limit=20, ssl=build_ssl_context())
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 401:
                    body = await resp.text()
                    print(f"[ERROR] OpenRouter 401 Unauthorized: {body}")
                    return f"🤖 OpenRouter avtorizatsiyasi rad etildi. {openrouter_key_hint()}"
                if resp.status == 403:
                    body = await resp.text()
                    print(f"[ERROR] OpenRouter 403 Forbidden: {body}")
                    return "🤖 OpenRouter so‘rovi taqiqlandi. Hisob limitingiz, model ruxsatlari yoki billing holatini tekshiring."
                if resp.status >= 400:
                    body = await resp.text()
                    print(f"[ERROR] OpenRouter HTTP {resp.status}: {body}")
                    return f"🤖 OpenRouter {resp.status} xato qaytardi."

                data = await resp.json()
                return data['choices'][0]['message']['content']
    except aiohttp.ClientConnectorCertificateError as e:
        print(f"[ERROR] OpenRouter TLS sertifikati tekshiruvi yiqildi: {e}")
        return "🤖 OpenRouter bilan xavfsiz ulanish o‘rnatilmadi. `certifi` o‘rnatilganini va Python sertifikatlari yangilanganini tekshiring."
    except aiohttp.ClientError as e:
        print(f"[ERROR] OpenRouter tarmoq xatosi: {e}")
        return "🤖 OpenRouter serveriga ulanishda tarmoq xatosi yuz berdi."
    except Exception as e:
        print(f"[ERROR] OpenRouter API: {e}")
        return "🤖 AI javob olishda xatolik yuz berdi."

# 📩 Private chatlar uchun handler (AI holati har kim boshqarishi mumkin)
@client.on(events.NewMessage(incoming=True))
async def handler(event):
    global AI_ENABLED

    if not event.is_private:
        return

    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False):
        return

    text = (event.message.message or "").strip()
    if not text:
        return

    user_id = event.sender_id

    # ---------- /on va /off komandalar (har kim ishlatishi mumkin) ----------
    if text.lower() == "/on":
        AI_ENABLED = True
        await save_state(AI_ENABLED)
        await event.reply("✅ Global AI holati: ON. Endi barcha private chatlar uchun AI javob beradi.")
        print(f"[INFO] AI turned ON by user {user_id}.")
        return

    if text.lower() == "/off":
        AI_ENABLED = False
        await save_state(AI_ENABLED)
        await event.reply("⛔ Global AI holati: OFF. Endi hech kimga avtomatik javob berilmaydi.")
        print(f"[INFO] AI turned OFF by user {user_id}.")
        return

    # Agar AI globalda o'chirilgan bo'lsa, javob bermaymiz
    if not AI_ENABLED:
        return

    # ---------- Multi-turn xabarlarni qayta ishlash ----------
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

async def main():
    print("[INFO] Telegram AI userbot ishga tushdi (global ON/OFF — har kim boshqarishi mumkin).")
    try:
        await ensure_authorized()
        await client.run_until_disconnected()
    finally:
        with suppress(asyncio.CancelledError):
            await client.disconnect()

# 🔥 Bot ishga tushishi
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Dastur foydalanuvchi tomonidan to‘xtatildi.")
    except Exception as e:
        print(f"[ERROR] {e}")
