"""侵权 / 删除申请工单（匿名提交，管理员审核）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_ip
from app.core.db import get_db
from app.core.exceptions import RateLimitError
from app.core.ratelimit import SlidingWindowLimiter, ratelimit_key
from app.core.redis_client import get_redis
from app.models._common import TakedownStatus
from app.models.task import TakedownRequest

router = APIRouter(tags=["takedown"])


class TakedownReq(BaseModel):
    requester_name: str | None = Field(None, max_length=128)
    requester_contact: str | None = Field(None, max_length=256)
    target_type: str = Field(..., max_length=32)
    target_id: str = Field(..., min_length=1, max_length=64)
    reason: str = Field(..., min_length=10, max_length=5000)


@router.post("/takedown")
async def submit_takedown(
    req: TakedownReq,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    # 限流：同 IP 每小时最多 5 次
    ip = get_client_ip(request)
    redis = get_redis()
    limiter = SlidingWindowLimiter(redis)
    ok, _ = await limiter.acquire(
        ratelimit_key("takedown_ip", ip),
        window_sec=3600,
        limit=5,
    )
    if not ok:
        raise RateLimitError("申请过于频繁，请稍后再试", retry_after_sec=1800)

    row = TakedownRequest(
        requester_name=req.requester_name,
        requester_contact=req.requester_contact,
        target_type=req.target_type,
        target_id=req.target_id,
        reason=req.reason,
        status=TakedownStatus.pending,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "status": row.status.value}
