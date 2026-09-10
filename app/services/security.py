"""Security: Rate Limiting + Audit Log + Security Headers"""
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

from .. import db

# ---------------- Rate Limiting ----------------

_rate_store: dict[str, deque] = defaultdict(deque)


def check_rate_limit(ip: str, limit: int = 60, window: int = 60) -> bool:
    """True = ผ่าน, False = เกินลิมิต (default: 60 requests/นาที ต่อ IP)"""
    now = time.time()
    bucket = _rate_store[ip]
    while bucket and bucket[0] < now - window:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    # เก็บเฉพาะ IP ล่าสุด 10,000 ตัว
    if len(_rate_store) > 10_000:
        _rate_store.pop(next(iter(_rate_store)))
    return True


async def rate_limit_middleware(request: Request, call_next):
    """ครอบทุก request — จำกัด 60 req/นาที ต่อ IP (เว้น /static, /health)"""
    path = request.url.path
    if path.startswith(("/static", "/health", "/metrics")):
        return await call_next(request)
    ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(ip):
        return JSONResponse(
            status_code=429,
            content={"error": {"message": "เรียกถี่เกินไป — รอสักครู่แล้วลองใหม่ (60 คำขอ/นาที ต่อ IP)",
                               "type": "rate_limit_error", "code": 429}},
            headers={"Retry-After": "60"})
    return await call_next(request)


# ---------------- Security Headers ----------------

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


async def security_headers_middleware(request: Request, call_next):
    resp = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    return resp


# ---------------- Audit Log ----------------

def audit(user_id: int | None, action: str, detail: str = "") -> None:
    """บันทึก action สำคัญลง audit_logs (แอดมินอนุมัติบิล, ระงับผู้ใช้ ฯลฯ)"""
    db.x("INSERT INTO audit_logs(user_id, action, detail, created_at) VALUES(?,?,?,?)",
         (user_id, action[:50], detail[:500], db.now_str()))
