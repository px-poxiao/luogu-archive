"""保存按钮 API。

POST /api/v1/save
Body: { content_type: "article"|"paste"|"user"|"feed"|"judgement"|"problem"|"problem_solution", id: "...", captcha_token?: "..." }

流程（3.md 十一-A.3）：
1. 校验 IP 限流（滑动窗口 60s / 5 次）
2. 若 IP 已进入"需验证"状态 → 先校验 captcha_token
3. 请求合并：若同 target 已有 pending 任务，返回已有 task_id
4. 派发资源队列任务（高优先级队列）
5. 写 SaveRequest 审计
"""
from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Request
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
    id: str = Field(..., min_length=1, max_length=256)
    captcha_token: str | None = None


class SaveResp(BaseModel):
    task_id: str
    merged: bool
    status: str = "queued"


# ============================================================
# 辅助：保存请求限流 + 验证码触发逻辑
# ============================================================

_CAPTCHA_REQUIRED_KEY_PREFIX = "save:captcha_required"

_ARTICLE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ARTICLE_PATH_RE = re.compile(r"^/(?:article|atricle)/([A-Za-z0-9_-]{1,64})/?$", re.IGNORECASE)
_LUOGU_HOSTS = {
    "www.luogu.com.cn",
    "luogu.com.cn",
    "www.luogu.com",
    "luogu.com",
}


def _normalize_article_ident(raw: str) -> str:
    """允许文章保存传入完整链接、路径或纯 article id。"""
    value = raw.strip()
    if not value:
        raise ValidationError("无效的文章 ID")

    if _ARTICLE_ID_RE.fullmatch(value):
        return value

    if value.startswith(("www.luogu.", "luogu.")):
        value = f"https://{value}"

    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        if parsed.netloc.lower() not in _LUOGU_HOSTS:
            raise ValidationError("只支持洛谷文章链接")
        path = parsed.path
    else:
        path = value

    m = _ARTICLE_PATH_RE.fullmatch(path)
    if not m:
        raise ValidationError("文章链接格式应为 /article/{id}")
    return m.group(1)


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
    # 软触发 - 1 分钟
    ok, _count = await limiter.acquire(
        ratelimit_key("save_ip_60s", ip),
        window_sec=settings.SAVE_IP_WINDOW_SEC,
        limit=settings.SAVE_IP_WINDOW_MAX,
    )
    if not ok:
        raise RateLimitError(
            "保存请求过于频繁（1 分钟内 20 次）",
            retry_after_sec=settings.SAVE_IP_WINDOW_SEC,
        )

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


async def _set_captcha_requirement(ip: str) -> None:
    """主动把当前 IP 标记为需要人机验证。"""
    redis = get_redis()
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

    此处"task_id"约定为资源队列任务 id。已有 pending → 复用；否则新派发。
    """
    from app.tasks.actors.crawl import (
        crawl_article,
        crawl_judgement_hi,
        crawl_paste,
        crawl_user_feeds_hi,
        crawl_user_manual,
    )
    from app.tasks.problem_queue import (
        enqueue_problem_list_page,
        enqueue_problem_solution,
    )

    redis = get_redis()

    key = _pending_key(content_type, ident)

    # 尝试读旧 task_id
    old = await redis.get(key)
    if old:
        return old, True

    # 派发
    task_id: str | None = None
    try:
        if content_type == "article":
            msg = crawl_article.send(ident, "manual")
        elif content_type == "paste":
            msg = crawl_paste.send(ident, "manual")
        elif content_type == "user":
            msg = crawl_user_manual.send(int(ident))
        elif content_type == "feed":
            # feed 的 ident 格式 "<uid>" 或 "<uid>:<page>"
            if ":" in ident:
                uid_str, page_str = ident.split(":", 1)
                uid, page = int(uid_str), int(page_str)
            else:
                uid, page = int(ident), 1
            msg = crawl_user_feeds_hi.send(uid, page, "manual")
        elif content_type == "judgement":
            # ident 任意值都忽略
            msg = crawl_judgement_hi.send("manual")
        elif content_type == "problem":
            # 列表页点保存：ident="list" → 扫前 N 页（发现新题 + 更新难度）
            #               ident=数字 → 只扫这一页（admin 内部 / 调试用）
            #               ident=P1001/B2001/CF1A... → 直接检查单题题解开放状态
            ident_norm = ident.strip()
            if ident_norm.lower() == "list":
                # 错峰扫前 30 页（覆盖 1500 道）。每页 11 秒间隔避免 cn 节点限流（0.1 req/s）。
                # 取第一页的消息 id 作为本次保存任务 id。
                first = await enqueue_problem_list_page(1, "manual")
                task_id = first.message_id
                for page in range(2, 31):
                    await enqueue_problem_list_page(
                        page,
                        "manual",
                        delay_ms=(page - 1) * 11_000,
                    )
            elif ident_norm.isdigit():
                page = int(ident_norm)
                queued = await enqueue_problem_list_page(page, "manual")
                task_id = queued.message_id
            else:
                queued = await enqueue_problem_solution(ident_norm.upper(), "manual")
                task_id = queued.message_id
        elif content_type == "problem_solution":
            queued = await enqueue_problem_solution(ident, "manual")
            task_id = queued.message_id
        else:
            raise ValidationError("未知的 content_type")
    except ValueError as e:
        raise ValidationError(f"无效的 id: {ident}") from e

    if task_id is None:
        task_id = msg.message_id
    # 挂 pending 标记，TTL 5 分钟（爬完没这么久，但防止卡死）
    await redis.setex(key, 300, task_id)
    return task_id, False


async def _try_get_pending(content_type: str, ident: str) -> str | None:
    """只读取 pending 任务，不产生新任务；重复点击同一目标不应消耗限流额度。"""
    redis = get_redis()
    return await redis.get(_pending_key(content_type, ident))


# ============================================================
# 端点
# ============================================================

@router.post("/save", response_model=SaveResp)
async def save(req: SaveReq, request: Request) -> SaveResp:
    ip = get_client_ip(request)
    ident = _normalize_article_ident(req.id) if req.content_type == "article" else req.id

    # 1. 同一目标已在队列中时直接合并返回，不消耗限流额度。
    old_task_id = await _try_get_pending(req.content_type, ident)
    if old_task_id:
        return SaveResp(task_id=old_task_id, merged=True)

    # 2. 如果已经进入验证码状态，优先给用户验证机会，避免直接撞 429 冷却。
    if await _need_captcha(ip):
        if settings.CAPTCHA_PROVIDER != "none":
            if not req.captcha_token:
                raise CaptchaRequired("请先完成人机验证")
            ok = await verify_captcha(req.captcha_token, ip=ip)
            if not ok:
                raise CaptchaRequired("人机验证失败，请重试")
        await _clear_captcha_requirement(ip)
    else:
        await _check_ip_limits(ip)

    # 3. 请求合并 / 派发
    task_id, merged = await _try_merge_or_enqueue(req.content_type, ident)

    # 4. 审计
    async with db_session() as session:
        session.add(
            SaveRequest(
                ip=ip,
                user_agent=request.headers.get("user-agent", "")[:500],
                target_type=req.content_type,
                target_id=ident,
                result="merged" if merged else "ok",
            )
        )
        await session.commit()

    return SaveResp(task_id=task_id, merged=merged)


@router.get("/save/status/{task_id}")
async def save_status(task_id: str) -> dict:
    """查询任务状态。

    保存接口用 Redis pending key 暴露用户可见状态，不直接泄露内部队列结构。
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
