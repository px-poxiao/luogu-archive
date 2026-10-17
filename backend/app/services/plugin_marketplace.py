"""插件广场共享校验、快照和查询辅助函数。"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
from datetime import date
from pathlib import PurePath

from markdown_it import MarkdownIt
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.models.plugin import PluginTag, PluginTagLink, PluginVersion


CODE_MAX_BYTES = 5 * 1024 * 1024
CODE_PREVIEW_MAX_LINES = 1000
CODE_PREVIEW_MAX_BYTES = 50 * 1024
# 二进制插件文件上限。base64 后约 1.34 倍，必须留在 nginx client_max_body_size 之下。
BINARY_FILE_MAX_BYTES = 10 * 1024 * 1024
# 留空元组表示不限制扩展名。
BINARY_ALLOWED_SUFFIXES = (".zip", ".crx", ".xpi")
BINARY_PREVIEW_TEXT = "（二进制文件，不提供文本预览，请下载后查看）"
ANALYSIS_MAX_CHARS = 20_000
RUNTIME_MODES = {"userscript", "extension", "bookmarklet", "other"}
CODE_ENCODINGS = {"text", "base64"}
APPLICATION_TYPES = {"publish", "update", "recommend", "delete"}
APPLICATION_STATUSES = {"pending", "approved", "rejected", "cancelled"}
REPORT_TYPES = {"dangerous_request", "malicious_code", "broken", "copyright", "misleading", "other"}
REPORT_STATUSES = {"pending", "resolved", "dismissed"}


class PluginSnapshot(BaseModel):
    """发布或更新申请的完整快照。"""

    summary: str | None = Field(None, max_length=50)
    version: str = Field(..., min_length=1, max_length=64)
    code: str = Field(..., min_length=1)
    # text 时 code 就是源码本身；base64 时 code 是二进制文件的 base64，
    # 解码后的字节才是用户实际下载到的内容。
    code_encoding: str = "text"
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

    @field_validator("code_encoding")
    @classmethod
    def valid_code_encoding(cls, value: str) -> str:
        if value not in CODE_ENCODINGS:
            raise ValueError("代码存储方式不受支持")
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
    def valid_code_payload(self) -> PluginSnapshot:
        """体积按存储方式分别校验；二进制额外限制扩展名。"""
        if self.code_encoding == "base64":
            try:
                decoded = base64.b64decode(self.code, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("二进制文件内容不是合法的 base64") from exc
            if len(decoded) > BINARY_FILE_MAX_BYTES:
                raise ValueError(
                    f"二进制文件不能超过 {BINARY_FILE_MAX_BYTES // (1024 * 1024)} MiB"
                )
            if BINARY_ALLOWED_SUFFIXES:
                suffix = PurePath(self.download_filename).suffix.lower()
                if suffix not in BINARY_ALLOWED_SUFFIXES:
                    allowed = " / ".join(BINARY_ALLOWED_SUFFIXES)
                    raise ValueError(f"二进制文件只允许 {allowed} 格式")
        elif len(self.code.encode("utf-8")) > CODE_MAX_BYTES:
            raise ValueError("代码不能超过 5 MiB")
        return self

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


def decode_code(code: str, code_encoding: str = "text") -> bytes:
    """把存储中的 code 还原为字节：这必须是用户下载后拿到的东西。"""
    if code_encoding == "base64":
        try:
            return base64.b64decode(code, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValidationError("二进制文件内容不是合法的 base64") from exc
    return code.encode("utf-8")


def code_media_type(code_encoding: str = "text") -> str:
    """二进制必须按字节流下发，否则会被当作文本处理而损坏。"""
    if code_encoding == "base64":
        return "application/octet-stream"
    return "text/plain; charset=utf-8"


def code_preview(code: str, code_encoding: str = "text") -> tuple[str, int, bool]:
    """生成用于 JSON 响应的代码预览，完整代码只允许通过按需下载接口传输。"""
    if code_encoding == "base64":
        # base64 摘一段出来对人类没有意义，只回报真实体积。
        return BINARY_PREVIEW_TEXT, len(decode_code(code, code_encoding)), False
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
    preview, source_bytes, truncated = code_preview(snapshot.code, snapshot.code_encoding)
    result.update({
        "code": preview,
        "code_bytes": source_bytes,
        "code_truncated": truncated,
    })
    return result


def code_sha256(code: str, code_encoding: str = "text") -> str:
    """哈希必须针对解码后的字节，用户下载后校验才能对得上。"""
    return hashlib.sha256(decode_code(code, code_encoding)).hexdigest()


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
        code_encoding=snapshot.code_encoding,
        code_sha256=code_sha256(snapshot.code, snapshot.code_encoding),
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
