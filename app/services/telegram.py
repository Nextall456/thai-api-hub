"""Telegram notification service สำหรับแจ้งเตือนแอดมิน"""
import httpx

from .. import config


def _enabled() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


async def send_telegram(text: str, parse_mode: str = "HTML") -> bool:
    """ส่งข้อความไป Telegram คืน True/False"""
    if not _enabled():
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "parse_mode": parse_mode},
            )
        return r.status_code == 200
    except Exception:
        return False


def _fmt_new_user(user: dict, plan: str) -> str:
    return (
        f"👤 <b>สมาชิกใหม่</b>\n"
        f"📧 {user['email']}\n"
        f"👤 {user.get('name') or '-'}\n"
        f"📦 แพ็กเกจ: {plan}\n"
        f"🆔 User ID: {user['id']}"
    )


def _fmt_payment_notify(pay: dict, user_email: str, plan_name: str) -> str:
    return (
        f"💰 <b>แจ้งชำระเงินใหม่</b>\n"
        f"👤 {user_email}\n"
        f"📦 {plan_name} ({pay['billing_period'] == 'year' and 'รายปี' or 'รายเดือน'})\n"
        f"💵 ฿{pay['amount_thb']:,.2f}\n"
        f"🔖 Ref: <code>{pay['ref_code']}</code>\n"
        f"📝 หมายเหตุ: {pay.get('note') or '-'}"
    )


def _fmt_payment_verified(pay: dict, user_email: str, plan_name: str, auto: bool) -> str:
    mode = "อัตโนมัติ" if auto else "แอดมิน"
    return (
        f"✅ <b>อนุมัติชำระเงิน ({mode})</b>\n"
        f"👤 {user_email}\n"
        f"📦 {plan_name} ({pay['billing_period'] == 'year' and 'รายปี' or 'รายเดือน'})\n"
        f"💵 ฿{pay['amount_thb']:,.2f}\n"
        f"🔖 Ref: <code>{pay['ref_code']}</code>"
    )


def _fmt_payment_rejected(pay: dict, user_email: str, plan_name: str) -> str:
    return (
        f"❌ <b>ปฏิเสธการชำระเงิน</b>\n"
        f"👤 {user_email}\n"
        f"📦 {plan_name}\n"
        f"💵 ฿{pay['amount_thb']:,.2f}\n"
        f"🔖 Ref: <code>{pay['ref_code']}</code>"
    )


def _fmt_error(err: str, context: str = "") -> str:
    ctx = f" ({context})" if context else ""
    return f"🚨 <b>ข้อผิดพลาด{ctx}</b>\n<pre>{err}</pre>"


# async wrappers สำหรับเรียกจาก async context
async def notify_new_user(user: dict, plan: str) -> bool:
    return await send_telegram(_fmt_new_user(user, plan))


async def notify_payment_pending(pay: dict, user_email: str, plan_name: str) -> bool:
    return await send_telegram(_fmt_payment_notify(pay, user_email, plan_name))


async def notify_payment_verified(pay: dict, user_email: str, plan_name: str, auto: bool = False) -> bool:
    return await send_telegram(_fmt_payment_verified(pay, user_email, plan_name, auto))


async def notify_payment_rejected(pay: dict, user_email: str, plan_name: str) -> bool:
    return await send_telegram(_fmt_payment_rejected(pay, user_email, plan_name))


async def notify_error(error: str, context: str = "") -> bool:
    return await send_telegram(_fmt_error(error, context))