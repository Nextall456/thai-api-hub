"""ตัวเชื่อม backend: Ollama (ในเครื่อง) และ OpenRouter — ทั้งคู่พูดภาษา OpenAI API"""
import logging
import time

import httpx

from .. import config

log = logging.getLogger("tah.providers")

FREE_PRIORITY = [
    "deepseek/deepseek-chat-v3-0324:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-235b-a22b:free",
    "google/gemma-3-27b-it:free",
    "mistralai/mistral-small-3.2-24b-instruct:free",
    "deepseek/deepseek-r1-0528:free",
]
CHEAP_PRIORITY = [
    "deepseek/deepseek-chat-v3.1",
    "google/gemini-2.0-flash-001",
    "openai/gpt-4o-mini",
    "google/gemini-2.5-flash",
    "meta-llama/llama-3.1-8b-instruct",
    "mistralai/mistral-nemo",
]

_cache = {"models_ts": 0.0, "models": [], "ollama_ts": 0.0, "ollama": []}


class BackendError(Exception):
    """backend นี้ใช้ไม่ได้ — สาย failover จะข้ามไปตัวถัดไป"""


async def fetch_openrouter_models(force: bool = False) -> list[dict]:
    """รายการโมเดลของ OpenRouter + ราคาต่อ 1M tokens (แคช 1 ชม.)"""
    now = time.time()
    if not force and _cache["models"] and now - _cache["models_ts"] < 3600:
        return _cache["models"]
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{config.OPENROUTER_BASE}/models")
            r.raise_for_status()
            items = r.json().get("data", [])
        models = []
        for m in items:
            pricing = m.get("pricing") or {}
            try:
                pp = float(pricing.get("prompt") or 0) * 1_000_000
                cp = float(pricing.get("completion") or 0) * 1_000_000
            except ValueError:
                pp = cp = 0.0
            models.append({
                "id": m.get("id", ""),
                "name": m.get("name", m.get("id", "")),
                "ctx": int(m.get("context_length") or 0),
                "prompt_price": pp,
                "completion_price": cp,
            })
        if models:
            _cache.update(models_ts=now, models=models)
        return _cache["models"]
    except Exception as e:
        log.warning("fetch openrouter models failed: %s", e)
        return _cache["models"]


def price_map() -> dict[str, tuple[float, float]]:
    return {m["id"]: (m["prompt_price"], m["completion_price"]) for m in _cache["models"]}


async def pick_models(kind: str) -> list[str]:
    """เลือกโมเดลฟรี / ราคาถูก โดยตรวจกับคลังจริงของ OpenRouter ถ้าหาได้"""
    static = FREE_PRIORITY if kind == "free" else CHEAP_PRIORITY
    models = await fetch_openrouter_models()
    if not models:
        return static
    by_id = {m["id"]: m for m in models}
    ids = [i for i in static if i in by_id]
    if kind == "free":
        dyn = [m["id"] for m in models if m["prompt_price"] == 0 and m["completion_price"] == 0
               and m["ctx"] >= 32_000]
    else:
        dyn = [m["id"] for m in models
               if 0 < m["prompt_price"] <= 1.0 and ":free" not in m["id"] and m["ctx"] >= 32_000]
    for i in dyn:
        if i not in ids:
            ids.append(i)
        if len(ids) >= 6:
            break
    for i in static:
        if len(ids) >= 6:
            break
        if i not in ids:
            ids.append(i)
    return ids[:6]


async def ollama_models() -> list[str]:
    """โมเดลที่มีจริงใน Ollama (แคช 60 วิ) — คืน [] ถ้า Ollama ไม่ทำงาน"""
    now = time.time()
    if now - _cache["ollama_ts"] < 60:
        return _cache["ollama"]
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{config.OLLAMA_BASE_URL}/api/tags")
            names = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        names = []
    _cache.update(ollama_ts=now, ollama=names)
    return names


def _base(provider: str) -> str:
    # OpenRouter base มี /v1 มาให้แล้ว ส่วน Ollama ต้องเติม /v1 เอง
    if provider == "ollama":
        return f"{config.OLLAMA_BASE_URL}/v1"
    return config.OPENROUTER_BASE


def _headers(provider: str) -> dict:
    if provider == "ollama":
        return {"Authorization": "Bearer ollama"}
    return {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}".strip(),
        "HTTP-Referer": config.SITE_URL,
        "X-Title": config.SITE_NAME,
    }


def _guard(provider: str) -> None:
    """เช็คว่า backend นี้พร้อมใช้หรือยัง — ไม่พร้อมให้ข้ามไปตัวถัดไปทันที"""
    if provider == "openrouter" and not config.OPENROUTER_API_KEY:
        raise BackendError("เซิร์ฟเวอร์ยังไม่ได้ตั้งค่า OPENROUTER_API_KEY (ผู้ดูแลใส่ในไฟล์ .env ได้)")


async def chat_once(provider: str, model: str, payload: dict, timeout: float = 180.0) -> dict:
    _guard(provider)
    body = {**payload, "model": model, "stream": False}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0)) as c:
            r = await c.post(f"{_base(provider)}/chat/completions", json=body,
                             headers=_headers(provider))
    except httpx.HTTPError as e:
        raise BackendError(f"{provider}: เชื่อมต่อไม่สำเร็จ ({type(e).__name__})")
    if r.status_code != 200:
        raise BackendError(f"{provider}/{model}: HTTP {r.status_code} {r.text[:160]}")
    return r.json()


async def chat_stream(provider: str, model: str, payload: dict, timeout: float = 300.0):
    """คืน async generator ที่ yield ข้อมูล JSON ทีละ chunk (ตัด SSE prefix ออกแล้ว)"""
    _guard(provider)
    body = {**payload, "model": model, "stream": True}
    if provider == "openrouter":
        body["stream_options"] = {"include_usage": True}
    try:
        client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0))
        req = client.build_request("POST", f"{_base(provider)}/chat/completions",
                                   json=body, headers=_headers(provider))
        resp = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        raise BackendError(f"{provider}: เชื่อมต่อไม่สำเร็จ ({type(e).__name__})")
    if resp.status_code != 200:
        text = (await resp.aread()).decode("utf-8", "replace")[:160]
        await resp.aclose()
        await client.aclose()
        raise BackendError(f"{provider}/{model}: HTTP {resp.status_code} {text}")

    async def gen():
        try:
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                if data:
                    yield data
        finally:
            await resp.aclose()
            await client.aclose()

    return gen()
