"""ตัวเชื่อม backend: Ollama (ในเครื่อง) และ OpenRouter — ทั้งคู่พูดภาษา OpenAI API"""
import logging
import time

import httpx

from .. import config

log = logging.getLogger("tah.providers")

FREE_PRIORITY = [
    "openrouter/free",
    "google/gemma-4-31b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "mistralai/mistral-small-3.2-24b-instruct:free",
]
CHEAP_PRIORITY = [
    "google/gemini-2.5-flash-lite",
    "mistralai/mistral-small-24b-instruct-2501",
    "deepseek/deepseek-chat",
    "meta-llama/llama-3.3-70b-instruct",
    "openai/gpt-4o-mini",
    "google/gemini-2.5-flash",
]

_cache = {"models_ts": 0.0, "models": [], "ollama_ts": 0.0, "ollama": []}


class CircuitBreaker:
    """Circuit Breaker ป้องกันการรอ Timeout ซ้ำๆ เมื่อ backend/model มีปัญหา"""
    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 60.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures: dict[str, int] = {}
        self._tripped_until: dict[str, float] = {}

    def _key(self, provider: str, model: str) -> str:
        return f"{provider}:{model}"

    def is_available(self, provider: str, model: str) -> bool:
        key = self._key(provider, model)
        tripped = self._tripped_until.get(key, 0.0)
        now = time.time()
        if tripped > now:
            return False
        if tripped != 0.0:
            # Cooldown ครบแล้ว ให้เข้าสู่สถานะ Half-Open เพื่อลองใหม่
            self._tripped_until.pop(key, None)
            self._failures[key] = 0
        return True

    def record_success(self, provider: str, model: str) -> None:
        key = self._key(provider, model)
        self._failures.pop(key, None)
        self._tripped_until.pop(key, None)

    def record_failure(self, provider: str, model: str) -> None:
        key = self._key(provider, model)
        count = self._failures.get(key, 0) + 1
        self._failures[key] = count
        if count >= self.failure_threshold:
            self._tripped_until[key] = time.time() + self.cooldown_seconds
            log.warning("Circuit breaker tripped for %s: cooldown %.0fs (failures: %d)",
                        key, self.cooldown_seconds, count)


circuit_breaker = CircuitBreaker()


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
        circuit_breaker.record_failure(provider, model)
        raise BackendError(f"{provider}: เชื่อมต่อไม่สำเร็จ ({type(e).__name__})")
    if r.status_code != 200:
        circuit_breaker.record_failure(provider, model)
        raise BackendError(f"{provider}/{model}: HTTP {r.status_code} {r.text[:160]}")
    circuit_breaker.record_success(provider, model)
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
        circuit_breaker.record_failure(provider, model)
        raise BackendError(f"{provider}: เชื่อมต่อไม่สำเร็จ ({type(e).__name__})")
    if resp.status_code != 200:
        text = (await resp.aread()).decode("utf-8", "replace")[:160]
        await resp.aclose()
        await client.aclose()
        circuit_breaker.record_failure(provider, model)
        raise BackendError(f"{provider}/{model}: HTTP {resp.status_code} {text}")

    circuit_breaker.record_success(provider, model)

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

