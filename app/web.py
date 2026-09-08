"""Jinja2 templates + session helpers สำหรับหน้าเว็บ"""
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.templating import Jinja2Templates

from . import config, db, security

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
SESSION_COOKIE = "tah_session"


def get_user(request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return db.q(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token = ? AND s.expires_at > ?",
        (token, db.now_str()), one=True)


def create_session(response, user_id: int) -> None:
    token = security.new_session_token()
    db.x("INSERT INTO sessions(token, user_id, expires_at, created_at) VALUES(?,?,?,?)",
         (token, user_id, db.plus(30), db.now_str()))
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        max_age=30 * 86400, path="/")


def drop_session(request, response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.x("DELETE FROM sessions WHERE token = ?", (token,))
    response.delete_cookie(SESSION_COOKIE, path="/")


def render(request, name: str, status_code: int = 200, **ctx):
    ctx.setdefault("user", get_user(request))
    ctx.setdefault("site_name", config.SITE_NAME)
    ctx.setdefault("site_url", config.SITE_URL)
    ctx.setdefault("msg", request.query_params.get("msg", ""))
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
