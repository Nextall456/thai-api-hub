"""Thai API Hub — API Gateway + ระบบขาย API รายเดือน/รายปี"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .api_errors import ApiError
from .routers import admin, dashboard, gateway, public


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    yield


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
