"""管理员通知收件人查询。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import Admin


async def admin_notification_emails(db: AsyncSession) -> list[str]:
    """返回所有启用管理员保存的通知邮箱。"""
    q = select(Admin.notification_email).where(
        Admin.notification_email.is_not(None),
        Admin.is_disabled.is_(False),
    )
    values = (await db.execute(q)).scalars().all()
    return sorted({str(value) for value in values if value})
