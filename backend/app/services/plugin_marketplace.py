"""插件广场共享校验、快照和查询辅助函数。"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import PurePath

from markdown_it import MarkdownIt
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.models.admin import Admin
from app.models.plugin import PluginTag, PluginTagLink, PluginVersion


CODE_MAX_BYTES = 5 * 1024 * 1024
CODE_PREVIEW_MAX_LINES = 1000
CODE_PREVIEW_MAX_BYTES = 50 * 1024
ANALYSIS_MAX_CHARS = 20_000
RUNTIME_MODES = {"userscript", "extension", "bookmarklet", "other"}
APPLICATION_TYPES = {"publish", "update", "recommend", "delete"}
APPLICATION_STATUSES = {"pending", "approved", "rejected", "cancelled"}
REPORT_TYPES = {"dangerous_request", "malicious_code", "broken", "copyright", "misleading", "other"}
REPORT_STATUSES = {"pending", "resolved", "dismissed"}


class PluginSnapshot(BaseModel):
    """发布或更新申请的完整快照。"""

    summary: str | None = Field(None, max_length=50)
    version: str = Field(..., min_length=1, max_length=64)
    code: str = Field(..., min_length=1)
    download_filename: str = Field(..., min_length=1, max_length=128)
    user_request_level: int = Field(..., ge=0, le=3)
    user_request_analysis: str = Field(..., min_length=1, max_length=ANALYSIS_MAX_CHARS)
    tag_ids: list[int] = Field(default_factory=list, max_length=20)
    runtime_mode: str
    supports_desktop: bool = True
    supports_mobile: bool = False
    last_verified_on: date

    # 管理员审核时可覆盖；普通用户提交接口会忽略这些字段。
    admin_request_level: int | None = Field(None, ge=0, le=3)
    admin_request_analysis: str | None = Field(None, max_length=ANALYSIS_MAX_CHARS)

    @field_validator("version", "user_request_analysis")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value

    @field_validator("summary", "admin_request_analysis")
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
    def valid_devices(self) -> "PluginSnapshot":
        if not self.supports_desktop and not self.supports_mobile:
            raise ValueError("至少选择一种兼容设备")
        return self

    @property
    def final_request_level(self) -> int:
        return self.admin_request_level if self.admin_request_level is not None else self.user_request_level


def encode_snapshot(snapshot: PluginSnapshot) -> str:
    return snapshot.model_dump_json()


def decode_snapshot(value: str) -> PluginSnapshot:
    return PluginSnapshot.model_validate_json(value)


def code_preview(code: str) -> tuple[str, int, bool]:
    """生成用于 JSON 响应的代码预览，完整代码只允许通过按需下载接口传输。"""
    source = code.encode("utf-8")
    lines = code.split("\n")
    preview = "\n".join(lines[:CODE_PREVIEW_MAX_LINES])
    preview_bytes = preview.encode("utf-8")
    truncated = len(lines) > CODE_PREVIEW_MAX_LINES or len(source) > CODE_PREVIEW_MAX_BYTES
    if len(preview_bytes) > CODE_PREVIEW_MAX_BYTES:
        # errors="ignore" 只会丢弃末尾被切开的 UTF-8 字符，不会产生乱码。
        preview = preview_bytes[:CODE_PREVIEW_MAX_BYTES].decode("utf-8", errors="ignore")
    return preview, len(source), truncated


def snapshot_preview_dict(snapshot: PluginSnapshot) -> dict:
    """序列化申请快照，但不把完整代码塞进普通详情响应。"""
    result = snapshot.model_dump(mode="json")
    preview, source_bytes, truncated = code_preview(snapshot.code)
    result.update({
        "code": preview,
        "code_bytes": source_bytes,
        "code_truncated": truncated,
    })
    return result


def code_sha256(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def article_summary(content_md: str, fallback: str, *, max_length: int = 50) -> str:
    """从文章 Markdown 的可见文本生成简介，避免把链接语法或 HTML 标签带进广场。"""
    parts: list[str] = []
    for token in MarkdownIt("commonmark", {"html": False}).parse(content_md):
        if token.type != "inline" or not token.children:
            continue
        for child in token.children:
            if child.type in {"text", "code_inline", "image"} and child.content:
                parts.append(child.content)
            elif child.type in {"softbreak", "hardbreak"}:
                parts.append(" ")
        parts.append(" ")

    text = re.sub(r"\s+", " ", "".join(parts)).strip() or fallback.strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


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
        # 旧数据库列暂时保留以兼容已发布版本，新版不再采集或公开这些字段。
        target_pages="",
        last_verified_on=snapshot.last_verified_on,
        min_compatible_date=None,
        compatibility_notes=None,
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
