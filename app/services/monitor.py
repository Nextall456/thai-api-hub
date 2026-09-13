"""Metrics endpoint (Prometheus format) + Daily Report + Backup"""
import asyncio
import logging
import time
from datetime import datetime, timedelta

import httpx

from .. import config, db

log = logging.getLogger("tah.monitor")

_fallback = {
    "requests_total": 0, "errors_total": 0, "tokens_month": 0,
    "users_total": 0, "subs_active": 0, "revenue_total": 0.0,
    "pending_payments": 0, "bot_chats": 0, "last_updated": "",
}


def collect_stats() -> dict:
    """รวมสถิติทั้งระบบจาก DB (ใช้ทั้ง /metrics และรายงานประจำวัน)"""
    try:
        day_ago = (datetime.now() - timedelta(hours=24)).strftime(db.FMT)
        month_start = datetime.now().strftime("%Y-%m-01 00:00:00")
        return {
            "requests_24h": db.q("SELECT COUNT(*) c FROM usage_logs WHERE created_at>=?", (day_ago,), one=True)["c"],
            "requests_total": db.q("SELECT COUNT(*) c FROM usage_logs", one=True)["c"],
            "errors_24h": db.q("SELECT COUNT(*) c FROM usage_logs WHERE created_at>=? AND status!='ok'", (day_ago,), one=True)["c"],
            "errors_total": db.q("SELECT COUNT(*) c FROM usage_logs WHERE status!='ok'", one=True)["c"],
            "tokens_24h": db.q("SELECT COALESCE(SUM(prompt_tokens+completion_tokens),0) t FROM usage_logs WHERE created_at>=?", (day_ago,), one=True)["t"],
            "tokens_month": db.q("SELECT COALESCE(SUM(prompt_tokens+completion_tokens),0) t FROM usage_logs WHERE created_at>=?", (month_start,), one=True)["t"],
            "cost_month_usd": db.q("SELECT COALESCE(SUM(cost_usd),0) v FROM usage_logs WHERE created_at>=?", (month_start,), one=True)["v"],
            "users_total": db.q("SELECT COUNT(*) c FROM users", one=True)["c"],
            "users_new_24h": db.q("SELECT COUNT(*) c FROM users WHERE created_at>=?", (day_ago,), one=True)["c"],
            "subs_active": db.q("SELECT COUNT(*) c FROM subscriptions WHERE status='active' AND ends_at>?", (db.now_str(),), one=True)["c"],
            "revenue_total": db.q("SELECT COALESCE(SUM(amount_thb),0) v FROM payments WHERE status='verified'", one=True)["v"],
            "revenue_24h": db.q("SELECT COALESCE(SUM(amount_thb),0) v FROM payments WHERE status='verified' AND verified_at>=?", (day_ago,), one=True)["v"],
            "pending_payments": db.q("SELECT COUNT(*) c FROM payments WHERE status='pending'", one=True)["c"],
            "keys_active": db.q("SELECT COUNT(*) c FROM api_keys WHERE revoked=0", one=True)["c"],
            "bot_chats": db.q("SELECT COUNT(*) c FROM bot_chats", one=True)["c"],
            "bot_msgs_24h": db.q("SELECT COALESCE(SUM(msg_count),0) c FROM bot_chats WHERE last_msg_at>=?", (day_ago,), one=True)["c"],
        }
    except Exception as e:
        log.warning("collect_stats error: %s", e)
        return dict(_fallback)


