"""Email notifications (SMTP) + LINE Messaging API — ตั้งค่าใน .env เมื่อพร้อม"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx

from .. import config

log = logging.getLogger("tah.notify")


# ---------------- Email (SMTP) ----------------

def _email_enabled() -> bool:
    return all([config.SMTP_HOST, config.SMTP_USER, config.SMTP_PASSWORD, config.SMTP_FROM])


def send_email(to: str, subject: str, html: str) -> bool:
    """ส่งอีเมลธุรกรรม — คืน True/False (ไม่ throw เพื่อไม่กระทบ flow หลัก)"""
    if not _email_enabled() or not to:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = config.SMTP_FROM
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(config.SMTP_FROM, [to], msg.as_string())
        return True
    except Exception as e:
        log.warning("email send failed to %s: %s", to, e)
        return False


def _wrap(title: str, body_html: str) -> str:
    return (f'<div style="font-family:sans-serif;max-width:560px;margin:0 auto">'
            f'<div style="background:#0b132b;color:#fff;padding:18px 24px;border-radius:12px 12px 0 0">'
            f'<h2 style="margin:0">{title}</h2></div>'
            f'<div style="border:1px solid #e5e7eb;padding:24px;border-radius:0 0 12px 12px">{body_html}'
            f'<p style="color:#6b7280;font-size:12px;margin-top:20px">'
            f'อีเมลอัตโนมัติจาก {config.SITE_NAME} · '
            f'<a href="{config.SITE_URL}">{config.SITE_URL}</a></p></div></div>')


def email_welcome(to: str, name: str) -> bool:
    return send_email(to, f"ยินดีต้อนรับ {config.SITE_NAME}", _wrap(
        "สมัครสำเร็จ! 🎉",
        f"<p>สวัสดี {name or to},</p>"
        f"<p>คุณได้รับสิทธิ์ทดลองใช้ฟรี <b>{config.TRIAL_DAYS} วัน</b>"
        f' — สร้าง API Key แล้วเริ่มใช้งานได้เลย: <a href="{config.SITE_URL}/dashboard/keys">สร้างคีย์</a></p>'
        f'<p style="background:#f3f4f6;padding:12px;border-radius:8px">'
        f'Base URL: <code>{config.SITE_URL}/v1</code><br>Model: <code>thai-hub/auto</code></p>'))


def email_payment_verified(to: str, plan_name: str, amount: float, ends_at: str) -> bool:
    return send_email(to, "ชำระเงินสำเร็จ — เปิดใช้งานแล้ว", _wrap(
        "ชำระเงินสำเร็จ ✅",
        f"<p>แพ็กเกจ <b>{plan_name}</b> ยอด ฿{amount:,.2f} เปิดใช้งานแล้ว</p>"
        f"<p>ใช้งานได้ถึง <b>{ends_at}</b></p>"
        f'<p><a href="{config.SITE_URL}/dashboard" style="background:#2563eb;color:#fff;'
        f'padding:10px 18px;border-radius:8px;text-decoration:none">เข้าแดชบอร์ด</a></p>'))


def email_payment_pending(to: str, plan_name: str, amount: float, ref: str) -> bool:
    return send_email(to, "ได้รับแจ้งชำระเงิน — รอตรวจสอบ", _wrap(
        "รับแจ้งชำระเงินแล้ว ⏳",
        f"<p>แพ็กเกจ <b>{plan_name}</b> ยอด ฿{amount:,.2f}</p>"
        f"<p>รหัสอ้างอิง: <code>{ref}</code></p>"
        f"<p>ทีมงานจะตรวจสอบและเปิดใช้งานภายใน 1-24 ชม.</p>"))


# ---------------- LINE Messaging API ----------------

def _line_enabled() -> bool:
    return bool(config.LINE_CHANNEL_ACCESS_TOKEN)


def send_line_reply(user_id: str, text: str) -> bool:
    """ส่งข้อความ push ผ่าน LINE Messaging API (ต้องมี Channel Access Token)"""
    if not _line_enabled() or not user_id:
        return False
    try:
        r = httpx.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}",
                     "Content-Type": "application/json"},
            json={"to": user_id, "messages": [{"type": "text", "text": text[:5000]}]},
            timeout=15)
        return r.status_code == 200
    except Exception as e:
        log.warning("line push failed: %s", e)
        return False


def line_notify_admin(text: str) -> bool:
    """แจ้งเตือนแอดมินผ่าน LINE (ใช้ LINE_NOTIFY_TOKEN แบบเก่า หรือ push ไปยัง admin LINE userId)"""
    if config.LINE_ADMIN_USER_ID:
        return send_line_reply(config.LINE_ADMIN_USER_ID, text)
    return False
