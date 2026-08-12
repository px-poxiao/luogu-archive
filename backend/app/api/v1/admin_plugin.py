"""管理员插件审核、标签、举报和通知邮箱接口。"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_ip
from app.auth.deps import get_current_admin
from app.core.config import settings
from app.core.db import get_db
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.mail import send_email, send_plugin_result_email
from app.models._common import utcnow
from app.models.admin import Admin, AdminAuditLog
from app.models.plugin import Plugin, PluginApplication, PluginReport, PluginTag, PluginVersion
from app.models.site_user import SiteUser
from app.services.plugin_marketplace import (
    PluginSnapshot,
    decode_snapshot,
    encode_snapshot,
    plugin_tag_names,
    replace_plugin_tags,
    validate_tag_ids,
    version_from_snapshot,
)


router = APIRouter(prefix="/admin", tags=["admin-plugins"])


class ReviewApplicationReq(BaseModel):
    approved: bool
    rejection_reason: str | None = Field(None, max_length=5000)
    snapshot: PluginSnapshot | None = None
    admin_request_level: int | None = Field(None, ge=0, le=3)
    admin_request_analysis: str | None = Field(None, max_length=20_000)


class PluginAdminUpdateReq(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    summary: str | None = Field(None, min_length=1, max_length=300)
    is_official: bool | None = None
    is_recommended: bool | None = None
    tag_ids: list[int] | None = Field(None, max_length=20)


class PluginStateReq(BaseModel):
    reason: str | None = Field(None, max_length=5000)


class TagWriteReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=32)
    is_active: bool = True
    sort_order: int = Field(0, ge=0, le=10000)


class ReportHandleReq(BaseModel):
    status: str = Field(..., pattern=r"^(resolved|dismissed)$")
    admin_note: str | None = Field(None, max_length=5000)


class NotificationEmailReq(BaseModel):
    email: EmailStr


async def _audit(
    db: AsyncSession,
    admin: Admin,
    request: Request,
    action: str,
    *,
    target_type: str,
    target_id: str,
    params: dict | None = None,
) -> None:
    db.add(AdminAuditLog(
        admin_id=admin.id,
        admin_username=admin.username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        params=params,
        ip=get_client_ip(request),
        ua=request.headers.get("user-agent", "")[:500],
    ))


def _application_dict(row: PluginApplication, *, include_snapshot: bool = False) -> dict:
    result = {
        "id": row.id,
        "plugin_id": row.plugin_id,
        "article_id": row.article_id,
        "applicant_user_id": row.applicant_user_id,
        "application_type": row.application_type,
        "status": row.status,
        "version": row.version,
        "user_request_level": row.user_request_level,
        "reason": row.reason,
        "review_note": row.review_note,
        "created_at": row.created_at.isoformat(),
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
    }
    if include_snapshot:
        result["snapshot"] = decode_snapshot(row.snapshot_json).model_dump(mode="json") if row.snapshot_json != "{}" else {}
    return result


@router.get("/plugin-applications")
async def list_plugin_applications(
    status: str = Query("pending", pattern=r"^(pending|approved|rejected|cancelled|all)$"),
    application_type: str | None = Query(None, pattern=r"^(publish|update|recommend|delete)$"),
    limit: int = Query(100, ge=1, le=200),
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    q = select(PluginApplication).order_by(desc(PluginApplication.created_at)).limit(limit)
    if status != "all":
        q = q.where(PluginApplication.status == status)
    if application_type:
        q = q.where(PluginApplication.application_type == application_type)
    rows = (await db.execute(q)).scalars().all()
    return [_application_dict(row) for row in rows]


@router.get("/plugin-applications/{application_id}")
async def plugin_application_detail(
    application_id: int,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(PluginApplication, application_id)
    if row is None:
        raise NotFoundError("插件申请不存在")
    result = _application_dict(row, include_snapshot=True)
    plugin = await db.get(Plugin, row.plugin_id) if row.plugin_id else None
    current = await db.get(PluginVersion, plugin.current_version_id) if plugin and plugin.current_version_id else None
    result["current"] = ({
        "name": plugin.name,
        "summary": plugin.summary,
        "version": current.version,
        "code": current.code,
        "final_request_level": current.final_request_level,
        "tags": await plugin_tag_names(db, plugin.id),
    } if plugin and current else None)
    applicant = await db.get(SiteUser, row.applicant_user_id)
    result["applicant"] = ({
        "id": applicant.id,
        "display_name": applicant.display_name,
        "luogu_uid": applicant.luogu_uid,
    } if applicant else None)
    return result


@router.post("/plugin-applications/{application_id}/review")
async def review_plugin_application(
    application_id: int,
    body: ReviewApplicationReq,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(
            select(PluginApplication)
            .where(PluginApplication.id == application_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("插件申请不存在")
    if row.status != "pending":
        raise ConflictError("该申请已经处理")
    if not body.approved and not (body.rejection_reason or "").strip():
        raise ValidationError("拒绝申请必须填写原因")

    applicant = await db.get(SiteUser, row.applicant_user_id)
    plugin = await db.get(Plugin, row.plugin_id) if row.plugin_id else None
    plugin_name = plugin.name if plugin else row.article_id

    if body.approved:
        if row.application_type in {"publish", "update"}:
            snapshot = body.snapshot or decode_snapshot(row.snapshot_json)
            snapshot = snapshot.model_copy(update={
                "admin_request_level": body.admin_request_level,
                "admin_request_analysis": (body.admin_request_analysis or "").strip() or None,
            })
            await validate_tag_ids(db, snapshot.tag_ids, allow_inactive=True)

            if row.application_type == "publish":
                existing = (
                    await db.execute(select(Plugin).where(Plugin.article_id == row.article_id).with_for_update())
                ).scalar_one_or_none()
                if existing is not None:
                    raise ConflictError("文章已经存在正式插件")
                plugin = Plugin(
                    article_id=row.article_id,
                    owner_user_id=row.applicant_user_id,
                    name=snapshot.name,
                    summary=snapshot.summary,
                    is_listed=True,
                    is_official=False,
                    is_recommended=False,
                )
                db.add(plugin)
                await db.flush()
                row.plugin_id = plugin.id
            else:
                plugin = (
                    await db.execute(select(Plugin).where(Plugin.id == row.plugin_id).with_for_update())
                ).scalar_one_or_none()
                if plugin is None:
                    raise NotFoundError("对应插件不存在")

            duplicate = await db.scalar(select(func.count()).select_from(PluginVersion).where(
                PluginVersion.plugin_id == plugin.id,
                PluginVersion.version == snapshot.version,
            ))
            if duplicate:
                raise ConflictError("该代码版本号已经存在")
            version = version_from_snapshot(
                plugin.id,
                snapshot,
                admin_id=admin.id,
                source_application_id=row.id,
            )
            db.add(version)
            await db.flush()
            plugin.name = snapshot.name
            plugin.summary = snapshot.summary
            plugin.current_version_id = version.id
            await replace_plugin_tags(db, plugin.id, snapshot.tag_ids)
            row.snapshot_json = encode_snapshot(snapshot)
            row.version = snapshot.version
            row.user_request_level = snapshot.user_request_level
            plugin_name = snapshot.name
        elif row.application_type == "recommend":
            if plugin is None:
                raise NotFoundError("对应插件不存在")
            plugin.is_recommended = True
            plugin_name = plugin.name
        elif row.application_type == "delete":
            if plugin is None:
                raise NotFoundError("对应插件不存在")
            plugin.is_listed = False
            plugin.down_reason = row.reason
            plugin_name = plugin.name
        else:
            raise ValidationError("未知申请类型")
        row.status = "approved"
        row.review_note = None
    else:
        row.status = "rejected"
        row.review_note = body.rejection_reason.strip()

    row.reviewed_by_admin_id = admin.id
    row.reviewed_at = utcnow()
    await _audit(
        db,
        admin,
        request,
        "plugin_application_review",
        target_type="plugin_application",
        target_id=str(row.id),
        params={"approved": body.approved, "application_type": row.application_type},
    )
    await db.commit()

    if applicant:
        await send_plugin_result_email(
            applicant.email,
            plugin_name=plugin_name,
            application_type=row.application_type,
            approved=body.approved,
            reason=None if body.approved else row.review_note,
        )
    return {"message": "审核完成", "status": row.status}


@router.get("/plugins")
async def admin_list_plugins(
    include_unlisted: bool = True,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    q = select(Plugin).order_by(desc(Plugin.updated_at))
    if not include_unlisted:
        q = q.where(Plugin.is_listed.is_(True))
    rows = (await db.execute(q)).scalars().all()
    return [{
        "id": row.id,
        "article_id": row.article_id,
        "owner_user_id": row.owner_user_id,
        "name": row.name,
        "summary": row.summary,
        "is_official": row.is_official,
        "is_recommended": row.is_recommended,
        "is_listed": row.is_listed,
        "down_reason": row.down_reason,
        "tags": await plugin_tag_names(db, row.id),
        "updated_at": row.updated_at.isoformat(),
    } for row in rows]


@router.get("/plugins/{plugin_id}")
async def admin_plugin_detail(
    plugin_id: int,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回管理员创建新版本所需的完整当前快照。"""
    plugin = await db.get(Plugin, plugin_id)
    if plugin is None:
        raise NotFoundError("插件不存在")
    current = await db.get(PluginVersion, plugin.current_version_id) if plugin.current_version_id else None
    if current is None:
        raise NotFoundError("插件当前版本缺失")
    tags = await plugin_tag_names(db, plugin.id)
    snapshot = PluginSnapshot(
        name=plugin.name,
        summary=plugin.summary,
        version=current.version,
        code=current.code,
        download_filename=current.download_filename,
        user_request_level=current.user_request_level,
        user_request_analysis=current.user_request_analysis,
        tag_ids=[tag["id"] for tag in tags],
        runtime_mode=current.runtime_mode,
        supports_desktop=current.supports_desktop,
        supports_mobile=current.supports_mobile,
        target_pages=current.target_pages,
        last_verified_on=current.last_verified_on,
        min_compatible_date=current.min_compatible_date,
        compatibility_notes=current.compatibility_notes,
        admin_request_level=current.admin_request_level,
        admin_request_analysis=current.admin_request_analysis,
    )
    return {
        "id": plugin.id,
        "article_id": plugin.article_id,
        "is_listed": plugin.is_listed,
        "is_official": plugin.is_official,
        "is_recommended": plugin.is_recommended,
        "snapshot": snapshot.model_dump(mode="json"),
    }


