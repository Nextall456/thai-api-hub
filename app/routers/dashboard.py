"""Dashboard ผู้ใช้: ภาพรวม, API Keys, บิล/สมัครแพ็กเกจ, Playground"""
import time
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import config, db, security
from ..api_errors import ApiError
from ..services import router_engine
from ..services import usage as usage_svc
from ..services import telegram as tg_notify
from ..services.providers import price_map
from ..web import get_user, render

router = APIRouter(prefix="/dashboard")


def _require(request: Request):
    user = get_user(request)
    if not user:
        return None
    return user


@router.get("")
@router.get("/")
async def overview(request: Request):
    user = _require(request)
    if not user:
        return RedirectResponse("/login", 303)
    plan, source = usage_svc.get_active_plan(user)
    stats = usage_svc.today_stats(user["id"])
    keys = db.q("SELECT * FROM api_keys WHERE user_id=? AND revoked=0 ORDER BY id DESC", (user["id"],))
    sub = None
    if source == "sub":
        sub = db.q("SELECT * FROM subscriptions WHERE user_id=? AND status='active' AND ends_at>? "
                   "ORDER BY ends_at DESC LIMIT 1", (user["id"], db.now_str()), one=True)
    chart = usage_svc.daily_usage(user["id"], 14)
    max_c = max([c["requests"] for c in chart] + [1])
    trial_left = ""
    if source == "trial" and user.get("trial_ends_at"):
        try:
            from datetime import datetime
            end = datetime.strptime(user["trial_ends_at"], db.FMT)
            trial_left = str(max(0, (end - datetime.now()).days))
        except ValueError:
            pass
    return render(request, "dash_overview.html", plan=plan, source=source, sub=sub,
                  stats=stats, keys=keys, chart=chart, max_c=max_c,
                  has_or_key=bool(config.OPENROUTER_API_KEY), site_url=config.SITE_URL,
                  is_admin=user["role"] == "admin", trial_left=trial_left)


# ---------------- API Keys ----------------

@router.get("/keys")
async def keys_page(request: Request):
    user = _require(request)
    if not user:
        return RedirectResponse("/login", 303)
    rows = db.q("SELECT * FROM api_keys WHERE user_id=? ORDER BY id DESC", (user["id"],))
    return render(request, "dash_keys.html", keys=rows, new_key="")


@router.post("/keys")
async def keys_create(request: Request, name: str = Form("default")):
    user = _require(request)
    if not user:
        return RedirectResponse("/login", 303)
    name = name.strip()[:40] or "default"
    key, kh, prefix = security.new_api_key()
    db.x("INSERT INTO api_keys(user_id, key_hash, key_prefix, name, created_at) VALUES(?,?,?,?,?)",
         (user["id"], kh, prefix, name, db.now_str()))
    rows = db.q("SELECT * FROM api_keys WHERE user_id=? ORDER BY id DESC", (user["id"],))
    return render(request, "dash_keys.html", keys=rows, new_key=key)


@router.post("/keys/{key_id}/revoke")
async def keys_revoke(request: Request, key_id: int):
    user = _require(request)
    if not user:
        return RedirectResponse("/login", 303)
    db.x("UPDATE api_keys SET revoked=1 WHERE id=? AND user_id=?", (key_id, user["id"]))
    return RedirectResponse("/dashboard/keys?msg=" + quote("ยกเลิกคีย์แล้ว"), 303)


# ---------------- บิล & แพ็กเกจ ----------------

