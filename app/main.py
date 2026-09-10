"""Thai API Hub — API Gateway + ระบบขาย API รายเดือน/รายปี"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .api_errors import ApiError
from .routers import admin, dashboard, gateway, public
from .services import bot as tg_bot
from .services import monitor as monitor_svc
from .services.security import rate_limit_middleware, security_headers_middleware

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    tasks = []
    if config.TELEGRAM_BOT_TOKEN:
        tasks.append(asyncio.create_task(tg_bot.run_polling()))
    tasks.append(asyncio.create_task(monitor_svc.monitor_loop()))
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Thai API Hub", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

# Security headers ก่อน แล้ว rate limit (ทำงานจากนอกสุดเข้าใน: ลงทะเบียนหลัง = ทำงานก่อน)
app.middleware("http")(security_headers_middleware)
app.middleware("http")(rate_limit_middleware)


@app.exception_handler(ApiError)
async def api_error_handler(_request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status,
                        content={"error": {"message": exc.message, "type": exc.etype, "code": exc.status}})


app.include_router(public.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(gateway.router)
