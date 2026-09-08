"""หน้าเว็บสาธารณะ: หน้าแรก/ราคา, เอกสาร, สมัคร, เข้าสู่ระบบ"""
import re
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import config, db, security
from ..services.router_engine import ALIAS_INFO
from ..services import telegram as tg_notify
from ..web import create_session, drop_session, get_user, render

router = APIRouter()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.get("/")
async def index(request: Request):
    plans = db.q("SELECT * FROM plans WHERE code != 'trial' ORDER BY sort")
    trial = db.q("SELECT * FROM plans WHERE code='trial'", one=True)
    return render(request, "index.html", plans=plans, trial=trial, alias_info=ALIAS_INFO)


@router.get("/docs-api")
async def docs_page(request: Request):
    plans = db.q("SELECT * FROM plans ORDER BY sort")
    return render(request, "docs.html", plans=plans, alias_info=ALIAS_INFO,
                  has_or_key=bool(config.OPENROUTER_API_KEY))


@router.get("/health")
async def health():
    return {"ok": True, "service": config.SITE_NAME, "time": db.now_str()}


@router.get("/login")
async def login_page(request: Request):
    if get_user(request):
        return RedirectResponse("/dashboard", 303)
    return render(request, "login.html")


@router.post("/login")
async def login(request: Request, email: str = Form(""), password: str = Form("")):
    user = db.q("SELECT * FROM users WHERE email=?", (email.strip().lower(),), one=True)
    if not user or not security.verify_password(password, user["password_hash"]):
        return render(request, "login.html", status_code=400, error="อีเมลหรือรหัสผ่านไม่ถูกต้อง")
    if not user["is_active"]:
        return render(request, "login.html", status_code=403, error="บัญชีถูกระงับ กรุณาติดต่อผู้ดูแล")
    resp = RedirectResponse("/dashboard", 303)
    create_session(resp, user["id"])
    return resp


@router.get("/signup")
async def signup_page(request: Request):
    if get_user(request):
        return RedirectResponse("/dashboard", 303)
    return render(request, "signup.html")


@router.post("/signup")
async def signup(request: Request, name: str = Form(""), email: str = Form(""),
                 password: str = Form("")):
    name, email = name.strip()[:60], email.strip().lower()
    if not EMAIL_RE.match(email):
        return render(request, "signup.html", status_code=400, error="รูปแบบอีเมลไม่ถูกต้อง")
    if len(password) < 8:
        return render(request, "signup.html", status_code=400, error="รหัสผ่านต้องยาวอย่างน้อย 8 ตัวอักษร")
    if db.q("SELECT id FROM users WHERE email=?", (email,), one=True):
        return render(request, "signup.html", status_code=400, error="อีเมลนี้สมัครไว้แล้ว — เข้าสู่ระบบแทน")
    role = "admin" if email in config.ADMIN_EMAILS else "user"
    uid = db.x("INSERT INTO users(email, password_hash, name, role, trial_ends_at, created_at) "
               "VALUES(?,?,?,?,?,?)",
               (email, security.hash_password(password), name, role,
                db.plus(config.TRIAL_DAYS), db.now_str()))
    user = db.q("SELECT * FROM users WHERE id=?", (uid,), one=True)
    await tg_notify.notify_new_user(user, "ทดลองใช้ฟรี 7 วัน")
    resp = RedirectResponse("/dashboard?msg=" + quote(
        f"สมัครสำเร็จ! ทดลองใช้ฟรี {config.TRIAL_DAYS} วัน — สร้าง API Key ได้เลย"), 303)
    create_session(resp, uid)
    return resp


@router.get("/logout")
async def logout(request: Request):
    resp = RedirectResponse("/", 303)
    drop_session(request, resp)
    return resp
