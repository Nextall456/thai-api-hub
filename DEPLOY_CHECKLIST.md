# ✅ Thai API Hub - Deployment Checklist สุดท้าย

> ใช้ไฟล์นี้เช็กว่าทุกอย่างพร้อมขายจริงแล้ว

---

## 1. ตั้งค่า Environment Variables บน Railway

ไปที่ **Railway Dashboard → Project `thai-api-hub` → Service `thai-api-hub` → Variables** ใส่ครบทุกตัว:

| Variable | ค่า | หมายเหตุ |
|---|---|---|
| `SECRET_KEY` | `tah_prod_Kx9mQ2vR7wZ4nB8c3Ld5fH1jS6aY0eT` | แรนดอมยาว 32+ ตัว |
| `ADMIN_EMAILS` | `next.all.98@gmail.com` | คั่นด้วย comma ถ้าหลายอีเมล |
| `PAYMENT_BANK` | `ธนาคารแลนด์แอนด์เฮ้าส์` |  |
| `PAYMENT_ACCOUNT_NO` | `005 2036481` |  |
| `PAYMENT_ACCOUNT_NAME` | `คำรณ โพธิ์มะณี` |  |
| `AUTO_VERIFY_PAYMENT` | `false` | `true` = อนุมัติทันที, `false` = รอแอดมิน |
| `OPENROUTER_API_KEY` | `sk-or-xxxxxxxxxxxx` | **สำคัญ**: ถ้าไม่ใส่ จะใช้ได้แค่ Local AI (qwen2.5, jarvis, llama3.2) |
| `TELEGRAM_BOT_TOKEN` | `123456789:AAxxxxxxxxxxxxxxx` | จาก @BotFather |
| `TELEGRAM_CHAT_ID` | `-1001234567890` | Chat ID กลุ่ม/ส่วนตัว (ขึ้นต้นด้วย -) |
| `SITE_NAME` | `Thai API Hub` |  |
| `SITE_URL` | `https://aimoneyfree.online` | จะใช้หลัง DNS propagate |
| `TRIAL_DAYS` | `7` |  |

> ⚠️ กด **Save** แล้วรอ Redeploy อัตโนมัติ (หรือ `railway up`)

---

## 2. ตั้งค่า DNS ที่ Namecheap

เข้า **Domain List → Manage → Advanced DNS** ลบ A/CNAME เก่าออก แล้วเพิ่ม:

| Type | Host | Value | TTL |
|---|---|---|---|
| **CNAME** | `@` | `7pumj9ya.up.railway.app` | Automatic |
| **TXT** | `_railway-verify` | `railway-verify=d4b1433abfeecd156ec0a20fdcc078800a6c9b24f4a883977303a25a77843afc` | Automatic |

> 💡 หากมี `www` ให้เพิ่ม CNAME `www` → `7pumj9ya.up.railway.app` ด้วย

**รอ DNS propagate 5-60 นาที** แล้วทดสอบ: `https://aimoneyfree.online/health`

---

## 3. ทดสอบครบวงจร (รันหลัง DNS + Env vars พร้อม)

```bash
# 1. Health check
curl https://aimoneyfree.online/health
# {"ok":true,"service":"Thai API Hub","time":"..."}

# 2. สมัครสมาชิกใหม่
curl -X POST https://aimoneyfree.online/signup \
  -d "name=TestUser&email=test@example.com&password=test123456"
# → redirect 303 ไป /dashboard, ตรวจสอบได้ Telegram แจ้งเตือน

# 3. ล็อกอิน + สร้าง API Key
# เข้าเว็บ https://aimoneyfree.online/login ด้วยเบราว์เซอร์
# ไป /dashboard/keys กด "สร้างคีย์ใหม่" → copy key (th-xxxxx)

# 4. เรียก API จริง
KEY=th-xxxxxxxxx  # key ที่ได้
curl -X POST https://aimoneyfree.online/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"thai-hub/auto","messages":[{"role":"user","content":"สวัสดี"}]}'
# → 200 OK, ได้คำตอบจาก AI

# 5. Streaming test
curl -N -X POST https://aimoneyfree.online/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"thai-hub/auto","stream":true,"messages":[{"role":"user","content":"นับ 1 ถึง 5"}]}'
# → ได้ข้อความไหลแบบ SSE

# 6. ทดสอบ billing
# เข้า /dashboard/billing → เลือกแพ็กเกจ → จะได้ QR + เลขบัญชี
# โอนจริง → กด "แจ้งชำระเงินแล้ว" → Telegram แจ้งเตือนแอดมิน
# แอดมินเข้า /admin กด "อนุมัติ" → Telegram แจ้ง "อนุมัติชำระเงิน (แอดมิน)"
# ลูกค้าใช้งานได้ทันที

# 7. Admin verify/reject test
# /admin → ดูรายการ pending → กด "ปฏิเสธ" → Telegram แจ้ง "ปฏิเสธการชำระเงิน"
```

