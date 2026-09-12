"""Telegram Bot ฝ่ายขาย: ลูกค้าทักถาม → AI ตอบ + แจ้งเตือนแอดมินเมื่อมีคนสนใจ"""
import asyncio
import logging

import httpx

from .. import config, db
from . import telegram as tg
from .router_engine import run_chat

log = logging.getLogger("tah.bot")

SYSTEM_PROMPT = (
    "คุณคือ 'ฮับบอท' ผู้ช่วยฝ่ายขายของ Thai API Hub (เว็บขาย AI API รายเดือน/รายปีของไทย) "
    "ตอบภาษาไทยสั้น กระชับ เป็นกันเอง ไม่เกิน 6 ประโยคต่อครั้ง\n"
    "ข้อมูลสินค้า:\n"
    "- API เข้ากันได้ 100% กับ OpenAI SDK (เปลี่ยนแค่ base_url + api key)\n"
    "- แพ็กเกจ: ทดลองฟรี 7 วัน (30 คำขอ/วัน) | เริ่มต้น 199 บาท/เดือน (300 คำขอ/วัน) | "
    "โปร 499 บาท/เดือน (1,500 คำขอ/วัน เลือกโมเดลได้เอง) | ธุรกิจ 1,499 บาท/เดือน (10,000 คำขอ/วัน)\n"
    "- รายปีถูกกว่าเดือนละ ~2 เท่า (เช่น โปรรายปี 4,990 บาท)\n"
    "- ชำระผ่านโอนธนาคาร/สแกน QR จากหน้าบิล แจ้งชำระแล้วรออนุมัติ 1-24 ชม.\n"
    "- โมเดล: AI ในเครื่องฟรี + โมเดลฟรีคุณภาพสูง + โมเดลพรีเมียมราคาถูกจาก AI ระดับโลก "
    "(Llama 3.3, DeepSeek V3, Gemini Flash, GPT-4o-mini ฯลฯ) สลับให้อัตโนมัติ\n"
    "ถ้าลูกค้าถามนอกเรื่องสินค้า ให้ตอบสั้นๆ แล้วชวนกลับมาที่บริการ ถ้าไม่แน่ใจให้ชวนสมัครทดลองฟรี 7 วัน"
)

WELCOME = (
    "สวัสดีครับ 👋 ผมคือฮับบอท ผู้ช่วยฝ่ายขายของ Thai API Hub\n\n"
    "🌐 เว็บไซต์: " + "{}" + "\n"
    "📦 แพ็กเกจเริ่มต้น 199 บาท/เดือน หรือทดลองฟรี 7 วัน\n"
    "💳 ชำระผ่านโอนธนาคาร/QR\n\n"
    "พิมพ์คำถามได้เลยครับ เช่น\n"
    "• ราคาเท่าไหร่\n"
    "• ใช้กับโค้ด OpenAI เดิมได้ไหม\n"
    "• โมเดลอะไรบ้าง"
)


async def ai_reply(text: str) -> str:
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text[:2000]},
        ],
        "max_tokens": 400,
    }
    try:
        provider, _model, result, _latency, _attempts = await run_chat("thai-hub/auto", payload, False, None)
        content = result["choices"][0]["message"]["content"]
        return (content or "ขออภัย ผมตอบไม่ได้ตอนนี้ครับ").strip()[:3000]
    except Exception as e:
        log.warning("bot ai_reply failed: %s", e)
        return "ขออภัยครับ ระบบตอบคำถามขัดข้องชั่วคราว — ติดต่อแอดมินได้ที่อีเมลในหน้าเว็บครับ"


def _extract(update: dict):
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    return {
        "chat_id": chat.get("id"),
        "first_name": chat.get("first_name") or "",
        "last_name": chat.get("last_name") or "",
        "username": chat.get("username") or "",
        "text": (msg.get("text") or "").strip(),
    }


async def _is_new_chat(chat_id: int) -> bool:
    return not db.q("SELECT 1 FROM bot_chats WHERE chat_id=?", (chat_id,), one=True)