def render_prometheus(s: dict) -> str:
    """แปลงสถิติเป็น Prometheus exposition format"""
    lines = [
        "# HELP thai_api_hub_info Build info",
        "# TYPE thai_api_hub_info gauge",
        f'thai_api_hub_info{{version="{config.VERSION}"}} 1',
        "# HELP thai_api_hub_requests_total Total API requests",
        "# TYPE thai_api_hub_requests_total counter",
        f"thai_api_hub_requests_total {s['requests_total']}",
        "# HELP thai_api_hub_requests_24h Requests in last 24h",
        "# TYPE thai_api_hub_requests_24h gauge",
        f"thai_api_hub_requests_24h {s['requests_24h']}",
        "# HELP thai_api_hub_errors_total Total errors",
        "# TYPE thai_api_hub_errors_total counter",
        f"thai_api_hub_errors_total {s['errors_total']}",
        "# HELP thai_api_hub_errors_24h Errors in last 24h",
        "# TYPE thai_api_hub_errors_24h gauge",
        f"thai_api_hub_errors_24h {s['errors_24h']}",
        "# HELP thai_api_hub_tokens_24h Tokens in last 24h",
        "# TYPE thai_api_hub_tokens_24h gauge",
        f"thai_api_hub_tokens_24h {s['tokens_24h']}",
        "# HELP thai_api_hub_tokens_month Tokens this month",
        "# TYPE thai_api_hub_tokens_month gauge",
        f"thai_api_hub_tokens_month {s['tokens_month']}",
        "# HELP thai_api_hub_cost_month_usd OpenRouter cost this month (USD)",
        "# TYPE thai_api_hub_cost_month_usd gauge",
        f"thai_api_hub_cost_month_usd {s['cost_month_usd']:.4f}",
        "# HELP thai_api_hub_users_total Registered users",
        "# TYPE thai_api_hub_users_total gauge",
        f"thai_api_hub_users_total {s['users_total']}",
        "# HELP thai_api_hub_users_new_24h New users in 24h",
        "# TYPE thai_api_hub_users_new_24h gauge",
        f"thai_api_hub_users_new_24h {s['users_new_24h']}",
        "# HELP thai_api_hub_subscriptions_active Active subscriptions",
        "# TYPE thai_api_hub_subscriptions_active gauge",
        f"thai_api_hub_subscriptions_active {s['subs_active']}",
        "# HELP thai_api_hub_revenue_total_thb Total verified revenue (THB)",
        "# TYPE thai_api_hub_revenue_total_thb gauge",
        f"thai_api_hub_revenue_total_thb {s['revenue_total']:.2f}",
        "# HELP thai_api_hub_revenue_24h_thb Revenue in 24h (THB)",
        "# TYPE thai_api_hub_revenue_24h_thb gauge",
        f"thai_api_hub_revenue_24h_thb {s['revenue_24h']:.2f}",
        "# HELP thai_api_hub_payments_pending Pending payments",
        "# TYPE thai_api_hub_payments_pending gauge",
        f"thai_api_hub_payments_pending {s['pending_payments']}",
        "# HELP thai_api_hub_api_keys_active Active API keys",
        "# TYPE thai_api_hub_api_keys_active gauge",
        f"thai_api_hub_api_keys_active {s['keys_active']}",
        "# HELP thai_api_hub_bot_chats Bot chat users",
        "# TYPE thai_api_hub_bot_chats gauge",
        f"thai_api_hub_bot_chats {s['bot_chats']}",
    ]
    if s["requests_24h"] > 0:
        err_rate = s["errors_24h"] / s["requests_24h"] * 100
        lines += [
            "# HELP thai_api_hub_error_rate_percent Error rate in 24h (%)",
            "# TYPE thai_api_hub_error_rate_percent gauge",
            f"thai_api_hub_error_rate_percent {err_rate:.2f}",
        ]
    return "\n".join(lines) + "\n"


# alert deduplication: จำ state ล่าสุดที่แจ้งไป (key -> (signature, timestamp))
_last_alerts: dict[str, tuple[str, float]] = {}
_ALERT_REPEAT_HOURS = 6  # แจ้งซ้ำได้ทุก 6 ชม. ถ้าสถานะเดิม


