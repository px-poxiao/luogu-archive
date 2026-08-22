"""删除申请的地址规范化和内容软隐藏服务。"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ValidationError
from app.models.task import ContentSuppression, TakedownRequest
from app.models._common import utcnow

PUBLIC_MESSAGE = "该内容已根据删除申请停止公开展示。"
SUPPORTED_TYPES = {"user", "article", "paste", "feed"}
ALLOWED_HOSTS = {
    "luogu.com.cn", "www.luogu.com.cn", "luogu.com", "www.luogu.com",
    "luogu.ac.cn", "www.luogu.ac.cn", "lg.px-poxiao.cn",
    "px-poxiao.cn", "www.px-poxiao.cn",
}
PATHS = {
    "user": re.compile(r"^/user/(\d+)/?$"),
    "article": re.compile(r"^/article/([A-Za-z0-9]+)/?$"),
    "paste": re.compile(r"^/paste/([A-Za-z0-9]+)/?$"),
    "feed": re.compile(r"^/feed/(\d+)/?$"),
}


class ContentHiddenError(AppError):
    http_status = 451
    error_code = "content_hidden"


def parse_target_url(target_type: str, raw_url: str) -> tuple[str, str]:
    """校验完整地址，并返回规范地址和目标编号。"""
    if target_type not in SUPPORTED_TYPES:
        raise ValidationError("暂不支持该内容类型")
    parsed = urlparse(raw_url.strip())
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValidationError("请输入洛谷或本站的完整内容地址")
    matched = PATHS[target_type].match(parsed.path)
    if matched is None:
        raise ValidationError("地址与所选内容类型不匹配")
    target_id = matched.group(1)
    return f"https://www.luogu.com.cn/{target_type}/{target_id}", target_id


async def find_active_suppression(
    db: AsyncSession, target_type: str, target_id: str, owner_uid: int | None = None,
) -> ContentSuppression | None:
    clauses = [
        (ContentSuppression.target_type == target_type)
        & (ContentSuppression.target_id == str(target_id))
    ]
    if owner_uid is not None:
        clauses.append(
            (ContentSuppression.target_type == "user")
            & (ContentSuppression.target_id == str(owner_uid))
        )
    q = select(ContentSuppression).where(ContentSuppression.restored_at.is_(None), or_(*clauses))
    return (await db.execute(q)).scalars().first()


async def ensure_content_visible(
    db: AsyncSession, target_type: str, target_id: str, owner_uid: int | None = None,
) -> None:
    if await find_active_suppression(db, target_type, target_id, owner_uid):
        raise ContentHiddenError(PUBLIC_MESSAGE)


def visible_content_clause(target_type: str, id_column, owner_column=None):
    """供公开列表查询使用，排除直接隐藏和作者主页级联隐藏的内容。"""
    direct = and_(
        ContentSuppression.target_type == target_type,
        ContentSuppression.target_id == id_column,
    )
    conditions = [direct]
    if owner_column is not None:
        conditions.append(and_(
            ContentSuppression.target_type == "user",
            ContentSuppression.target_id == owner_column,
        ))
    hidden = select(ContentSuppression.id).where(
        ContentSuppression.restored_at.is_(None), or_(*conditions)
    )
    return ~exists(hidden)


async def apply_takedown(
    db: AsyncSession, request: TakedownRequest, *, admin_id: int | None = None,
) -> ContentSuppression:
    existing = (await db.execute(select(ContentSuppression).where(
        ContentSuppression.target_type == request.target_type,
        ContentSuppression.target_id == str(request.target_id),
    ))).scalars().first()
    if existing is not None:
        # 同一目标恢复后再次批准时复用唯一记录，并重新启用屏蔽。
        existing.owner_uid = request.target_author_uid
        existing.takedown_request_id = request.id
        existing.public_message = PUBLIC_MESSAGE
        existing.block_crawl = True
        existing.hidden_at = request.handled_at or utcnow()
        existing.restored_at = None
        existing.created_by_user_id = request.requester_user_id
        existing.created_by_admin_id = admin_id
        request.execution_status = "success"
        return existing
    row = ContentSuppression(
        target_type=request.target_type,
        target_id=request.target_id,
        owner_uid=request.target_author_uid,
        takedown_request_id=request.id,
        public_message=PUBLIC_MESSAGE,
        created_by_user_id=request.requester_user_id,
        created_by_admin_id=admin_id,
    )
    db.add(row)
    request.execution_status = "success"
    return row