@router.get("/billing")
async def billing_page(request: Request):
    user = _require(request)
    if not user:
        return RedirectResponse("/login", 303)
    plans = db.q("SELECT * FROM plans WHERE code != 'trial' ORDER BY sort")
    active_sub = db.q(
        "SELECT s.*, p.name_th plan_name FROM subscriptions s JOIN plans p ON p.code=s.plan_code "
        "WHERE s.user_id=? AND s.status='active' AND s.ends_at>? ORDER BY s.ends_at DESC LIMIT 1",
        (user["id"], db.now_str()), one=True)
    pending = db.q(
        "SELECT pay.*, p.name_th plan_name FROM payments pay JOIN plans p ON p.code=pay.plan_code "
        "WHERE pay.user_id=? AND pay.status='pending' ORDER BY pay.id DESC", (user["id"],))
    history = db.q(
        "SELECT pay.*, p.name_th plan_name FROM payments pay JOIN plans p ON p.code=pay.plan_code "
        "WHERE pay.user_id=? AND pay.status!='pending' ORDER BY pay.id DESC LIMIT 20", (user["id"],))
    return render(request, "dash_billing.html", plans=plans, active_sub=active_sub,
                  pending=pending, history=history, pay_ready=config.PAYMENT_QR_PATH.exists())


@router.post("/billing/subscribe")
async def subscribe(request: Request, plan_code: str = Form(...), period: str = Form("month")):
    user = _require(request)
    if not user:
        return RedirectResponse("/login", 303)
    plan = db.q("SELECT * FROM plans WHERE code=? AND code != 'trial'", (plan_code,), one=True)
    if not plan:
        return RedirectResponse("/dashboard/billing?msg=" + quote("ไม่พบแพ็กเกจนี้"), 303)
    period = "year" if period == "year" else "month"
    amount = plan["price_year_thb"] if period == "year" else plan["price_month_thb"]
    ref = security.new_ref_code()
    sub_id = db.x("INSERT INTO subscriptions(user_id, plan_code, status, billing_period, created_at) "
                  "VALUES(?,?,?,?,?)", (user["id"], plan_code, "pending_payment", period, db.now_str()))
    pay_id = db.x("INSERT INTO payments(user_id, subscription_id, plan_code, billing_period, "
                  "amount_thb, ref_code, created_at) VALUES(?,?,?,?,?,?,?)",
                  (user["id"], sub_id, plan_code, period, amount, ref, db.now_str()))
    return RedirectResponse(f"/dashboard/billing/invoice/{pay_id}", 303)


@router.get("/billing/invoice/{pay_id}")
async def invoice(request: Request, pay_id: int):
    user = _require(request)
    if not user:
        return RedirectResponse("/login", 303)
    pay = db.q("SELECT pay.*, p.name_th plan_name FROM payments pay JOIN plans p ON p.code=pay.plan_code "
               "WHERE pay.id=? AND pay.user_id=?", (pay_id, user["id"]), one=True)
    if not pay:
        return RedirectResponse("/dashboard/billing", 303)
    # ใช้รูป QR ตัวจริง (ไฟล์เดิม ไม่เจนใหม่) แสดงเฉพาะบิลที่ยังรอชำระ
    pay_ready = config.PAYMENT_QR_PATH.exists()
    qr_uri = "/static/payment-qr.jpg" if pay_ready and pay["status"] == "pending" else ""
    return render(request, "invoice.html", pay=pay, qr_uri=qr_uri, pay_ready=pay_ready,
                  bank=config.PAYMENT_BANK, acct_no=config.PAYMENT_ACCOUNT_NO,
                  acct_name=config.PAYMENT_ACCOUNT_NAME)


