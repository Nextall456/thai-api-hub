"""รหัสผ่าน + การสร้างคีย์/โทเคน"""
import hashlib
import hmac
import secrets


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt.encode(), 120_000)
    return f"{salt}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt.encode(), 120_000)
    return hmac.compare_digest(dk.hex(), digest)


def new_api_key() -> tuple[str, str, str]:
    """คืน (key ฉบับเต็ม, hash สำหรับเก็บ DB, prefix สำหรับแสดงผล)"""
    key = "th-" + secrets.token_hex(24)
    return key, hashlib.sha256(key.encode()).hexdigest(), key[:12]


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_ref_code() -> str:
    from datetime import datetime
    return "TP" + datetime.now().strftime("%y%m%d") + secrets.token_hex(2).upper()