def _record_chat(m: dict) -> None:
    name = f"{m['first_name']} {m['last_name']}".strip() or m["username"] or str(m["chat_id"])
    now = db.now_str()
    db.x("INSERT INTO bot_chats(chat_id, name, username, msg_count, created_at, last_msg_at) "
         "VALUES(?,?,?,1,?,?) ON CONFLICT(chat_id) DO UPDATE SET "
         "msg_count=msg_count+1, last_msg_at=?, name=?",
         (m["chat_id"], name, m["username"], now, now, now, name))


async def _send(chat_id: int, text: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                         json={"chat_id": chat_id, "text": text[:4000]})
    except Exception as e:
        log.warning("bot send failed: %s", e)


async def _handle(update: dict) -> None:
    m = _extract(update)
    if not m["chat_id"] or not m["text"]:
        return
    # ข้อความจากแชทแอดมินเอง ไม่ต้องให้ AI ตอบ
    if str(m["chat_id"]) == config.TELEGRAM_CHAT_ID:
        return

    is_new = await _is_new_chat(m["chat_id"])
    _record_chat(m)

    if is_new:
        name = f"{m['first_name']} {m['last_name']}".strip() or m["username"] or str(m["chat_id"])
        await tg.send_telegram(
            f"🔔 <b>มีลูกค้าสนใจทักแชทบอท!</b>\n"
            f"👤 {name}" + (f" (@{m['username']})" if m["username"] else "") + "\n"
            f"💬 ข้อความแรก: {m['text'][:150]}")

    low = m["text"].lower()
    if low in ("/start", "/hello", "start"):
        await _send(m["chat_id"], WELCOME.format(config.SITE_URL))
        return
    if low in ("/pricing", "/price", "ราคา"):
        await _send(m["chat_id"],
                    "📦 แพ็กเกจ Thai API Hub\n"
                    "• ทดลองฟรี 7 วัน — 30 คำขอ/วัน\n"
                    "• เริ่มต้น 199.-/เดือน (รายปี 1,990.-)\n"
                    "• โปร 499.-/เดือน (รายปี 4,990.-) ⭐ ยอดนิยม\n"
                    "• ธุรกิจ 1,499.-/เดือน (รายปี 14,990.-)\n\n"
                    f"สมัครได้ที่ {config.SITE_URL}/signup")
        return
    if low in ("/help", "ช่วย"):
        await _send(m["chat_id"],
                    "วิธีเริ่มใช้งาน:\n"
                    f"1. สมัครฟรีที่ {config.SITE_URL}/signup\n"
                    "2. เข้าแดชบอร์ด → สร้าง API Key\n"
                    "3. โค้ดเดิมเปลี่ยนแค่ base_url กับ api_key\n"
                    f"4. อ่านเอกสารที่ {config.SITE_URL}/docs-api")
        return

    reply = await ai_reply(m["text"])
    await _send(m["chat_id"], reply)


async def run_polling() -> None:
    """วนรับข้อความจาก Telegram (long-polling) — รันเป็น background task ใน FastAPI"""
    if not config.TELEGRAM_BOT_TOKEN:
        return
    log.info("Telegram bot polling started | token_prefix=%s...", config.TELEGRAM_BOT_TOKEN[:10])
    offset = 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15)) as c:
        while True:
            try:
                r = await c.get(
                    f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates",
                    params={"offset": offset, "timeout": 50})
                if r.status_code in (401, 404):
                    log.error("Telegram bot token ไม่ถูกต้อง — หยุดบอท")
                    return
                updates = r.json().get("result", [])
                if updates:
                    log.info("poll got %d updates", len(updates))
                for upd in updates:
                    offset = upd["update_id"] + 1
                    try:
                        await _handle(upd)
                    except Exception as e:
                        log.warning("bot handle error: %s", e)
            except asyncio.CancelledError:
                log.info("Telegram bot stopped")
                return
            except Exception as e:
                log.warning("bot poll error: %s", e)
                await asyncio.sleep(5)