@router.post("/billing/invoice/{pay_id}/notify")
async def invoice_notify(request: Request, pay_id: int, note: str = Form("")):
    user = _require(request)
    if not user:
        return RedirectResponse("/login", 303)
    pay = db.q("SELECT * FROM payments WHERE id=? AND user_id=? AND status='pending'",
               (pay_id, user["id"]), one=True)
    if not pay:
        return RedirectResponse("/dashboard/billing?msg=" +
                                quote("ไม่พบใบแจ้งหนี้นี้ หรือถูกจัดการไปแล้ว"), 303)
    db.x("UPDATE payments SET paid_at=?, note=? WHERE id=? AND user_id=? AND status='pending'",
         (db.now_str(), note.strip()[:200], pay_id, user["id"]))

    # แจ้งเตือนแอดมิน: มีการแจ้งชำระเงินใหม่
    await tg_notify.notify_payment_pending(pay, user["email"], plan["name_th"])

    if config.AUTO_VERIFY_PAYMENT:
        # โหมดอนุมัติอัตโนมัติ (เปิด/ปิดที่ AUTO_VERIFY_PAYMENT ใน .env)
        period_days = 365 if pay["billing_period"] == "year" else 30
        sub = db.q("SELECT * FROM subscriptions WHERE id=?", (pay["subscription_id"],), one=True)
        existing = db.q("SELECT * FROM subscriptions WHERE user_id=? AND plan_code=? AND status='active' "
                        "AND ends_at>? AND id != ?",
                        (pay["user_id"], pay["plan_code"], db.now_str(), sub["id"]), one=True)
        if existing:
            base = datetime.strptime(existing["ends_at"], db.FMT)
            new_end = (base + timedelta(days=period_days)).strftime(db.FMT)
            db.x("UPDATE subscriptions SET ends_at=? WHERE id=?", (new_end, existing["id"]))
            db.x("UPDATE subscriptions SET status='expired' WHERE id=?", (sub["id"],))
        else:
            db.x("UPDATE subscriptions SET status='active', starts_at=?, ends_at=? WHERE id=?",
                 (db.now_str(), db.plus(period_days), sub["id"]))
        db.x("UPDATE payments SET status='verified', verified_at=? WHERE id=?",
             (db.now_str(), pay_id))
        # แจ้งเตือนแอดมิน: อนุมัติอัตโนมัติ
        await tg_notify.notify_payment_verified(pay, user["email"], plan["name_th"], auto=True)
        return RedirectResponse(f"/dashboard/billing/invoice/{pay_id}?msg=" +
                                quote("อนุมัติอัตโนมัติแล้ว — แพ็กเกจเปิดใช้งานทันที"), 303)

    return RedirectResponse(f"/dashboard/billing/invoice/{pay_id}?msg=" +
                            quote("แจ้งชำระเงินแล้ว — รอผู้ดูแลตรวจสอบสลิปและอนุมัติ (1-24 ชม.)"), 303)


# ---------------- โปรไฟล์สมาชิก ----------------

@router.get("/profile")
async def profile_page(request: Request):
    user = _require(request)
    if not user:
        return RedirectResponse("/login", 303)
    plan, source = usage_svc.get_active_plan(user)
    keys_n = db.q("SELECT COUNT(*) c FROM api_keys WHERE user_id=? AND revoked=0",
                  (user["id"],), one=True)["c"]
    total = db.q("SELECT COUNT(*) c, COALESCE(SUM(prompt_tokens+completion_tokens),0) t "
                 "FROM usage_logs WHERE user_id=? AND status='ok'", (user["id"],), one=True)
    initial = (user.get("name") or user["email"])[0].upper()
    return render(request, "dash_profile.html", plan=plan, source=source,
                  keys_n=keys_n, total=total, initial=initial)


@router.post("/profile")
async def profile_update(request: Request, name: str = Form("")):
    user = _require(request)
    if not user:
        return RedirectResponse("/login", 303)
    name = name.strip()[:60]
    if name:
        db.x("UPDATE users SET name=? WHERE id=?", (name, user["id"]))
    return RedirectResponse("/dashboard/profile?msg=" + quote("บันทึกโปรไฟล์แล้ว"), 303)


@router.post("/profile/password")
async def profile_password(request: Request, current: str = Form(""),
                           new: str = Form(""), confirm: str = Form("")):
    user = _require(request)
    if not user:
        return RedirectResponse("/login", 303)
    plan, source = usage_svc.get_active_plan(user)
    keys_n = db.q("SELECT COUNT(*) c FROM api_keys WHERE user_id=? AND revoked=0",
                  (user["id"],), one=True)["c"]
    total = db.q("SELECT COUNT(*) c, COALESCE(SUM(prompt_tokens+completion_tokens),0) t "
                 "FROM usage_logs WHERE user_id=? AND status='ok'", (user["id"],), one=True)
    initial = (user.get("name") or user["email"])[0].upper()
    ctx = dict(plan=plan, source=source, keys_n=keys_n, total=total, initial=initial)
    if not security.verify_password(current, user["password_hash"]):
        return render(request, "dash_profile.html", status_code=400,
                      error="รหัสผ่านปัจจุบันไม่ถูกต้อง", **ctx)
    if len(new) < 8:
        return render(request, "dash_profile.html", status_code=400,
                      error="รหัสผ่านใหม่ต้องยาวอย่างน้อย 8 ตัวอักษร", **ctx)
    if new != confirm:
        return render(request, "dash_profile.html", status_code=400,
                      error="รหัสผ่านใหม่ทั้งสองช่องไม่ตรงกัน", **ctx)
    db.x("UPDATE users SET password_hash=? WHERE id=?",
         (security.hash_password(new), user["id"]))
    return RedirectResponse("/dashboard/profile?msg=" +
                            quote("เปลี่ยนรหัสผ่านสำเร็จ — ใช้รหัสใหม่ตอนเข้าสู่ระบบครั้งหน้า"), 303)


