"""插件广场共享校验、快照和查询辅助函数。"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import PurePath

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.models.admin import Admin
from app.models.plugin import PluginTag, PluginTagLink, PluginVersion


CODE_MAX_BYTES = 5 * 1024 * 1024
ANALYSIS_MAX_CHARS = 20_000
RUNTIME_MODES = {"userscript", "extension", "bookmarklet", "other"}
APPLICATION_TYPES = {"publish", "update", "recommend", "delete"}
APPLICATION_STATUSES = {"pending", "approved", "rejected", "cancelled"}
REPORT_TYPES = {"dangerous_request", "malicious_code", "broken", "copyright", "misleading", "other"}
REPORT_STATUSES = {"pending", "resolved", "dismissed"}


class PluginSnapshot(BaseModel):
    """发布或更新申请的完整快照。"""

    name: str = Field(..., min_length=1, max_length=80)
    summary: str = Field(..., min_length=1, max_length=300)
    version: str = Field(..., min_length=1, max_length=64)
    code: str = Field(..., min_length=1)
    download_filename: str = Field(..., min_length=1, max_length=128)
    user_request_level: int = Field(..., ge=0, le=3)
    user_request_analysis: str = Field(..., min_length=1, max_length=ANALYSIS_MAX_CHARS)
    tag_ids: list[int] = Field(default_factory=list, max_length=20)
    runtime_mode: str
    supports_desktop: bool = True
    supports_mobile: bool = False
    target_pages: str = Field(..., min_length=1, max_length=5000)
    last_verified_on: date
    min_compatible_date: date | None = None
    compatibility_notes: str | None = Field(None, max_length=5000)

    # 管理员审核时可覆盖；普通用户提交接口会忽略这些字段。
    admin_request_level: int | None = Field(None, ge=0, le=3)
    admin_request_analysis: str | None = Field(None, max_length=ANALYSIS_MAX_CHARS)

    @field_validator("name", "summary", "version", "user_request_analysis", "target_pages")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value

    @field_validator("compatibility_notes", "admin_request_analysis")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("runtime_mode")
    @classmethod
    def valid_runtime_mode(cls, value: str) -> str:
        if value not in RUNTIME_MODES:
            raise ValueError("运行方式不受支持")
        return value

    @field_validator("code")
    @classmethod
    def valid_code_size(cls, value: str) -> str:
        if len(value.encode("utf-8")) > CODE_MAX_BYTES:
            raise ValueError("代码不能超过 5 MiB")
        return value

    @field_validator("download_filename")
    @classmethod
    def valid_filename(cls, value: str) -> str:
        value = value.strip()
        if (
            not value
            or value in {".", ".."}
            or PurePath(value).name != value
            or any(char in value for char in "\r\n\0/\\")
            or not re.fullmatch(r"[^<>:\"|?*]+", value)
        ):
            raise ValueError("下载文件名不安全")
        return value

    @field_validator("tag_ids")
    @classmethod
    def unique_tags(cls, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def valid_compatibility(self) -> "PluginSnapshot":
        if not self.supports_desktop and not self.supports_mobile:
            raise ValueError("至少选择一种兼容设备")
        if self.min_compatible_date is None and not self.compatibility_notes:
            raise ValueError("最低适配日期和兼容说明至少填写一项")
        return self

    @property
    def final_request_level(self) -> int:
        return self.admin_request_level if self.admin_request_level is not None else self.user_request_level


def encode_snapshot(snapshot: PluginSnapshot) -> str:
    return snapshot.model_dump_json()


def decode_snapshot(value: str) -> PluginSnapshot:
    return PluginSnapshot.model_validate_json(value)


def code_sha256(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


async def validate_tag_ids(
    db: AsyncSession,
    tag_ids: list[int],
    *,
    allow_inactive: bool = False,
) -> None:
    if not tag_ids:
        return
    q = select(PluginTag.id).where(PluginTag.id.in_(tag_ids))
    if not allow_inactive:
        q = q.where(PluginTag.is_active.is_(True))
    found = set((await db.execute(q)).scalars().all())
    if found != set(tag_ids):
        raise ValidationError("包含不存在或已停用的插件标签")


async def replace_plugin_tags(db: AsyncSession, plugin_id: int, tag_ids: list[int]) -> None:
    await db.execute(delete(PluginTagLink).where(PluginTagLink.plugin_id == plugin_id))
    for tag_id in tag_ids:
        db.add(PluginTagLink(plugin_id=plugin_id, tag_id=tag_id))


async def plugin_tag_names(db: AsyncSession, plugin_id: int) -> list[dict]:
    q = (
        select(PluginTag)
        .join(PluginTagLink, PluginTagLink.tag_id == PluginTag.id)
        .where(PluginTagLink.plugin_id == plugin_id)
        .order_by(PluginTag.sort_order, PluginTag.id)
    )
    return [{"id": row.id, "name": row.name} for row in (await db.execute(q)).scalars().all()]


def version_from_snapshot(
    plugin_id: int,
    snapshot: PluginSnapshot,
    *,
    admin_id: int,
    source_application_id: int | None,
) -> PluginVersion:
    return PluginVersion(
        plugin_id=plugin_id,
        version=snapshot.version,
        code=snapshot.code,
        code_sha256=code_sha256(snapshot.code),
        download_filename=snapshot.download_filename,
        user_request_level=snapshot.user_request_level,
        user_request_analysis=snapshot.user_request_analysis,
        admin_request_level=snapshot.admin_request_level,
        admin_request_analysis=snapshot.admin_request_analysis,
        final_request_level=snapshot.final_request_level,
        runtime_mode=snapshot.runtime_mode,
        supports_desktop=snapshot.supports_desktop,
        supports_mobile=snapshot.supports_mobile,
        target_pages=snapshot.target_pages,
        last_verified_on=snapshot.last_verified_on,
        min_compatible_date=snapshot.min_compatible_date,
        compatibility_notes=snapshot.compatibility_notes,
        source_application_id=source_application_id,
        reviewed_by_admin_id=admin_id,
    )


async def verified_admin_emails(db: AsyncSession) -> list[str]:
    q = select(Admin.notification_email).where(
        Admin.notification_email_verified.is_(True),
        Admin.notification_email.is_not(None),
        Admin.is_disabled.is_(False),
    )
    return sorted({str(value) for value in (await db.execute(q)).scalars().all() if value})
