"""邮件发送（aiosmtplib）。

主要用途：
- 站内用户注册后的邮箱验证链接
- 密码重置

国外部署建议用 SMTP relay（如 Resend、SendGrid、AWS SES、Postmark）。
本实现只做基础封装，相关额度/信誉问题由运维保证。
"""
from __future__ import annotations

import email.message

import aiosmtplib

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


async def send_email(to: str, subject: str, body_plain: str, body_html: str | None = None) -> bool:
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
        log.error("email.send_failed", to=to, error=str(e))
        return False


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
