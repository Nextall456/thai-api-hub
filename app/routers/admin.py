"""แผงผู้ดูแลระบบ: สถิติ, อนุมัติการชำระเงิน, จัดการผู้ใช้"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from urllib.parse import quote

from .. import config, db
from ..services.providers import ollama_models
from ..web import get_user, render

router = APIRouter(prefix="/admin")


def _require_admin(request: Request):
    user = get_user(request)
    if not user or user["role"] != "admin":
        return None
    return user


@router.get("")
@router.get("/")
async def admin_home(request: Request):
    user = _require_admin(request)
    if not user:
        return RedirectResponse("/dashboard", 303)
    day_ago = (datetime.now() - timedelta(hours=24)).strftime(db.FMT)
    stats = {
        "users": db.q("SELECT COUNT(*) c FROM users", one=True)["c"],
        "active_subs": db.q("SELECT COUNT(*) c FROM subscriptions WHERE status='active' AND ends_at>?",
                            (db.now_str(),), one=True)["c"],
        "revenue": db.q("SELECT COALESCE(SUM(amount_thb),0) v FROM payments WHERE status='verified'",
                        one=True)["v"],
        "req24": db.q("SELECT COUNT(*) c FROM usage_logs WHERE created_at>=?", (day_ago,), one=True)["c"],
        "fail24": db.q("SELECT COUNT(*) c FROM usage_logs WHERE created_at>=? AND status!='ok'",
                       (day_ago,), one=True)["c"],
    }
    pending = db.q("SELECT pay.*, u.email FROM payments pay JOIN users u ON u.id=pay.user_id "
                   "WHERE pay.status='pending' ORDER BY pay.id")
    recent = db.q("SELECT l.*, u.email FROM usage_logs l JOIN users u ON u.id=l.user_id "
                  "ORDER BY l.id DESC LIMIT 25")
    local_models = await ollama_models()
    return render(request, "admin.html", stats=stats, pending=pending, recent=recent,
                  local_models=local_models, has_or_key=bool(config.OPENROUTER_API_KEY))


@router.get("/users")
async def users_page(request: Request):
    user = _require_admin(request)
    if not user:
        return RedirectResponse("/dashboard", 303)
    rows = db.q(
        "SELECT u.*, (SELECT p.name_th FROM subscriptions s JOIN plans p ON p.code=s.plan_code "
        "WHERE s.user_id=u.id AND s.status='active' AND s.ends_at>? ORDER BY s.ends_at DESC LIMIT 1) sub_plan, "
        "(SELECT MAX(s.ends_at) FROM subscriptions s WHERE s.user_id=u.id AND s.status='active') sub_end "
        "FROM users u ORDER BY u.id DESC LIMIT 300", (db.now_str(),))
    return render(request, "admin_users.html", users=rows)


@router.post("/payments/{pay_id}/verify")
async def verify_payment(request: Request, pay_id: int):
    user = _require_admin(request)
    if not user:
        return RedirectResponse("/dashboard", 303)
    pay = db.q("SELECT * FROM payments WHERE id=? AND status='pending'", (pay_id,), one=True)
    if not pay:
        return RedirectResponse("/admin?msg=" + quote("รายการนี้ถูกจัดการไปแล้ว"), 303)
    db.x("UPDATE payments SET status='verified', verified_at=? WHERE id=?", (db.now_str(), pay_id))
    period_days = 365 if pay["billing_period"] == "year" else 30
    sub = db.q("SELECT * FROM subscriptions WHERE id=?", (pay["subscription_id"],), one=True)
    existing = db.q("SELECT * FROM subscriptions WHERE user_id=? AND plan_code=? AND status='active' "
                    "AND ends_at>? AND id != ?",
                    (pay["user_id"], pay["plan_code"], db.now_str(), sub["id"]), one=True)
    if existing:  # ต่ออายุ: ต่อจากวันหมดอายุเดิม
        base = datetime.strptime(existing["ends_at"], db.FMT)
        new_end = (base + timedelta(days=period_days)).strftime(db.FMT)
        db.x("UPDATE subscriptions SET ends_at=? WHERE id=?", (new_end, existing["id"]))
        db.x("UPDATE subscriptions SET status='expired' WHERE id=?", (sub["id"],))
    else:
        db.x("UPDATE subscriptions SET status='active', starts_at=?, ends_at=? WHERE id=?",
             (db.now_str(), db.plus(period_days), sub["id"]))
    return RedirectResponse("/admin?msg=" + quote(f"อนุมัติบิล #{pay_id} แล้ว — เปิดใช้งาน {period_days} วัน"), 303)


@router.post("/payments/{pay_id}/reject")
async def reject_payment(request: Request, pay_id: int):
    user = _require_admin(request)
    if not user:
        return RedirectResponse("/dashboard", 303)
    db.x("UPDATE payments SET status='rejected', verified_at=? WHERE id=? AND status='pending'",
         (db.now_str(), pay_id))
    return RedirectResponse("/admin?msg=" + quote("ปฏิเสธบิลแล้ว"), 303)


@router.post("/users/{uid}/toggle")
async def toggle_user(request: Request, uid: int):
    user = _require_admin(request)
    if not user:
        return RedirectResponse("/dashboard", 303)
    target = db.q("SELECT * FROM users WHERE id=?", (uid,), one=True)
    if target and target["id"] != user["id"]:
        db.x("UPDATE users SET is_active=? WHERE id=?", (0 if target["is_active"] else 1, uid))
    return RedirectResponse("/admin/users?msg=" + quote("อัปเดตสถานะผู้ใช้แล้ว"), 303)
