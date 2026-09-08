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


def check_quota(user_id: int, key_id: int | None, plan: dict) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    r = db.q("SELECT COUNT(*) c FROM usage_logs WHERE user_id=? AND date(created_at)=?",
             (user_id, today), one=True)
    if r["c"] >= plan["daily_requests"]:
        raise ApiError(429, f"ครบโควตา {plan['daily_requests']:,} คำขอ/วัน ของแพ็กเกจ {plan['name_th']} แล้ว "
                            f"(ต่ออายุ/อัปเกรดได้ที่หน้า Billing)", "quota_error")
    month_start = datetime.now().strftime("%Y-%m-01 00:00:00")
    r = db.q("SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0) t FROM usage_logs "
             "WHERE user_id=? AND created_at >= ?", (user_id, month_start), one=True)
    if r["t"] >= plan["monthly_tokens"]:
        raise ApiError(429, f"ครบโควตา {plan['monthly_tokens']:,} tokens/เดือน แล้ว "
                            f"(ต่ออายุ/อัปเกรดได้ที่หน้า Billing)", "quota_error")
    if key_id:
        minute_ago = (datetime.now() - timedelta(seconds=60)).strftime(db.FMT)
        r = db.q("SELECT COUNT(*) c FROM usage_logs WHERE key_id=? AND created_at >= ?",
                 (key_id, minute_ago), one=True)
        if r["c"] >= plan["rpm"]:
            raise ApiError(429, f"เกินอัตรา {plan['rpm']} คำขอ/นาที — โปรดลดความถี่", "rate_limit_error")


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
