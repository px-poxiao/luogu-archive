"""FastAPI 应用入口。

生命周期：
- 启动：初始化日志、检查数据库/Redis 可用性
- 关停：关闭 httpx / Redis / DB 连接

暂时只挂载健康检查。业务路由会在阶段 2~4 逐步加到 app.api.v1 下。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger, setup_logging
from app.core.redis_client import close_redis, get_redis
from app.crawler.http import close_http_client

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log.info("app.startup", env=settings.APP_ENV, origin=settings.WEB_PUBLIC_ORIGIN)

    # ping redis
    redis = get_redis()
    try:
        await redis.ping()
    except Exception as e:
        log.error("app.redis_unreachable", error=str(e))
        raise

    yield

    await close_http_client()
    await close_redis()
    log.info("app.shutdown")


app = FastAPI(
    title="luogu-archive",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)


# 挂载业务路由
from app.api.v1 import api_v1  # noqa: E402
app.include_router(api_v1)


# 全局异常：把 AppError 子类转成统一 JSON
@app.exception_handler(AppError)
async def app_error_handler(request, exc: AppError):  # noqa: ANN001
    return ORJSONResponse(
        status_code=exc.http_status,
        content={
            "error_code": exc.error_code,
            "message": exc.message,
            "data": exc.data,
        },
    )


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """健康检查。用于监控 / 负载均衡探活。"""
    return {"status": "ok"}


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": settings.APP_NAME,
        "env": settings.APP_ENV,
        "version": "0.1.0",
    }
