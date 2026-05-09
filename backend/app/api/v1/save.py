"""保存按钮 API。

POST /api/v1/save
Body: { content_type: "article"|"paste"|"user"|"feed"|"judgement"|"problem"|"problem_solution", id: "...", captcha_token?: "..." }

流程（3.md 十一-A.3）：
1. 校验 IP 限流（滑动窗口 60s / 5 次）
2. 若 IP 已进入"需验证"状态 → 先校验 captcha_token
3. 请求合并：若同 target 已有 pending 任务，返回已有 task_id
4. 派发 Dramatiq 任务（高优先级队列）
5. 写 SaveRequest 审计
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import get_client_ip
from app.core.captcha import verify_captcha
from app.core.config import settings
from app.core.db import db_session
from app.core.exceptions import (
    CaptchaRequired,
    RateLimitError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.ratelimit import SlidingWindowLimiter, ratelimit_key
from app.core.redis_client import get_redis
from app.models.task import SaveRequest

router = APIRouter(tags=["save"])
log = get_logger(__name__)

ContentType = Literal[
    "article", "paste", "user", "feed", "judgement", "problem", "problem_solution"
]


class SaveReq(BaseModel):
    content_type: ContentType
    id: str = Field(..., min_length=1, max_length=64)
    captcha_token: str | None = None


class SaveResp(BaseModel):
    task_id: str
    merged: bool
    status: str = "queued"


# ============================================================
# 辅助：保存请求限流 + 验证码触发逻辑
# ============================================================

_CAPTCHA_REQUIRED_KEY_PREFIX = "save:captcha_required"


def _captcha_required_key(ip: str) -> str:
    return f"{_CAPTCHA_REQUIRED_KEY_PREFIX}:{ip}"


async def _check_ip_limits(ip: str) -> None:
    """两级检查：
    1) 60 秒 5 次硬限流（超则 429）
    2) 1 分钟 3 次 / 10 分钟 10 次软触发 → 要求下次验证码
    """
    redis = get_redis()
    limiter = SlidingWindowLimiter(redis)

    # 硬限流
    ok, _count = await limiter.acquire(
        ratelimit_key("save_ip_60s", ip),
        window_sec=settings.SAVE_IP_WINDOW_SEC,
        limit=settings.SAVE_IP_WINDOW_MAX,
    )
    if not ok:
        raise RateLimitError(
            "保存请求过于频繁（60 秒内 5 次）",
            retry_after_sec=settings.SAVE_IP_WINDOW_SEC,
        )

    # 软触发 - 1 分钟
    ok_soft_1m, _ = await limiter.acquire(
        ratelimit_key("save_ip_captcha_1m", ip),
        window_sec=60,
        limit=settings.CAPTCHA_TRIGGER_SAVE_PER_MIN,
    )
    # 软触发 - 10 分钟
    ok_soft_10m, _ = await limiter.acquire(
        ratelimit_key("save_ip_captcha_10m", ip),
        window_sec=600,
        limit=settings.CAPTCHA_TRIGGER_SAVE_PER_10MIN,
    )
    if not ok_soft_1m or not ok_soft_10m:
        # 打上"需要验证码"标记，10 分钟内所有保存都得验
        await redis.setex(_captcha_required_key(ip), 600, "1")


async def _need_captcha(ip: str) -> bool:
    redis = get_redis()
    return await redis.exists(_captcha_required_key(ip)) > 0


async def _clear_captcha_requirement(ip: str) -> None:
    """验证码验证通过后重置。"""
    redis = get_redis()
    await redis.delete(_captcha_required_key(ip))


# ============================================================
# 请求合并：同 target 已有 pending 任务时共享结果
# ============================================================

_PENDING_PREFIX = "save:pending"


def _pending_key(content_type: str, ident: str) -> str:
    return f"{_PENDING_PREFIX}:{content_type}:{ident}"


async def _try_merge_or_enqueue(
    content_type: ContentType, ident: str
) -> tuple[str, bool]:
    """返回 (task_id, merged)。

    此处"task_id"约定为 Dramatiq 消息 id。已有 pending → 复用；否则新派发。
    """
    from app.tasks.actors.crawl import (
        crawl_article,
        crawl_judgement,
        crawl_paste,
        crawl_problem_list_page,
        crawl_problem_solution,
        crawl_user,
        crawl_user_feeds,
    )

    redis = get_redis()
    key = _pending_key(content_type, ident)

    # 尝试读旧 task_id
    old = await redis.get(key)
    if old:
        return old, True

    # 派发
    if content_type == "article":
        msg = crawl_article.send(ident, "manual")
    elif content_type == "paste":
        msg = crawl_paste.send(ident, "manual")
    elif content_type == "user":
        msg = crawl_user.send(int(ident), "manual")
    elif content_type == "feed":
        # feed 的 ident 格式 "<uid>" 或 "<uid>:<page>"
        if ":" in ident:
            uid_str, page_str = ident.split(":", 1)
            uid, page = int(uid_str), int(page_str)
        else:
            uid, page = int(ident), 1
        msg = crawl_user_feeds.send(uid, page, "manual")
    elif content_type == "judgement":
        msg = crawl_judgement.send("manual")
    elif content_type == "problem":
        msg = crawl_problem_list_page.send(int(ident), "manual")
    elif content_type == "problem_solution":
        msg = crawl_problem_solution.send(ident, "manual")
    else:
        raise ValidationError("未知的 content_type")

    task_id = msg.message_id
    # 挂 pending 标记，TTL 5 分钟（爬完没这么久，但防止卡死）
    await redis.setex(key, 300, task_id)
    return task_id, False


# ============================================================
# 端点
# ============================================================

@router.post("/save", response_model=SaveResp)
async def save(req: SaveReq, request: Request) -> SaveResp:
    ip = get_client_ip(request)

    # 1. IP 限流
    await _check_ip_limits(ip)

    # 2. 验证码检查
    if await _need_captcha(ip):
        if not req.captcha_token:
            raise CaptchaRequired("请先完成人机验证")
        ok = await verify_captcha(req.captcha_token, ip=ip)
        if not ok:
            raise CaptchaRequired("人机验证失败，请重试")
        await _clear_captcha_requirement(ip)

    # 3. 请求合并 / 派发
    task_id, merged = await _try_merge_or_enqueue(req.content_type, req.id)

    # 4. 审计
    async with db_session() as session:
        session.add(
            SaveRequest(
                ip=ip,
                user_agent=request.headers.get("user-agent", "")[:500],
                target_type=req.content_type,
                target_id=req.id,
                result="merged" if merged else "ok",
            )
        )
        await session.commit()

    return SaveResp(task_id=task_id, merged=merged)


@router.get("/save/status/{task_id}")
async def save_status(task_id: str) -> dict:
    """查询任务状态。

    Dramatiq 原生没有"任务状态 API"。最简：看 Redis 是否还有 pending key 决定。
    更精细需要接一个结果后端，后续加。这里先给前端轮询方案。
    """
    redis = get_redis()
    # 扫描 pending keys 找 task_id（开发期先用，生产有结果后端后再优化）
    # 简化：我们不扫描全部 pending，而是告诉客户端"请等几秒再刷新数据"
    exists_pending = False
    async for _ in redis.scan_iter(match=f"{_PENDING_PREFIX}:*", count=50):
        val = await redis.get(_)
        if val == task_id:
            exists_pending = True
            break
    return {
        "task_id": task_id,
        "status": "pending" if exists_pending else "done",
    }
