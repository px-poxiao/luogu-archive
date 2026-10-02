"""插件使用事件去重与统计。"""
from __future__ import annotations

import hashlib
import hmac
from datetime import date

from fastapi import Request
from sqlalchemy import update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_ip
from app.core.config import settings
from app.models._common import utcnow
from app.models.plugin import Plugin, PluginUsageEvent, PluginVersion
from app.models.site_user import SiteUser


def _usage_client_ip(request: Request) -> str:
    """优先使用由本站反向代理覆盖写入、不可由客户端伪造的地址。"""

    real_ip = request.headers.get("x-real-ip")
    return real_ip.strip() if real_ip else get_client_ip(request)


def _visitor_key(request: Request, user: SiteUser | None, event_date: date) -> str:
    """生成仅在本站内部可比较的每日访客摘要。"""

    if user is not None:
        identity = f"user:{user.id}"
    else:
        user_agent = request.headers.get("user-agent", "")[:512]
        identity = f"anonymous:{_usage_client_ip(request)}:{user_agent}"
    message = f"plugin-usage:{event_date.isoformat()}:{identity}".encode()
    return hmac.new(settings.JWT_SECRET.encode(), message, hashlib.sha256).hexdigest()


async def record_plugin_usage(
    db: AsyncSession,
    request: Request,
    plugin: Plugin,
    version: PluginVersion,
    action: str,
    *,
    user: SiteUser | None,
) -> bool:
    """记录一次复制或下载；重复事件返回 False 且不增加累计计数。"""

    if action not in {"copy", "download"}:
        raise ValueError("未知的插件使用事件")
    event_date = utcnow().date()
    stmt = mysql_insert(PluginUsageEvent).values(
        plugin_id=plugin.id,
        version_id=version.id,
        action=action,
        visitor_key=_visitor_key(request, user, event_date),
        event_date=event_date,
    ).prefix_with("IGNORE")
    result = await db.execute(stmt)
    if result.rowcount != 1:
        return False

    counter_update = (
        {"copy_count": PluginVersion.copy_count + 1}
        if action == "copy"
        else {"download_count": PluginVersion.download_count + 1}
    )
    await db.execute(
        update(PluginVersion)
        .where(PluginVersion.id == version.id)
        .values(**counter_update)
    )
    await db.execute(
        update(Plugin)
        .where(Plugin.id == plugin.id)
        .values(total_usage=Plugin.total_usage + 1)
    )
    return True
