"""โควตา / มิเตอร์การใช้งานต่อผู้ใช้"""
from datetime import datetime, timedelta

from .. import db
from ..api_errors import ApiError


def get_active_plan(user: dict) -> tuple[dict | None, str]:
    """คืน (แพ็กเกจที่ใช้ได้, ที่มา: sub|trial|none)"""
    row = db.q(
        "SELECT p.* FROM subscriptions s JOIN plans p ON p.code = s.plan_code "
        "WHERE s.user_id = ? AND s.status = 'active' AND s.ends_at > ? "
        "ORDER BY s.ends_at DESC LIMIT 1",
        (user["id"], db.now_str()), one=True)
    if row:
        return row, "sub"
    t = user.get("trial_ends_at") or ""
    if t:
        try:
            if datetime.strptime(t, db.FMT) > datetime.now():
                return db.q("SELECT * FROM plans WHERE code='trial'", one=True), "trial"
        except ValueError:
            pass
    return None, "none"


def get_rate_limit_info(user_id: int, key_id: int | None, plan: dict) -> dict:
    """คำนวณสถิติโควตาคงเหลือและสถานะแจ้งเตือนล่วงหน้า (80% / 95%)"""
    today = datetime.now().strftime("%Y-%m-%d")
    r_daily = db.q("SELECT COUNT(*) c FROM usage_logs WHERE user_id=? AND date(created_at)=?",
                   (user_id, today), one=True)
    daily_used = r_daily["c"] if r_daily else 0
    daily_limit = plan.get("daily_requests", 0)

    month_start = datetime.now().strftime("%Y-%m-01 00:00:00")
    r_month = db.q("SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0) t FROM usage_logs "
                   "WHERE user_id=? AND created_at >= ?", (user_id, month_start), one=True)
    tokens_used = r_month["t"] if r_month else 0
    tokens_limit = plan.get("monthly_tokens", 0)

    rpm_used = 0
    rpm_limit = plan.get("rpm", 30)
    if key_id:
        minute_ago = (datetime.now() - timedelta(seconds=60)).strftime(db.FMT)
        r_rpm = db.q("SELECT COUNT(*) c FROM usage_logs WHERE key_id=? AND created_at >= ?",
                     (key_id, minute_ago), one=True)
        rpm_used = r_rpm["c"] if r_rpm else 0

    warnings = []
    if daily_limit > 0:
        ratio_daily = daily_used / daily_limit
        if ratio_daily >= 0.95:
            warnings.append(f"Daily requests at {ratio_daily*100:.0f}% ({daily_used}/{daily_limit})")
        elif ratio_daily >= 0.80:
            warnings.append(f"Daily requests at {ratio_daily*100:.0f}% ({daily_used}/{daily_limit})")

    if tokens_limit > 0:
        ratio_tokens = tokens_used / tokens_limit
        if ratio_tokens >= 0.95:
            warnings.append(f"Monthly tokens at {ratio_tokens*100:.0f}% ({tokens_used:,}/{tokens_limit:,})")
        elif ratio_tokens >= 0.80:
            warnings.append(f"Monthly tokens at {ratio_tokens*100:.0f}% ({tokens_used:,}/{tokens_limit:,})")

    return {
        "daily_limit": daily_limit,
        "daily_used": daily_used,
        "daily_remaining": max(0, daily_limit - daily_used),
        "tokens_limit": tokens_limit,
        "tokens_used": tokens_used,
        "tokens_remaining": max(0, tokens_limit - tokens_used),
        "rpm_limit": rpm_limit,
        "rpm_used": rpm_used,
        "rpm_remaining": max(0, rpm_limit - rpm_used),
        "warning": " | ".join(warnings) if warnings else "",
    }


def check_quota(user_id: int, key_id: int | None, plan: dict) -> dict:
    info = get_rate_limit_info(user_id, key_id, plan)
    if info["daily_used"] >= info["daily_limit"]:
        raise ApiError(429, f"ครบโควตา {info['daily_limit']:,} คำขอ/วัน ของแพ็กเกจ {plan['name_th']} แล้ว "
                            f"(ต่ออายุ/อัปเกรดได้ที่หน้า Billing)", "quota_error")
    if info["tokens_used"] >= info["tokens_limit"]:
        raise ApiError(429, f"ครบโควตา {info['tokens_limit']:,} tokens/เดือน แล้ว "
                            f"(ต่ออายุ/อัปเกรดได้ที่หน้า Billing)", "quota_error")
    if key_id and info["rpm_used"] >= info["rpm_limit"]:
        raise ApiError(429, f"เกินอัตรา {info['rpm_limit']} คำขอ/นาที — โปรดลดความถี่ (Rate limit exceeded)", "rate_limit_error")
    return info



def record(user_id: int, key_id: int | None, alias: str, provider: str, backend_model: str,
           prompt_tokens: int, completion_tokens: int, latency_ms: int,
           status: str = "ok", cost_usd: float = 0.0) -> None:
    db.x("INSERT INTO usage_logs(user_id, key_id, alias, backend_model, provider, prompt_tokens, "
         "completion_tokens, latency_ms, status, cost_usd, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
         (user_id, key_id, alias, backend_model, provider, prompt_tokens, completion_tokens,
          latency_ms, status, round(cost_usd, 6), db.now_str()))
    if key_id:
        db.x("UPDATE api_keys SET last_used_at=? WHERE id=?", (db.now_str(), key_id))


def today_stats(user_id: int) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    reqs = db.q("SELECT COUNT(*) c FROM usage_logs WHERE user_id=? AND date(created_at)=? AND status='ok'",
                (user_id, today), one=True)["c"]
    month_start = datetime.now().strftime("%Y-%m-01 00:00:00")
    toks = db.q("SELECT COALESCE(SUM(prompt_tokens + completion_tokens),0) t FROM usage_logs "
                "WHERE user_id=? AND created_at>=? AND status='ok'", (user_id, month_start), one=True)["t"]
    return {"today_requests": reqs, "month_tokens": toks}


def daily_usage(user_id: int, days: int = 14) -> list[dict]:
    since = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")
    rows = db.q(
        "SELECT date(created_at) d, COUNT(*) c, "
        "COALESCE(SUM(prompt_tokens + completion_tokens),0) t "
        "FROM usage_logs WHERE user_id=? AND created_at >= ? AND status='ok' "
        "GROUP BY date(created_at) ORDER BY d", (user_id, since))
    out = {}
    for r in rows:
        out[r["d"]] = r
    result = []
    for i in range(days):
        d = (datetime.now() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        r = out.get(d, {"d": d, "c": 0, "t": 0})
        result.append({"date": d, "requests": r["c"], "tokens": r["t"]})
    return result


def est_tokens(text: str) -> int:
    """ประมาณ token จากความยาวข้อความ (ไทย/อังกฤษปนกัน ใช้ ~3.5 ตัวอักษร/token)"""
    return max(1, int(len(text or "") / 3.5) + 1)