def _should_alert(key: str, signature: str) -> bool:
    """แจ้งเฉพาะครั้งแรกที่เห็นสถานะนี้ หรือครบ 6 ชม. (กันเด้งทุก 10 นาที)"""
    now = time.time()
    last = _last_alerts.get(key)
    if last and last[0] == signature and now - last[1] < _ALERT_REPEAT_HOURS * 3600:
        return False
    _last_alerts[key] = (signature, now)
    return True


async def check_and_alert() -> None:
    """แจ้งเตือน Telegram เมื่อ error rate > 20% (เรียกทุก 10 นาที)"""
    from . import telegram as tg
    s = collect_stats()
    if s["requests_24h"] >= 20 and s["errors_24h"] / s["requests_24h"] > 0.20:
        rate = s["errors_24h"] / s["requests_24h"] * 100
        if _should_alert("error_rate", f"{rate:.0f}%"):
            await tg.send_telegram(
                f"🚨 <b>Alert: Error Rate สูง!</b>\n"
                f"⚠ {rate:.1f}% ของ {s['requests_24h']} คำขอใน 24 ชม. ล้มเหลว\n"
                f"🔎 ตรวจสอบ: {config.SITE_URL}/admin")
    if s["pending_payments"] >= 1:
        if _should_alert("pending_payments", str(s["pending_payments"])):
            await tg.send_telegram(
                f"⏳ <b>มีบิลรออนุมัติ {s['pending_payments']} รายการ</b>\n"
                f"→ {config.SITE_URL}/admin")


async def daily_report() -> None:
    """สรุปยอดประจำวันส่ง Telegram"""
    from . import telegram as tg
    s = collect_stats()
    await tg.send_telegram(
        f"📊 <b>รายงานประจำวัน — Thai API Hub</b>\n"
        f"📅 {datetime.now().strftime('%d %b %Y')}\n\n"
        f"👤 ผู้ใช้ใหม่: <b>{s['users_new_24h']}</b> (รวม {s['users_total']})\n"
        f"🔌 API: <b>{s['requests_24h']}</b> คำขอ · {s['tokens_24h']:,} tokens\n"
        f"⚠️ Errors: <b>{s['errors_24h']}</b>\n"
        f"💰 รายได้วันนี้: <b>฿{s['revenue_24h']:,.0f}</b> (รวม ฿{s['revenue_total']:,.0f})\n"
        f"📦 แพ็กเกจ active: {s['subs_active']}\n"
        f"⏳ บิลรออนุมัติ: {s['pending_payments']}\n"
        f"🤖 บอท: {s['bot_msgs_24h']} ข้อความ\n"
        f"💵 ต้นทุน OR เดือนนี้: ${s['cost_month_usd']:.4f}")


async def monitor_loop() -> None:
    """Background: health-alert ทุก 10 นาที + daily report เที่ยงคืน + cleanup ทุกชั่วโมง"""
    last_report_day = datetime.now().day
    last_cleanup = datetime.now().hour
    while True:
        try:
            await asyncio.sleep(600)  # 10 นาที
            now = datetime.now()
            # alert + health check
            if config.TELEGRAM_CHAT_ID:
                await check_and_alert()
            # daily report เที่ยงคืน (00:00-00:10)
            if now.day != last_report_day and now.hour == 0 and config.TELEGRAM_CHAT_ID:
                await daily_report()
                last_report_day = now.day
            # cleanup: sessions หมดอายุ + log เก่าเกิน 90 วัน (ทุกชั่วโมง)
            if now.hour != last_cleanup:
                db.x("DELETE FROM sessions WHERE expires_at < ?", (db.now_str(),))
                cutoff = (datetime.now() - timedelta(days=90)).strftime(db.FMT)
                db.x("DELETE FROM usage_logs WHERE created_at < ?", (cutoff,))
                db.x("DELETE FROM audit_logs WHERE created_at < ?", (cutoff,))
                last_cleanup = now.hour
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.warning("monitor loop error: %s", e)
            await asyncio.sleep(60)
