"""邮件发送。

支持两种后端（settings.MAIL_PROVIDER）：
- resend：Resend HTTP API（推荐，走 443，不易被防火墙挡）
- smtp：传统 SMTP（aiosmtplib）

主要用途：
- 站内用户注册后的邮箱验证链接
- 密码重置

发件域名必须在 Resend 后台验证过，否则只能用 onboarding@resend.dev 发到自己。
"""
from __future__ import annotations

import email.message

import aiosmtplib
import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_RESEND_ENDPOINT = "https://api.resend.com/emails"


async def _send_via_resend(
    to: str, subject: str, body_plain: str, body_html: str | None
) -> bool:
    """走 Resend HTTP API。"""
    if not settings.RESEND_API_KEY:
        log.error("email.resend_no_api_key")
        return False

    payload: dict = {
        "from": settings.MAIL_FROM,
        "to": [to],
        "subject": subject,
        "text": body_plain,
    }
    if body_html:
        payload["html"] = body_html

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                _RESEND_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if resp.status_code in (200, 201):
            return True
        log.error(
            "email.resend_failed",
            to=to,
            status=resp.status_code,
            body=resp.text[:500],
        )
        return False
    except Exception as e:
        log.error("email.resend_exception", to=to, error=str(e))
        return False


async def _send_via_smtp(
    to: str, subject: str, body_plain: str, body_html: str | None
) -> bool:
    """走传统 SMTP。"""
    msg = email.message.EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body_plain)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASSWORD or None,
            start_tls=settings.SMTP_USE_TLS,
            timeout=20,
        )
        return True
    except Exception as e:
        log.error("email.smtp_failed", to=to, error=str(e))
        return False


async def send_email(
    to: str, subject: str, body_plain: str, body_html: str | None = None
) -> bool:
    if settings.MAIL_PROVIDER == "resend":
        return await _send_via_resend(to, subject, body_plain, body_html)
    return await _send_via_smtp(to, subject, body_plain, body_html)


async def send_verification_email(to: str, verify_url: str) -> bool:
    subject = "[洛谷存档] 邮箱验证"
    text = (
        "你好，\n\n"
        "请点击以下链接完成邮箱验证（24 小时内有效）：\n"
        f"{verify_url}\n\n"
        "如果不是你本人操作，请忽略此邮件。\n"
    )
    html = (
        f'<p>请点击下方链接完成邮箱验证（24 小时内有效）：</p>'
        f'<p><a href="{verify_url}">{verify_url}</a></p>'
        f'<p style="color:#888;font-size:12px;">如果不是你本人操作，请忽略此邮件。</p>'
    )
    return await send_email(to, subject, text, html)
