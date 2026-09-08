# Thai API Hub 🇹🇭

**ระบบขาย AI API รายเดือน/รายปี ที่รันบนเครื่องคุณเอง** — API Gateway เข้ากันได้ 100% กับ OpenAI SDK
ด้านหลังสลับโมเดลให้อัตโนมัติระหว่าง Local AI (ฟรี) → โมเดลฟรี → โมเดลราคาถูก จาก OpenRouter

```
ลูกค้า (โค้ดเดิมแค่เปลี่ยน base_url)
        │  OpenAI-compatible API
        ▼
┌─────────────────────────────┐
│  Thai API Hub (FastAPI)      │  สมาชิก · คีย์ · โควตา · บิล PromptPay
└──────────┬──────────────────┘
           │ failover อัตโนมัติ
   ┌───────┼───────────────┬─────────────────┐
   ▼       ▼               ▼                 ▼
 Ollama   OpenRouter   OpenRouter       เว็บแอดมิน
 (local   โมเดลฟรี     โมเดลราคาถูก     (อนุมัติบิล)
  ฟรี)    Llama/DS/Qwen DeepSeek/Gemini
```

## ฟีเจอร์

- **OpenAI-compatible Gateway** — `/v1/chat/completions` (รองรับ streaming) + `/v1/models` เปลี่ยน base_url กับ key ก็ใช้ได้ทันที
- **Local AI ฟรีบนเครื่อง** — ใช้ Ollama (qwen2.5:7b, jarvis-llama3.1, llama3.2) คำขอไม่ออกจากเครื่อง
- **สลับโมเดลอัตโนมัติ (failover)** — alias เดียว เช่น `thai-hub/auto` ระบบไล่ลอง: local → ฟรี → ราคาถูก
- **OpenRouter** — ดึงรายการโมเดลฟรี/ราคาถูกแบบอัตโนมัติ + คิดค่าใช้จ่ายจริงต่อคำขอ
- **ระบบขายรายเดือน/รายปี** — 4 แพ็กเกจ (ทดลองฟรี 7 วัน / เริ่มต้น ฿199 / โปร ฿499 / ธุรกิจ ฿1,499) ชำระผ่าน **QR/โอนธนาคาร** — ใช้รูป QR ตัวจริงของบัญชี (`app/static/payment-qr.jpg` ใช้รูปเดิมทุกบิล ไม่ต้องเจน) พร้อมแสดงเลขบัญชีบนหน้าบิล
- **แดชบอร์ดภาษาไทย** — กราฟการใช้ 14 วัน, โควตา, จัดการ API key หลายคีย์, ห้องทดลอง AI
- **แผงแอดมิน** — อนุมัติ/ปฏิเสธบิล (ต่ออายุอัตโนมัติจากวันหมดอายุเดิม), ดูสถิติ, ระงับผู้ใช้
- **โควตา 3 ชั้น** — คำขอ/วัน, tokens/เดือน, คำขอ/นาที ตามแพ็กเกจ

## เริ่มต้นใช้งาน

