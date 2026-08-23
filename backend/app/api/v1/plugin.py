"""插件广场公开接口与登录用户申请接口。"""
from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_ip
from app.auth.deps import get_current_site_user, get_optional_site_user
from app.core.db import get_db
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, RateLimitError, ValidationError
from app.core.mail import send_plugin_admin_notice
from app.core.ratelimit import SlidingWindowLimiter, ratelimit_key
from app.core.redis_client import get_redis
from app.models._common import utcnow
from app.models.luogu_content import Article, ArticleVersion
from app.services.content_suppression import ensure_content_visible, visible_content_clause
from app.models.luogu_user import LuoguUser
from app.models.plugin import (
    Plugin,
    PluginApplication,
    PluginReport,
    PluginTag,
    PluginTagLink,
    PluginVersion,
)
from app.models.site_user import SiteUser
from app.services.plugin_marketplace import (
    REPORT_TYPES,
    PluginSnapshot,
    article_summary,
    code_preview,
    decode_snapshot,
    encode_snapshot,
    plugin_tag_names,
    snapshot_preview_dict,
    validate_tag_ids,
    admin_notification_emails,
)


router = APIRouter(prefix="/plugins", tags=["plugins"])
DOWNLOAD_CHUNK_BYTES = 64 * 1024


async def _ensure_plugin_article_visible(
    db: AsyncSession, article_id: str,
) -> None:
    """插件依附于文章，文章或作者主页隐藏后插件也不能绕过展示。"""
    article = await db.get(Article, article_id)
    await ensure_content_visible(
        db, "article", article_id, article.author_uid if article else None
    )


class PublishApplicationReq(BaseModel):
    article_id: str = Field(..., min_length=1, max_length=16, pattern=r"^[A-Za-z0-9]+$")
    snapshot: PluginSnapshot


class ReasonReq(BaseModel):
    reason: str = Field(..., min_length=5, max_length=5000)


class ReportReq(BaseModel):
    report_type: str
    description: str = Field(..., min_length=10, max_length=5000)


def _code_download_response(code: str, filename: str) -> StreamingResponse:
    """分块发送代码并关闭代理缓冲，让浏览器及时显示下载进度。"""
    content = code.encode("utf-8")

    async def chunks():
        for offset in range(0, len(content), DOWNLOAD_CHUNK_BYTES):
            yield content[offset:offset + DOWNLOAD_CHUNK_BYTES]

    encoded = quote(filename, safe="")
    return StreamingResponse(
        chunks(),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
            "Content-Length": str(len(content)),
            "X-Accel-Buffering": "no",
        },
    )


def _require_bound_user(user: SiteUser) -> None:
    if user.luogu_uid is None:
        raise ForbiddenError("发布插件前请先绑定洛谷账号")


async def _write_limit(user: SiteUser, request: Request, scope: str, *, limit: int = 10) -> None:
    limiter = SlidingWindowLimiter(get_redis())
    user_ok, _ = await limiter.acquire(
        ratelimit_key(f"plugin_{scope}_user", str(user.id)), window_sec=3600, limit=limit
    )
    ip_ok, _ = await limiter.acquire(
        ratelimit_key(f"plugin_{scope}_ip", get_client_ip(request)), window_sec=3600, limit=limit * 2
    )
    if not user_ok or not ip_ok:
        raise RateLimitError("插件操作过于频繁，请稍后再试", retry_after_sec=1800)


def _version_dict(row: PluginVersion, *, include_code: bool = True) -> dict:
    result = {
        "id": row.id,
        "version": row.version,

        "download_count": row.download_count,

        "code_sha256": row.code_sha256,
        "download_filename": row.download_filename,
        "user_request_level": row.user_request_level,
        "user_request_analysis": row.user_request_analysis,
        "admin_request_level": row.admin_request_level,
        "admin_request_analysis": row.admin_request_analysis,
        "final_request_level": row.final_request_level,
        "runtime_mode": row.runtime_mode,
        "supports_desktop": row.supports_desktop,
        "supports_mobile": row.supports_mobile,
        "last_verified_on": row.last_verified_on.isoformat(),
        "published_at": row.published_at.isoformat(),
    }
    if include_code:
        preview, source_bytes, truncated = code_preview(row.code)
        result.update({
            "code": preview,
            "code_bytes": source_bytes,
            "code_truncated": truncated,
        })
    return result


