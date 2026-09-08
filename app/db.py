"""SQLite helpers + schema + แพ็กเกจราคา"""
import sqlite3
import threading
from datetime import datetime, timedelta

from . import config

FMT = "%Y-%m-%d %H:%M:%S"
_local = threading.local()


def now_str() -> str:
    return datetime.now().strftime(FMT)


def plus(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime(FMT)


def get_db() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(config.DB_PATH), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.conn = conn
    return conn


def q(sql: str, params=(), one: bool = False):
    cur = get_db().execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    if one:
        return rows[0] if rows else None
    return rows


def x(sql: str, params=()) -> int:
    conn = get_db()
    cur = conn.execute(sql, params)
    conn.commit()
    rid = cur.lastrowid
    cur.close()
    return rid


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  name TEXT DEFAULT '',
  role TEXT DEFAULT 'user',
  is_active INTEGER DEFAULT 1,
  trial_ends_at TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  key_hash TEXT UNIQUE NOT NULL,
  key_prefix TEXT NOT NULL,
  name TEXT DEFAULT 'default',
  revoked INTEGER DEFAULT 0,
  last_used_at TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans(
  code TEXT PRIMARY KEY,
  name_th TEXT NOT NULL,
  tier INTEGER DEFAULT 0,
  price_month_thb REAL DEFAULT 0,
  price_year_thb REAL DEFAULT 0,
  daily_requests INTEGER DEFAULT 0,
  monthly_tokens INTEGER DEFAULT 0,
  rpm INTEGER DEFAULT 30,
  chain TEXT DEFAULT 'local_first',
  passthrough INTEGER DEFAULT 0,
  features_th TEXT DEFAULT '',
  sort INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS subscriptions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  plan_code TEXT NOT NULL,
  status TEXT DEFAULT 'pending_payment',
  billing_period TEXT DEFAULT 'month',
  starts_at TEXT DEFAULT '',
  ends_at TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  subscription_id INTEGER NOT NULL,
  plan_code TEXT NOT NULL,
  billing_period TEXT NOT NULL,
  amount_thb REAL NOT NULL,
  ref_code TEXT UNIQUE NOT NULL,
  status TEXT DEFAULT 'pending',
  note TEXT DEFAULT '',
  paid_at TEXT DEFAULT '',
  verified_at TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  key_id INTEGER,
  alias TEXT DEFAULT '',
  backend_model TEXT DEFAULT '',
  provider TEXT DEFAULT '',
  prompt_tokens INTEGER DEFAULT 0,
  completion_tokens INTEGER DEFAULT 0,
  latency_ms INTEGER DEFAULT 0,
  status TEXT DEFAULT 'ok',
  cost_usd REAL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_logs(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_usage_key ON usage_logs(key_id, created_at);
"""

# แพ็กเกจขาย (features_th คั่นรายการด้วย |)
PLANS = [
    dict(code="trial", name_th="ทดลองใช้ฟรี", tier=0, price_month_thb=0, price_year_thb=0,
         daily_requests=30, monthly_tokens=300_000, rpm=10, chain="local_first", passthrough=0, sort=0,
         features_th="โมเดลในเครื่อง (Local AI) + โมเดลฟรีคุณภาพสูงจาก AI ระดับโลก|30 คำขอ/วัน|300,000 tokens/เดือน|ใช้ฟรี 7 วันหลังสมัคร"),
    dict(code="starter", name_th="เริ่มต้น", tier=1, price_month_thb=199, price_year_thb=1990,
         daily_requests=300, monthly_tokens=3_000_000, rpm=30, chain="local_first", passthrough=0, sort=1,
         features_th="+ โมเดลราคาประหยัด (DeepSeek V3, Gemini Flash, GPT-4o-mini)|300 คำขอ/วัน|3 ล้าน tokens/เดือน|30 คำขอ/นาที|ชำระผ่านโอนธนาคาร/QR"),
    dict(code="pro", name_th="โปร", tier=2, price_month_thb=499, price_year_thb=4990,
         daily_requests=1_500, monthly_tokens=15_000_000, rpm=60, chain="quality_first", passthrough=1, sort=2,
         features_th="ทุกโมเดล + เลือกโมเดล AI ระดับโลกได้เองทุกตัว|เส้นทางคุณภาพก่อน: ฟรี → พรีเมียม → Local|1,500 คำขอ/วัน|15 ล้าน tokens/เดือน|60 คำขอ/นาที|รองรับ alias โมเดลทั้ง 5 แบบ"),
    dict(code="business", name_th="ธุรกิจ", tier=3, price_month_thb=1_499, price_year_thb=14_990,
         daily_requests=10_000, monthly_tokens=80_000_000, rpm=120, chain="quality_first", passthrough=1, sort=3,
         features_th="สูงสุดทุกอย่างของแพ็กเกจโปร|10,000 คำขอ/วัน|80 ล้าน tokens/เดือน|120 คำขอ/นาที|เหมาะกับทีม/เอเจนซี่|สนับสนุนลำดับแรก"),
]


def init_db() -> None:
    conn = get_db()
    conn.executescript(SCHEMA)
    for p in PLANS:
        cols = "code,name_th,tier,price_month_thb,price_year_thb,daily_requests,monthly_tokens,rpm,chain,passthrough,features_th,sort"
        ph = ",".join(f":{c}" for c in cols.split(","))
        updates = ",".join(f"{c}=:{c}" for c in cols.split(",") if c != "code")
        conn.execute(f"INSERT INTO plans({cols}) VALUES({ph}) ON CONFLICT(code) DO UPDATE SET {updates}", p)
    conn.commit()