ต้องมี: Python 3.11+ และ [Ollama](https://ollama.com) (ดึงโมเดลด้วย `ollama pull qwen2.5:7b`)

```bat
setup.bat    :: ครั้งแรก — สร้าง venv + ติดตั้ง dependencies + สร้าง .env
start.bat    :: รันเซิร์ฟเวอร์ → http://localhost:8077
```

หรือด้วยมือ:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python run.py
```

### ตั้งค่าสำคัญใน `.env`

| ตัวแปร | ความหมาย |
|---|---|
| `ADMIN_EMAILS` | อีเมลเหล่านี้ สมัครแล้วได้สิทธิ์แอดมินทันที |
| `OPENROUTER_API_KEY` | จาก https://openrouter.ai/keys — **ยังไม่ใส่ = ใช้ได้เฉพาะโมเดลในเครื่อง** |
| `LOCAL_MODELS` | ลำดับโมเดล Ollama ที่จะใช้ (คั่นด้วย ,) |
| `PROMPTPAY` → `PAYMENT_BANK` / `PAYMENT_ACCOUNT_NO` / `PAYMENT_ACCOUNT_NAME` | บัญชีรับเงินที่แสดงในหน้าบิล · รูป QR วางที่ `app/static/payment-qr.jpg` |

## ตัวอย่างการเรียกใช้

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8077/v1", api_key="th-คีย์ของคุณ")
resp = client.chat.completions.create(
    model="thai-hub/auto",   # หรือ local / free / cheap / best / ชื่อโมเดลตรง
    messages=[{"role": "user", "content": "สวัสดี"}],
)
print(resp.choices[0].message.content)
```

| alias | ความหมาย | แพ็กเกจขั้นต่ำ |
|---|---|---|
| `thai-hub/auto` | สายอัตโนมัติตามแพ็กเกจ | ทุกแพ็กเกจ |
| `thai-hub/local` | AI ในเครื่องเท่านั้น (ฟรี) | ทุกแพ็กเกจ |
| `thai-hub/free` | โมเดลฟรี OpenRouter | ทุกแพ็กเกจ |
| `thai-hub/cheap` | โมเดลราคาประหยัด | เริ่มต้น |
| `thai-hub/best` | สายคุณภาพ | โปร |
| ชื่อโมเดลตรง เช่น `jarvis-llama3.1:latest`, `deepseek/deepseek-chat-v3.1` | — | local ทุกแพ็กเกจ / OpenRouter เฉพาะโปร+ |

## โครงสร้างโปรเจกต์

```
app/
├── main.py              # FastAPI + exception handler
├── config.py / db.py    # ตั้งค่า + SQLite (WAL)
├── routers/
│   ├── gateway.py       # /v1/* OpenAI-compatible + โควตา + สตรีม
│   ├── public.py        # หน้าแรก/ราคา/เอกสาร/สมัคร/ล็อกอิน
│   ├── dashboard.py     # ภาพรวม/คีย์/บิล/Playground
│   └── admin.py         # อนุมัติบิล/ผู้ใช้/สถิติ
├── services/
│   ├── providers.py     # ตัวเชื่อม Ollama + OpenRouter (+ คลังโมเดล/ราคา)
│   ├── router_engine.py # สมองสลับโมเดล (alias → สาย failover)
│   ├── usage.py         # โควตา/มิเตอร์/สถิติ
└── templates/ + static/ # หน้าเว็บภาษาไทย (dark theme) + payment-qr.jpg
```

## โฟลว์เงิน

1. ลูกค้าเลือกแพ็กเกจ (รายเดือน/รายปี) → ระบบสร้างบิล (ref + ยอด)
2. หน้าบิลแสดง **รูป QR ของบัญชีรับเงิน** (`app/static/payment-qr.jpg` — รูปเดิมทุกบิล) + เลขบัญชีธนาคาร ลูกค้าสแกน/โอนยอดตามบิล แล้วกด "แจ้งชำระเงิน"
3. แอดมินกด ✓ อนุมัติใน `/admin` → แพ็กเกจ active ทันที (ซื้อซ้ำแพ็กเกจเดิม = ต่อจากวันหมดอายุเดิม)

> เปลี่ยนบัญชีรับเงิน: แก้ `PAYMENT_*` ใน `.env` และวางรูป QR ใหม่ที่ `app/static/payment-qr.jpg`

## ทดสอบแล้ว

- สมัคร/ล็อกอิน/สร้างคีย์/ยกเลิกคีย์ ✓ · ยิง API ผ่าน qwen2.5:7b + jarvis-llama3.1 (ทั้ง non-stream และ stream) ✓
- โควตา/สิทธิ์ตาม tier (403/401/429) ✓ · บิล PromptPay ครบวงจรจนถึงเปิดแพ็กเกจ ✓ · แอดมินอนุมัติ/ปฏิเสธ ✓