async def _complete_snapshot(
    db: AsyncSession,
    article: Article,
    snapshot: PluginSnapshot,
    *,
    clear_admin_fields: bool,
) -> PluginSnapshot:
    """补齐可省略的简介；文章标题本身作为插件名称，不接受用户另填名称。"""
    version = await db.get(ArticleVersion, article.current_version_id)
    if version is None:
        raise NotFoundError("文章版本缺失")
    updates: dict = {
        "summary": snapshot.summary or article_summary(version.content_md, article.title),
    }
    if clear_admin_fields:
        updates.update({"admin_request_level": None, "admin_request_analysis": None})
    return snapshot.model_copy(update=updates)


async def _pending_for_owner(
    db: AsyncSession,
    plugin: Plugin | None,
    article_id: str,
    user: SiteUser | None,
) -> PluginApplication | None:
    if user is None:
        return None
    q = select(PluginApplication).where(
        PluginApplication.article_id == article_id,
        PluginApplication.applicant_user_id == user.id,
        PluginApplication.status == "pending",
        PluginApplication.application_type.in_(["publish", "update"]),
    )
    if plugin is not None and plugin.owner_user_id != user.id:
        return None
    return (await db.execute(q.order_by(desc(PluginApplication.created_at)).limit(1))).scalar_one_or_none()


async def _tags_by_ids(db: AsyncSession, tag_ids: list[int]) -> list[dict]:
    """按后台排序返回申请快照中的标签，供上传者预览待审核内容。"""
    if not tag_ids:
        return []
    rows = (
        await db.execute(
            select(PluginTag)
            .where(PluginTag.id.in_(tag_ids))
            .order_by(PluginTag.sort_order, PluginTag.id)
        )
    ).scalars().all()
    return [{"id": row.id, "name": row.name} for row in rows]


@router.get("/tags")
async def list_tags(db: AsyncSession = Depends(get_db)) -> list[dict]:
    q = select(PluginTag).where(PluginTag.is_active.is_(True)).order_by(PluginTag.sort_order, PluginTag.id)
    rows = (await db.execute(q)).scalars().all()
    return [{"id": row.id, "name": row.name} for row in rows]


