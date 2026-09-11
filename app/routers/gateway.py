"""OpenAI-compatible Gateway: /v1/chat/completions + /v1/models"""
import json
import time

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import config, db, security
from ..api_errors import ApiError
from ..services import router_engine
from ..services import usage as usage_svc
from ..services.providers import ollama_models, pick_models, price_map

router = APIRouter()

ALLOWED_FIELDS = {"messages", "temperature", "top_p", "max_tokens", "stop",
                  "presence_penalty", "frequency_penalty", "seed", "response_format", "n"}


def _bearer(authorization: str) -> str:
    if not authorization:
        raise ApiError(401, "ไม่พบ API key — ส่งมาใน header: Authorization: Bearer th-xxxxxxxx")
    parts = authorization.split(" ", 1)
    key = parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else parts[0].strip()
    if not key:
        raise ApiError(401, "API key ว่างเปล่า")
    return key


def _auth(authorization: str):
    key = _bearer(authorization)
    row = db.q("SELECT * FROM api_keys WHERE key_hash=? AND revoked=0",
               (security.key_hash(key),), one=True)
    if not row:
        raise ApiError(401, "API key ไม่ถูกต้องหรือถูกยกเลิกแล้ว")
    user = db.q("SELECT * FROM users WHERE id=? AND is_active=1", (row["user_id"],), one=True)
    if not user:
        raise ApiError(403, "บัญชีนี้ถูกระงับการใช้งาน")
    return user, row


def _cost(provider: str, model: str, pt: int, ct: int) -> float:
    if provider != "openrouter":
        return 0.0
    pm = price_map().get(model)
    if not pm:
        return 0.0
    return pt / 1_000_000 * pm[0] + ct / 1_000_000 * pm[1]


@router.get("/v1/models")
async def list_models(authorization: str = Header(default="")):
    _auth(authorization)
    data, seen = [], set()
    for alias in router_engine.ALIAS_INFO:
        data.append({"id": alias, "object": "model", "created": 0, "owned_by": "thai-api-hub"})
        seen.add(alias)
    for m in await ollama_models():
        if m not in seen:
            data.append({"id": m, "object": "model", "created": 0, "owned_by": "local"})
            seen.add(m)
    if config.OPENROUTER_API_KEY:
        for m in await pick_models("free") + await pick_models("cheap"):
            if m not in seen:
                data.append({"id": m, "object": "model", "created": 0, "owned_by": "openrouter"})
                seen.add(m)
    return {"object": "list", "data": data}


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, authorization: str = Header(default="")):
    user, key = _auth(authorization)
    plan, source = usage_svc.get_active_plan(user)
    if not plan:
        raise ApiError(402, "ยังไม่มีแพ็กเกจที่ใช้งานได้ (ทดลองใช้อาจหมดอายุแล้ว) — "
                            "สมัคร/ต่ออายุที่หน้า Billing ของเว็บ Thai API Hub")
    quota_info = usage_svc.check_quota(user["id"], key["id"], plan)

    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, "รูปแบบ JSON ไม่ถูกต้อง")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ApiError(400, "ต้องส่ง field 'messages' เป็น list ที่ไม่ว่าง")
    model = (body.get("model") or "thai-hub/auto").strip()
    stream = bool(body.get("stream"))
    payload = {k: v for k, v in body.items() if k in ALLOWED_FIELDS}
    payload["messages"] = messages

    pt_est = sum(usage_svc.est_tokens(str(m.get("content") or "")) for m in messages)
    t0 = time.time()
    try:
        provider, backend_model, result, _connect_ms, attempts = await router_engine.run_chat(
            model, payload, stream, plan)
    except ApiError:
        usage_svc.record(user["id"], key["id"], model, "none", "", 0, 0,
                         int((time.time() - t0) * 1000), status="fail")
        raise

    base_headers = {
        "X-Thai-Hub-Backend": f"{provider}:{backend_model}",
        "X-Thai-Hub-Attempts": str(attempts),
        "X-Thai-Hub-Failover": "true" if attempts > 1 else "false",
        "X-RateLimit-Limit-Requests": str(quota_info["daily_limit"]),
        "X-RateLimit-Remaining-Requests": str(max(0, quota_info["daily_remaining"] - 1)),
        "X-RateLimit-Limit-Tokens": str(quota_info["tokens_limit"]),
        "X-RateLimit-Remaining-Tokens": str(max(0, quota_info["tokens_remaining"])),
        "X-RateLimit-Limit-RPM": str(quota_info["rpm_limit"]),
        "X-RateLimit-Remaining-RPM": str(max(0, quota_info["rpm_remaining"] - 1)),
    }
    if quota_info["warning"]:
        base_headers["X-Thai-Hub-Warning"] = quota_info["warning"]

    if not stream:
        latency = int((time.time() - t0) * 1000)
        u = result.get("usage") or {}
        content = ""
        try:
            content = result["choices"][0]["message"].get("content") or ""
        except Exception:
            pass
        pt = int(u.get("prompt_tokens") or pt_est)
        ct = int(u.get("completion_tokens") or usage_svc.est_tokens(content))
        cost = _cost(provider, backend_model, pt, ct)
        usage_svc.record(user["id"], key["id"], model, provider, backend_model,
                         pt, ct, latency, "ok", cost)
        resp_headers = {
            **base_headers,
            "X-Thai-Hub-Latency-Ms": str(latency),
            "X-RateLimit-Remaining-Tokens": str(max(0, quota_info["tokens_remaining"] - (pt + ct))),
        }
        return JSONResponse(result, headers=resp_headers)

    # ---------- streaming ----------
    ct_chars = 0

    async def sse():
        nonlocal ct_chars
        u_final = None
        try:
            async for data in result:
                yield f"data: {data}\n\n"
                try:
                    j = json.loads(data)
                except Exception:
                    continue
                if isinstance(j.get("usage"), dict) and j["usage"].get("prompt_tokens"):
                    u_final = j["usage"]
                for ch in j.get("choices") or []:
                    d = ch.get("delta") or {}
                    c = d.get("content")
                    if isinstance(c, str):
                        ct_chars += len(c)
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield "data: " + json.dumps(
                {"error": {"message": f"สตรีมถูกตัดกลางคัน: {e}", "type": "api_error"}}) + "\n\n"
        finally:
            latency = int((time.time() - t0) * 1000)
            if u_final:
                pt = int(u_final.get("prompt_tokens") or pt_est)
                ct = int(u_final.get("completion_tokens") or usage_svc.est_tokens("x" * ct_chars))
            else:
                pt, ct = pt_est, usage_svc.est_tokens("x" * ct_chars)
            usage_svc.record(user["id"], key["id"], model, provider, backend_model,
                             pt, ct, latency, "ok", _cost(provider, backend_model, pt, ct))

    stream_headers = {
        **base_headers,
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(sse(), media_type="text/event-stream", headers=stream_headers)

