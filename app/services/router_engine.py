"""สมองกลาง: แปลง alias -> สาย backend ที่ต้องลองตามลำดับ (failover)"""
import time

from .. import config
from ..api_errors import ApiError
from .providers import BackendError, chat_once, chat_stream, ollama_models, pick_models

ALIAS_INFO = {
    "thai-hub/auto": "เลือกเส้นทางอัตโนมัติ คุ้มค่าสุดตามแพ็กเกจ (แนะนำ)",
    "thai-hub/local": "AI รันในเครื่องเซิร์ฟเวอร์ ฟรี ไม่ออกบิลนอกบ้าน",
    "thai-hub/free": "โมเดลฟรีคุณภาพสูงจาก AI ระดับโลก (Llama 3.3 70B, DeepSeek V3 ฯลฯ)",
    "thai-hub/cheap": "โมเดลพรีเมียมราคาถูกที่งานดี (DeepSeek V3.1, Gemini Flash, GPT-4o-mini)",
    "thai-hub/best": "สายคุณภาพ — ลองตัวที่ฉลาดที่สุดก่อน แล้วค่อยลดหลั่น",
}
# alias นี้ต้องใช้แพ็กเกจ tier ขั้นต่ำเท่าไร
ALIAS_TIER = {"thai-hub/auto": 0, "thai-hub/local": 0, "thai-hub/free": 0,
              "thai-hub/cheap": 1, "thai-hub/best": 2}


async def local_chain() -> list[tuple[str, str]]:
    """โมเดลในเครื่อง เรียงตาม LOCAL_MODELS ใน .env ก่อน แล้วตามที่มีจริง"""
    avail = await ollama_models()
    ordered = [m for m in config.LOCAL_MODELS if m in avail]
    ordered += [m for m in avail if m not in ordered]
    return [("ollama", m) for m in ordered[:3]]


async def resolve_chain(model: str, plan: dict | None) -> list[tuple[str, str]]:
    tier = (plan or {}).get("tier", 0)
    policy = (plan or {}).get("chain", "local_first")

    if model.startswith("thai-hub/"):
        if model not in ALIAS_TIER:
            raise ApiError(404, f"ไม่รู้จักโมเดล '{model}' — ดูรายชื่อที่ /v1/models")
        if tier < ALIAS_TIER[model]:
            raise ApiError(403, f"แพ็กเกจปัจจุบันยังไม่รองรับ '{model}' — อัปเกรดได้ที่หน้า Billing")
        if model == "thai-hub/local":
            chain = await local_chain()
            if not chain:
                raise ApiError(503, "ยังไม่มีโมเดลในเครื่อง (เช็คว่า Ollama รันอยู่และ LOCAL_MODELS ถูกต้อง)")
            return chain
        free = await pick_models("free")
        cheap = await pick_models("cheap")
        if model == "thai-hub/free":
            return [("openrouter", m) for m in free]
        if model == "thai-hub/cheap":
            return [("openrouter", m) for m in cheap]
        if model == "thai-hub/best":
            return [("openrouter", m) for m in (cheap[:2] + free[:1])]
        # thai-hub/auto
        chain: list[tuple[str, str]] = []
        if policy == "quality_first":
            chain += [("openrouter", m) for m in free[:2]]
            if tier >= 1:
                chain += [("openrouter", m) for m in cheap[:2]]
            chain += (await local_chain())[:1]
        else:
            chain += (await local_chain())[:1]
            chain += [("openrouter", m) for m in free[:2]]
            if tier >= 1:
                chain += [("openrouter", m) for m in cheap[:2]]
        return chain

    # เรียกโมเดลในเครื่องตรงๆ ด้วยชื่อ (เช่น jarvis-llama3.1:latest) — ใช้ได้ทุกแพ็กเกจ
    locs = [m for _, m in await local_chain()]
    if model in locs:
        return [("ollama", model)]

    # ส่งชื่อโมเดลตรงๆ จาก OpenRouter (เช่น google/gemini-2.0-flash-001) — เฉพาะแพ็กเกจที่เปิด
    if (plan or {}).get("passthrough"):
        return [("openrouter", model)]
    raise ApiError(403, f"โมเดล '{model}' ใช้ได้เฉพาะแพ็กเกจ Pro ขึ้นไป — หรือใช้ alias thai-hub/* แทน")


async def run_chat(model: str, payload: dict, stream: bool, plan: dict | None):
    """ไล่ลองทีละ backend ตามสาย ตัวไหนตอบกลับมาก่อนชนะ — คืน (provider, model, result, connect_ms)"""
    chain = await resolve_chain(model, plan)
    errors: list[str] = []
    for provider, m in chain:
        t0 = time.time()
        try:
            if stream:
                gen = await chat_stream(provider, m, payload)
            else:
                gen = await chat_once(provider, m, payload)
            return provider, m, gen, int((time.time() - t0) * 1000)
        except BackendError as e:
            errors.append(str(e))
    detail = " | ".join(errors[-3:])
    raise ApiError(502, f"ทุก backend ล้มเหลว: {detail}", "api_error")