@router.get("")
async def list_plugins(
    tag_id: int | None = Query(None, gt=0),
    request_level: int | None = Query(None, ge=0, le=3),
    runtime_mode: str | None = None,
    device: str | None = Query(None, pattern=r"^(desktop|mobile)$"),
    official: bool | None = None,
    recommended: bool | None = None,
    updated_within_days: int | None = Query(None, ge=1, le=365),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> dict:
    q = (
        select(Plugin, PluginVersion, Article, LuoguUser)
        .join(PluginVersion, PluginVersion.id == Plugin.current_version_id)
        .join(Article, Article.article_id == Plugin.article_id)
        .outerjoin(LuoguUser, LuoguUser.uid == Article.author_uid)
        .where(Plugin.is_listed.is_(True), visible_content_clause("article", Article.article_id, Article.author_uid))
    )
    if tag_id is not None:
        q = q.join(PluginTagLink, PluginTagLink.plugin_id == Plugin.id).where(PluginTagLink.tag_id == tag_id)
    if request_level is not None:
        q = q.where(PluginVersion.final_request_level == request_level)
    if runtime_mode:
        q = q.where(PluginVersion.runtime_mode == runtime_mode)
    if device == "desktop":
        q = q.where(PluginVersion.supports_desktop.is_(True))
    if device == "mobile":
        q = q.where(PluginVersion.supports_mobile.is_(True))
    if official is not None:
        q = q.where(Plugin.is_official.is_(official))
    if recommended is not None:
        q = q.where(Plugin.is_recommended.is_(recommended))
    if updated_within_days is not None:
        q = q.where(Plugin.updated_at >= utcnow() - timedelta(days=updated_within_days))

    count_q = select(func.count()).select_from(q.order_by(None).subquery())
    total = int(await db.scalar(count_q) or 0)
    rows = (
        await db.execute(
            q.order_by(desc(Plugin.updated_at), desc(Plugin.id))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = []
    for plugin, version, article, author in rows:
        items.append({
            "article_id": plugin.article_id,
            "name": article.title,
            "summary": plugin.summary,
            "article_title": article.title,
            "article_author": ({
                "uid": author.uid,
                "name": author.name,
                "color": author.color.value,
                "badge": author.badge,
                "avatar": author.avatar,
                "ccf_level": author.ccf_level or 0,
                "xcpc_level": author.xcpc_level or 0,
                "is_admin": author.is_admin,
            } if author else None),
            "version": version.version,
            "final_request_level": version.final_request_level,

            "download_count": version.download_count,

            "runtime_mode": version.runtime_mode,
            "supports_desktop": version.supports_desktop,
            "supports_mobile": version.supports_mobile,
            "is_official": plugin.is_official,
            "is_recommended": plugin.is_recommended,
            "tags": await plugin_tag_names(db, plugin.id),
            "updated_at": plugin.updated_at.isoformat(),
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/manage")
async def manage_plugins(
    user: SiteUser = Depends(get_current_site_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    plugin_rows = (
        await db.execute(
            select(Plugin, Article)
            .join(Article, Article.article_id == Plugin.article_id)
            .where(Plugin.owner_user_id == user.id)
            .order_by(desc(Plugin.updated_at))
        )
    ).all()
    app_rows = (
        await db.execute(
            select(PluginApplication)
            .where(PluginApplication.applicant_user_id == user.id)
            .order_by(desc(PluginApplication.created_at))
            .limit(100)
        )
    ).scalars().all()
    return {
        "plugins": [{
            "id": row.id,
            "article_id": row.article_id,
            "name": article.title,
            "is_listed": row.is_listed,
            "is_official": row.is_official,
            "is_recommended": row.is_recommended,
            "updated_at": row.updated_at.isoformat(),
        } for row, article in plugin_rows],
        "applications": [{
            "id": row.id,
            "plugin_id": row.plugin_id,
            "article_id": row.article_id,
            "application_type": row.application_type,
            "status": row.status,
            "version": row.version,
            "reason": row.reason,
            "review_note": row.review_note,
            "created_at": row.created_at.isoformat(),
        } for row in app_rows],
    }


@router.get("/{article_id}")
async def plugin_detail(
    article_id: str,
    user: SiteUser | None = Depends(get_optional_site_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _ensure_plugin_article_visible(db, article_id)
    plugin = (
        await db.execute(select(Plugin).where(Plugin.article_id == article_id))
    ).scalar_one_or_none()
    pending = await _pending_for_owner(db, plugin, article_id, user)
    if plugin is None and pending is None:
        raise NotFoundError("插件不存在或尚未通过审核")

    if plugin is None:
        snapshot = decode_snapshot(pending.snapshot_json)
        return {
            "article_id": article_id,
            "pending_only": True,
            "is_owner": True,
            "is_listed": False,
            "pending_application": {
                "id": pending.id,
                "type": pending.application_type,
                "snapshot": snapshot_preview_dict(snapshot),
                "tags": await _tags_by_ids(db, snapshot.tag_ids),
            },
            "current": None,
            "versions": [],
            "tags": [],
        }

    is_owner = bool(user and user.id == plugin.owner_user_id)
    current = await db.get(PluginVersion, plugin.current_version_id) if plugin.current_version_id else None
    if current is None:
        raise NotFoundError("插件正式版本缺失")
    versions = (
        await db.execute(
            select(PluginVersion)
            .where(PluginVersion.plugin_id == plugin.id)
            .order_by(desc(PluginVersion.published_at), desc(PluginVersion.id))
        )
    ).scalars().all()
    pending_snapshot = decode_snapshot(pending.snapshot_json) if pending else None
    return {
        "id": plugin.id,
        "article_id": plugin.article_id,
        "name": plugin.name,
        "summary": plugin.summary,
        "is_official": plugin.is_official,
        "is_recommended": plugin.is_recommended,
        "is_listed": plugin.is_listed,
        "down_reason": plugin.down_reason if not plugin.is_listed else None,
        "is_owner": is_owner,
        "pending_only": False,
        "tags": await plugin_tag_names(db, plugin.id),
        "current": _version_dict(current) if plugin.is_listed or is_owner else None,
        "versions": [
            {"id": row.id, "version": row.version, "published_at": row.published_at.isoformat(), "is_current": row.id == plugin.current_version_id}
            for row in versions
        ] if plugin.is_listed or is_owner else [],
        "pending_application": ({
            "id": pending.id,
            "type": pending.application_type,
            "snapshot": snapshot_preview_dict(pending_snapshot),
            "tags": await _tags_by_ids(db, pending_snapshot.tag_ids),
        } if pending and pending_snapshot else None),
    }


@router.get("/{article_id}/versions/{version_id}")
async def get_plugin_version(
    article_id: str,
    version_id: int,
    user: SiteUser | None = Depends(get_optional_site_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _ensure_plugin_article_visible(db, article_id)
    plugin = (await db.execute(select(Plugin).where(Plugin.article_id == article_id))).scalar_one_or_none()
    if plugin is None:
        raise NotFoundError("插件不存在")
    if not plugin.is_listed and (user is None or user.id != plugin.owner_user_id):
        raise NotFoundError("插件已下架")
    version = await db.get(PluginVersion, version_id)
    if version is None or version.plugin_id != plugin.id:
        raise NotFoundError("代码版本不存在")
    return _version_dict(version)


@router.get("/{article_id}/download/{version_id}")
async def download_plugin_version(
    article_id: str,
    version_id: int,
    user: SiteUser | None = Depends(get_optional_site_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    await _ensure_plugin_article_visible(db, article_id)
    plugin = (await db.execute(select(Plugin).where(Plugin.article_id == article_id))).scalar_one_or_none()
    if plugin is None or (not plugin.is_listed and (user is None or user.id != plugin.owner_user_id)):
        raise NotFoundError("插件不存在或已下架")
    version = await db.get(PluginVersion, version_id)
    if version is None or version.plugin_id != plugin.id:
        raise NotFoundError("代码版本不存在")
    # return _code_download_response(version.code, version.download_filename)

    # 叠加下载次数（人次）
    version.download_count += 1
    await db.commit()
    return _code_download_response(
        version.code,
        version.download_filename
    )

@router.post("/applications/publish")
async def apply_publish(
    body: PublishApplicationReq,
    request: Request,
    user: SiteUser = Depends(get_current_site_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_bound_user(user)
    await _write_limit(user, request, "application")
    article = (
        await db.execute(select(Article).where(Article.article_id == body.article_id).with_for_update())
    ).scalar_one_or_none()
    if article is None or article.current_version_id is None:
        raise NotFoundError("文章尚未被本站完整收录")
    if await db.scalar(select(func.count()).select_from(Plugin).where(Plugin.article_id == body.article_id)):
        raise ConflictError("该文章已有插件，请提交版本更新")
    pending = await db.scalar(
        select(func.count()).select_from(PluginApplication).where(
            PluginApplication.article_id == body.article_id,
            PluginApplication.application_type == "publish",
            PluginApplication.status == "pending",
        )
    )
    if pending:
        raise ConflictError("该文章已有待审核的首次发布申请")
    await validate_tag_ids(db, body.snapshot.tag_ids)
    snapshot = await _complete_snapshot(
        db, article, body.snapshot, clear_admin_fields=True
    )
    row = PluginApplication(
        article_id=body.article_id,
        applicant_user_id=user.id,
        application_type="publish",
        status="pending",
        version=snapshot.version,
        user_request_level=snapshot.user_request_level,
        snapshot_json=encode_snapshot(snapshot),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "status": row.status}


@router.post("/{article_id}/applications/update")
async def apply_update(
    article_id: str,
    snapshot: PluginSnapshot,
    request: Request,
    user: SiteUser = Depends(get_current_site_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_bound_user(user)
    await _write_limit(user, request, "application")
    plugin = (
        await db.execute(select(Plugin).where(Plugin.article_id == article_id).with_for_update())
    ).scalar_one_or_none()
    if plugin is None:
        raise NotFoundError("插件不存在")
    if plugin.owner_user_id != user.id:
        raise ForbiddenError("只有插件上传者可以提交更新")
    article = await db.get(Article, article_id)
    if article is None or article.current_version_id is None:
        raise NotFoundError("文章尚未被本站完整收录")
    pending = await db.scalar(select(func.count()).select_from(PluginApplication).where(
        PluginApplication.plugin_id == plugin.id,
        PluginApplication.application_type == "update",
        PluginApplication.status == "pending",
    ))
    if pending:
        raise ConflictError("该插件已有待审核的版本更新")
    version_exists = await db.scalar(select(func.count()).select_from(PluginVersion).where(
        PluginVersion.plugin_id == plugin.id, PluginVersion.version == snapshot.version
    ))
    if version_exists:
        raise ConflictError("该代码版本号已经存在")
    await validate_tag_ids(db, snapshot.tag_ids)
    clean = await _complete_snapshot(db, article, snapshot, clear_admin_fields=True)
    row = PluginApplication(
        plugin_id=plugin.id,
        article_id=article_id,
        applicant_user_id=user.id,
        application_type="update",
        status="pending",
        version=clean.version,
        user_request_level=clean.user_request_level,
        snapshot_json=encode_snapshot(clean),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "status": row.status}


async def _reason_application(
    application_type: str,
    article_id: str,
    reason: str,
    request: Request,
    user: SiteUser,
    db: AsyncSession,
) -> tuple[PluginApplication, str, list[str]]:
    if application_type not in {"recommend", "delete"}:
        raise ValidationError("申请类型不支持")
    _require_bound_user(user)
    await _write_limit(user, request, "application")
    plugin = (
        await db.execute(select(Plugin).where(Plugin.article_id == article_id).with_for_update())
    ).scalar_one_or_none()
    if plugin is None:
        raise NotFoundError("插件不存在")
    if plugin.owner_user_id != user.id:
        raise ForbiddenError("只有插件上传者可以提交该申请")
    if not plugin.is_listed:
        raise ConflictError("已下架插件不能提交该申请")
    if application_type == "recommend" and plugin.is_recommended:
        raise ConflictError("插件已经是推荐插件")
    pending = await db.scalar(select(func.count()).select_from(PluginApplication).where(
        PluginApplication.plugin_id == plugin.id,
        PluginApplication.application_type == application_type,
        PluginApplication.status == "pending",
    ))
    if pending:
        raise ConflictError("已有同类型待审核申请")
    row = PluginApplication(
        plugin_id=plugin.id,
        article_id=article_id,
        applicant_user_id=user.id,
        application_type=application_type,
        status="pending",
        snapshot_json="{}",
        reason=reason.strip(),
    )
    db.add(row)
    emails = await admin_notification_emails(db)
    await db.commit()
    await db.refresh(row)
    return row, plugin.name, emails


@router.post("/{article_id}/applications/recommend")
async def apply_recommend(
    article_id: str,
    body: ReasonReq,
    request: Request,
    user: SiteUser = Depends(get_current_site_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row, name, emails = await _reason_application("recommend", article_id, body.reason, request, user, db)
    await send_plugin_admin_notice(emails, event_name="推荐申请", plugin_name=name, detail=body.reason)
    return {"id": row.id, "status": row.status}


@router.post("/{article_id}/applications/delete")
async def apply_delete(
    article_id: str,
    body: ReasonReq,
    request: Request,
    user: SiteUser = Depends(get_current_site_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row, name, emails = await _reason_application("delete", article_id, body.reason, request, user, db)
    await send_plugin_admin_notice(emails, event_name="删除申请", plugin_name=name, detail=body.reason)
    return {"id": row.id, "status": row.status}


@router.delete("/applications/{application_id}")
async def cancel_application(
    application_id: int,
    user: SiteUser = Depends(get_current_site_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(PluginApplication, application_id)
    if row is None or row.applicant_user_id != user.id:
        raise NotFoundError("申请不存在")
    if row.status != "pending":
        raise ConflictError("只有待审核申请可以撤销")
    row.status = "cancelled"
    await db.commit()
    return {"message": "申请已撤销"}


@router.get("/applications/{application_id}/download")
async def download_own_application_code(
    application_id: int,
    user: SiteUser = Depends(get_current_site_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """上传者明确查看或编辑申请时，才传输申请中的完整代码。"""
    row = await db.get(PluginApplication, application_id)
    if row is None or row.applicant_user_id != user.id or row.snapshot_json == "{}":
        raise NotFoundError("插件申请代码不存在")
    snapshot = decode_snapshot(row.snapshot_json)
    return _code_download_response(snapshot.code, snapshot.download_filename)


@router.post("/{article_id}/reports")
async def report_plugin(
    article_id: str,
    body: ReportReq,
    request: Request,
    user: SiteUser = Depends(get_current_site_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_bound_user(user)
    if body.report_type not in REPORT_TYPES:
        raise ValidationError("举报类型不支持")
    await _write_limit(user, request, "report", limit=5)
    plugin = (await db.execute(select(Plugin).where(Plugin.article_id == article_id))).scalar_one_or_none()
    if plugin is None:
        raise NotFoundError("插件不存在")
    row = PluginReport(
        plugin_id=plugin.id,
        reporter_user_id=user.id,
        report_type=body.report_type,
        description=body.description.strip(),
        status="pending",
    )
    db.add(row)
    emails = await admin_notification_emails(db)
    await db.commit()
    await db.refresh(row)
    await send_plugin_admin_notice(
        emails,
        event_name="举报",
        plugin_name=plugin.name,
        detail=f"类型：{body.report_type}\n{body.description}",
    )
    return {"id": row.id, "status": row.status}