@router.get("/usage")
async def usage_page(request: Request):
    user = _require(request)
    if not user:
        return RedirectResponse("/login", 303)
    plan, source = usage_svc.get_active_plan(user)
    stats = usage_svc.today_stats(user["id"])
    logs = db.q("SELECT l.*, k.name key_name FROM usage_logs l LEFT JOIN api_keys k ON k.id=l.key_id "
                "WHERE l.user_id=? ORDER BY l.id DESC LIMIT 100", (user["id"],))
    by_model = db.q("SELECT COALESCE(NULLIF(backend_model,''),'—') m, provider, COUNT(*) c, "
                    "COALESCE(SUM(prompt_tokens+completion_tokens),0) t, COALESCE(SUM(cost_usd),0) cost "
                    "FROM usage_logs WHERE user_id=? AND status='ok' "
                    "GROUP BY backend_model, provider ORDER BY c DESC LIMIT 12", (user["id"],))
    chart = usage_svc.daily_usage(user["id"], 14)
    max_c = max([c["requests"] for c in chart] + [1])
    return render(request, "dash_usage.html", plan=plan, stats=stats, logs=logs,
                  by_model=by_model, chart=chart, max_c=max_c)


# ---------------- Playground ----------------

@router.get("/playground")
async def playground_page(request: Request):
    user = _require(request)
    if not user:
        return RedirectResponse("/login", 303)
    return render(request, "playground.html")


@router.post("/playground")
async def playground(request: Request):
    user = get_user(request)
    if not user:
        return JSONResponse({"error": "ต้องเข้าสู่ระบบก่อน"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "รูปแบบคำขอไม่ถูกต้อง (ต้องเป็น UTF-8 JSON)"}, status_code=400)
    prompt = str(body.get("prompt") or "").strip()[:4000]
    model = str(body.get("model") or "thai-hub/auto")
    if not prompt:
        return JSONResponse({"error": "กรอกข้อความก่อน"}, status_code=400)
    plan, source = usage_svc.get_active_plan(user)
    if not plan:
        return JSONResponse({"error": "ยังไม่มีแพ็กเกจที่ใช้งานได้ — ไปที่หน้า Billing"}, status_code=402)
    try:
        usage_svc.check_quota(user["id"], None, plan)
    except ApiError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)
    payload = {"messages": [{"role": "user", "content": prompt}]}
    t0 = time.time()
    try:
        provider, backend_model, result, _ = await router_engine.run_chat(model, payload, False, plan)
    except ApiError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)
    latency = int((time.time() - t0) * 1000)
    content = ""
    try:
        content = result["choices"][0]["message"]["content"] or ""
    except Exception:
        pass
    u = result.get("usage") or {}
    pt = int(u.get("prompt_tokens") or usage_svc.est_tokens(prompt))
    ct = int(u.get("completion_tokens") or usage_svc.est_tokens(content))
    pm = price_map().get(backend_model) if provider == "openrouter" else None
    cost = (pt / 1e6 * pm[0] + ct / 1e6 * pm[1]) if pm else 0.0
    usage_svc.record(user["id"], None, model, provider, backend_model, pt, ct, latency, "ok", cost)
    return {"content": content, "backend": f"{provider}:{backend_model}",
            "latency_ms": latency, "tokens": pt + ct}
