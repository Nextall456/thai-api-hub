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

# Set log level to INFO for all loggers
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    bot_task = None
    if config.TELEGRAM_BOT_TOKEN:
        logging.getLogger(__name__).info("Starting Telegram bot polling task...")
        bot_task = asyncio.create_task(tg_bot.run_polling())
    yield
    if bot_task:
        bot_task.cancel()


app = FastAPI(title="Thai API Hub", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.exception_handler(ApiError)
async def api_error_handler(_request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status,
                        content={"error": {"message": exc.message, "type": exc.etype, "code": exc.status}})


app.include_router(public.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(gateway.router)