@router.put("/plugins/{plugin_id}")
async def admin_update_plugin(
    plugin_id: int,
    body: PluginAdminUpdateReq,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    plugin = await db.get(Plugin, plugin_id)
    if plugin is None:
        raise NotFoundError("插件不存在")
    if body.name is not None:
        plugin.name = body.name.strip()
    if body.summary is not None:
        plugin.summary = body.summary.strip()
    if body.is_official is not None:
        plugin.is_official = body.is_official
    if body.is_recommended is not None:
        plugin.is_recommended = body.is_recommended
    if body.tag_ids is not None:
        await validate_tag_ids(db, body.tag_ids, allow_inactive=True)
        await replace_plugin_tags(db, plugin.id, body.tag_ids)
    await _audit(db, admin, request, "plugin_update", target_type="plugin", target_id=str(plugin.id))
    await db.commit()
    return {"message": "插件信息已更新"}


@router.post("/plugins/{plugin_id}/versions")
async def admin_create_plugin_version(
    plugin_id: int,
    snapshot: PluginSnapshot,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    plugin = (
        await db.execute(select(Plugin).where(Plugin.id == plugin_id).with_for_update())
    ).scalar_one_or_none()
    if plugin is None:
        raise NotFoundError("插件不存在")
    await validate_tag_ids(db, snapshot.tag_ids, allow_inactive=True)
    duplicate = await db.scalar(select(func.count()).select_from(PluginVersion).where(
        PluginVersion.plugin_id == plugin.id, PluginVersion.version == snapshot.version
    ))
    if duplicate:
        raise ConflictError("该版本号已经存在")
    version = version_from_snapshot(plugin.id, snapshot, admin_id=admin.id, source_application_id=None)
    db.add(version)
    await db.flush()
    plugin.name = snapshot.name
    plugin.summary = snapshot.summary
    plugin.current_version_id = version.id
    await replace_plugin_tags(db, plugin.id, snapshot.tag_ids)
    await _audit(
        db, admin, request, "plugin_version_create",
        target_type="plugin", target_id=str(plugin.id), params={"version": snapshot.version},
    )
    await db.commit()
    return {"message": "新代码版本已发布", "version_id": version.id}


@router.post("/plugins/{plugin_id}/unlist")
async def admin_unlist_plugin(
    plugin_id: int,
    body: PluginStateReq,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    plugin = await db.get(Plugin, plugin_id)
    if plugin is None:
        raise NotFoundError("插件不存在")
    plugin.is_listed = False
    plugin.down_reason = (body.reason or "").strip() or "由管理员下架"
    await _audit(db, admin, request, "plugin_unlist", target_type="plugin", target_id=str(plugin.id))
    await db.commit()
    return {"message": "插件已下架"}


@router.post("/plugins/{plugin_id}/restore")
async def admin_restore_plugin(
    plugin_id: int,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    plugin = await db.get(Plugin, plugin_id)
    if plugin is None:
        raise NotFoundError("插件不存在")
    plugin.is_listed = True
    plugin.down_reason = None
    await _audit(db, admin, request, "plugin_restore", target_type="plugin", target_id=str(plugin.id))
    await db.commit()
    return {"message": "插件已恢复"}


@router.get("/plugin-tags")
async def admin_list_tags(
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = (await db.execute(select(PluginTag).order_by(PluginTag.sort_order, PluginTag.id))).scalars().all()
    return [{"id": row.id, "name": row.name, "is_active": row.is_active, "sort_order": row.sort_order} for row in rows]


@router.post("/plugin-tags")
async def admin_create_tag(
    body: TagWriteReq,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    name = body.name.strip()
    if await db.scalar(select(func.count()).select_from(PluginTag).where(PluginTag.name == name)):
        raise ConflictError("标签名称已经存在")
    row = PluginTag(name=name, is_active=body.is_active, sort_order=body.sort_order)
    db.add(row)
    await db.flush()
    await _audit(db, admin, request, "plugin_tag_create", target_type="plugin_tag", target_id=str(row.id))
    await db.commit()
    return {"id": row.id}


@router.put("/plugin-tags/{tag_id}")
async def admin_update_tag(
    tag_id: int,
    body: TagWriteReq,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(PluginTag, tag_id)
    if row is None:
        raise NotFoundError("标签不存在")
    duplicate = await db.scalar(select(func.count()).select_from(PluginTag).where(
        PluginTag.name == body.name.strip(), PluginTag.id != tag_id
    ))
    if duplicate:
        raise ConflictError("标签名称已经存在")
    row.name = body.name.strip()
    row.is_active = body.is_active
    row.sort_order = body.sort_order
    await _audit(db, admin, request, "plugin_tag_update", target_type="plugin_tag", target_id=str(row.id))
    await db.commit()
    return {"message": "标签已更新"}


@router.get("/plugin-reports")
async def admin_list_reports(
    status: str = Query("pending", pattern=r"^(pending|resolved|dismissed|all)$"),
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    q = select(PluginReport).order_by(desc(PluginReport.created_at)).limit(200)
    if status != "all":
        q = q.where(PluginReport.status == status)
    rows = (await db.execute(q)).scalars().all()
    return [{
        "id": row.id,
        "plugin_id": row.plugin_id,
        "reporter_user_id": row.reporter_user_id,
        "report_type": row.report_type,
        "description": row.description,
        "status": row.status,
        "admin_note": row.admin_note,
        "created_at": row.created_at.isoformat(),
    } for row in rows]


@router.post("/plugin-reports/{report_id}/handle")
async def admin_handle_report(
    report_id: int,
    body: ReportHandleReq,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(PluginReport, report_id)
    if row is None:
        raise NotFoundError("举报不存在")
    if row.status != "pending":
        raise ConflictError("举报已经处理")
    row.status = body.status
    row.admin_note = body.admin_note
    row.handled_by_admin_id = admin.id
    row.handled_at = utcnow()
    await _audit(db, admin, request, "plugin_report_handle", target_type="plugin_report", target_id=str(row.id), params={"status": body.status})
    await db.commit()
    return {"message": "举报已处理"}


@router.get("/notification-email")
async def notification_email_status(admin: Admin = Depends(get_current_admin)) -> dict:
    return {
        "email": admin.notification_email,
        "verified": admin.notification_email_verified,
    }


@router.post("/notification-email")
async def bind_notification_email(
    body: NotificationEmailReq,
    request: Request,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    token = secrets.token_urlsafe(32)
    admin.notification_email = str(body.email).lower()
    admin.notification_email_verified = False
    admin.notification_email_token_hash = hashlib.sha256(token.encode()).hexdigest()
    admin.notification_email_expires = utcnow() + timedelta(hours=24)
    await _audit(db, admin, request, "admin_notification_email_bind", target_type="admin", target_id=str(admin.id))
    await db.commit()

    verify_url = f"{settings.WEB_PUBLIC_ORIGIN.rstrip('/')}/admin/notification-email/verify?token={token}"
    ok = await send_email(
        admin.notification_email,
        "[洛谷档案馆] 验证管理员通知邮箱",
        f"请在 24 小时内打开以下链接完成验证：\n{verify_url}",
    )
    return {"message": "验证邮件已发送" if ok else "邮箱已保存，但验证邮件发送失败，请检查邮件配置"}


@router.get("/notification-email/verify")
async def verify_notification_email(
    request: Request,
    token: str = Query(..., min_length=20, max_length=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    admin = (
        await db.execute(select(Admin).where(Admin.notification_email_token_hash == token_hash))
    ).scalar_one_or_none()
    expires = admin.notification_email_expires if admin else None
    # MySQL 可能返回不带时区的 datetime，比较前统一按 UTC 解释。
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if admin is None or expires is None or expires < utcnow():
        raise ValidationError("验证链接无效或已过期")
    admin.notification_email_verified = True
    admin.notification_email_token_hash = None
    admin.notification_email_expires = None
    await _audit(
        db,
        admin,
        request,
        "admin_notification_email_verify",
        target_type="admin",
        target_id=str(admin.id),
    )
    await db.commit()
    return {"message": "管理员通知邮箱验证成功"}
