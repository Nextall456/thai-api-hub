"""โหลดค่าตั้งจาก .env + ค่าเริ่มต้นของระบบ"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8077"))
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
DB_PATH = Path(os.environ.get("DB_PATH", str(BASE_DIR / "data" / "thaiapihub.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
LOCAL_MODELS = [m.strip() for m in os.environ.get("LOCAL_MODELS", "qwen2.5:7b,jarvis-llama3.1:latest,llama3.2:latest").split(",") if m.strip()]

SITE_NAME = os.environ.get("SITE_NAME", "Thai API Hub")
SITE_URL = os.environ.get("SITE_URL", f"http://localhost:{PORT}").rstrip("/")
ADMIN_EMAILS = [e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()]

# Payment settings
PAYMENT_BANK = os.environ.get("PAYMENT_BANK", "").strip()
PAYMENT_ACCOUNT_NO = os.environ.get("PAYMENT_ACCOUNT_NO", "").strip()
PAYMENT_ACCOUNT_NAME = os.environ.get("PAYMENT_ACCOUNT_NAME", "").strip()
PAYMENT_QR_PATH = BASE_DIR / "static" / "payment-qr.jpg"

# Telegram Bot สำหรับแจ้งเตือนแอดมิน
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# โหมดอนุมัติชำระเงินอัตโนมัติ (true = ลูกค้ากดแจ้งชำระแล้วเปิดใช้ทันที / false = แอดมินกดอนุมัติเอง)
AUTO_VERIFY_PAYMENT = os.environ.get("AUTO_VERIFY_PAYMENT", "false").lower() == "true"

TRIAL_DAYS = int(os.environ.get("TRIAL_DAYS", "7"))
VERSION = "1.3.0"