---

## 4. Production URLs

| บริการ | URL |
|---|---|
| **เว็บหลัก** | https://aimoneyfree.online |
| **Health Check** | https://aimoneyfree.online/health |
| **API Endpoint** | https://aimoneyfree.online/v1/chat/completions |
| **Models List** | https://aimoneyfree.online/v1/models |
| **Dashboard** | https://aimoneyfree.online/dashboard |
| **Admin Panel** | https://aimoneyfree.online/admin |

---

## 5. ข้อมูลสำคัญสำหรับลูกค้า

### API Key Format
```
th-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
(48 hex chars หลัง th-)
```

### Model Aliases
| Alias | ความหมาย | แพ็กเกจขั้นต่ำ |
|---|---|---|
| `thai-hub/auto` | อัตโนมัติ (แนะนำ) | ทุกแพ็กเกจ |
| `thai-hub/local` | AI ในเครื่อง (ฟรี) | ทุกแพ็กเกจ |
| `thai-hub/free` | โมเดลฟรีคุณภาพสูง | ทุกแพ็กเกจ |
| `thai-hub/cheap` | โมเดลพรีเมียมราคาถูก | เริ่มต้น (฿199) |
| `thai-hub/best` | สายคุณภาพสูงสุด | โปร (฿499) |

### โควตาต่อแพ็กเกจ
| แพ็กเกจ | คำขอ/วัน | Tokens/เดือน | ราคา/เดือน | ราคา/ปี |
|---|---|---|---|---|
| ทดลองฟรี | 30 | 300,000 | ฟรี (7 วัน) | - |
| เริ่มต้น | 300 | 3 ล้าน | ฿199 | ฿1,990 |
| โปร | 1,500 | 15 ล้าน | ฿499 | ฿4,990 |
| ธุรกิจ | 10,000 | 80 ล้าน | ฿1,499 | ฿14,990 |

---

## 6. การบำรุงรักษา

| งาน | ความถี่ | วิธี |
|---|---|---|
| Backup SQLite | รายวัน | `cp data/thaiapihub.db backups/thaiapihub_$(date +%F).db` |
| Log errors | ตลอดเวลา | `railway logs --tail 100` |
| Update deps | รายเดือน | `pip install -r requirements.txt --upgrade` |
| Rotate SECRET_KEY | รายปี | Gen ใหม่ + update Railway variable |

---

## 7. Troubleshooting ด่วน

| อาการ | สาเหตุ/แก้ไข |
|---|---|
| `/health` 502 | Service down → `railway logs` ดู error |
| API 401 | Key ผิด/หมดอายุ → สร้างใหม่ที่ /dashboard/keys |
| API 403 | ใช้ alias ไม่ได้ในแพ็กเกจนี้ → อัปเกรดหรือใช้ alias ที่อนุญาต |
| API 429 | เกินโควตา → รอ reset (เที่ยงคืน/ต้นเดือน) หรืออัปเกรด |
| API 502 | Backend ล้ม → รอ failover, เช็ค `OPENROUTER_API_KEY` |
| Telegram ไม่แจ้ง | ตรวจ `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` |
| DNS ไม่ resolve | รอ 60 นาที, เช็ค `nslookup aimoneyfree.online` |

---

## 8. โค้ดฐาน (GitHub + Railway)

| ที่เก็บ | URL |
|---|---|
| **GitHub Repo** | https://github.com/Nextall456/thai-api-hub |
| **Railway Project** | https://railway.com/project/9240defb-6d59-4cf9-a036-61018bba620f |
| **Production (Railway)** | https://thai-api-hub-production.up.railway.app |
| **Custom Domain** | https://aimoneyfree.online |

---

## 🎉 เสร็จแล้ว!

เมื่อ checklist ครบทุกข้อ → **Thai API Hub พร้อมขายจริง**

> ขาย API ได้เลย: แชร์ลิงก์ https://aimoneyfree.online ให้ลูกค้า สมัคร → ได้ Key → ใช้งานทันที