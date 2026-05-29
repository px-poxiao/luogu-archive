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
        "感谢注册洛谷存档。请点击以下链接完成邮箱验证（24 小时内有效）：\n"
        f"{verify_url}\n\n"
        "如果按钮无法点击，请将上面的链接复制到浏览器地址栏打开。\n"
        "如果这不是你本人的操作，请忽略此邮件。\n"
    )
    html = _verification_html(verify_url)
    return await send_email(to, subject, text, html)


def _verification_html(verify_url: str) -> str:
    """邮箱验证邮件的 HTML 模板。

    邮件客户端（QQ 邮箱 / Outlook）CSS 支持极弱，必须：
    - table 布局，不用 flex / grid
    - 全部内联样式，不用 <style> / class / CSS 变量
    - 固定色值，不依赖深浅色模式
    """
    brand = "#0969da"
    return f"""\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background-color:#f2f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f2f4f7;padding:32px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background-color:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 4px 18px rgba(0,0,0,0.06);">
          <!-- 顶部品牌条 -->
          <tr>
            <td style="background-color:{brand};padding:24px 32px;text-align:center;">
              <span style="color:#ffffff;font-size:20px;font-weight:700;letter-spacing:0.5px;">洛谷存档</span>
            </td>
          </tr>
          <!-- 正文 -->
          <tr>
            <td style="padding:36px 32px 8px;">
              <h1 style="margin:0 0 16px;font-size:21px;color:#1f2328;font-weight:700;">验证你的邮箱</h1>
              <p style="margin:0 0 8px;font-size:15px;line-height:1.7;color:#57606a;">
                你好，感谢注册<strong style="color:#1f2328;">洛谷存档</strong>。
              </p>
              <p style="margin:0 0 28px;font-size:15px;line-height:1.7;color:#57606a;">
                请点击下方按钮完成邮箱验证。此链接 <strong style="color:#1f2328;">24 小时内</strong> 有效。
              </p>
              <!-- 按钮 -->
              <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto 28px;">
                <tr>
                  <td align="center" style="border-radius:8px;background-color:{brand};">
                    <a href="{verify_url}" target="_blank"
                       style="display:inline-block;padding:13px 38px;font-size:16px;font-weight:600;color:#ffffff;text-decoration:none;border-radius:8px;">
                      验证邮箱
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 8px;font-size:13px;line-height:1.6;color:#8b949e;">
                如果按钮无法点击，请复制以下链接到浏览器打开：
              </p>
              <p style="margin:0 0 8px;font-size:13px;line-height:1.6;word-break:break-all;">
                <a href="{verify_url}" target="_blank" style="color:{brand};text-decoration:none;">{verify_url}</a>
              </p>
            </td>
          </tr>
          <!-- 分隔 -->
          <tr>
            <td style="padding:0 32px;">
              <div style="border-top:1px solid #eaecef;"></div>
            </td>
          </tr>
          <!-- 页脚 -->
          <tr>
            <td style="padding:20px 32px 32px;">
              <p style="margin:0 0 4px;font-size:12px;line-height:1.6;color:#8b949e;">
                如果这不是你本人的操作，请直接忽略此邮件，你的账号不会受到任何影响。
              </p>
              <p style="margin:0;font-size:12px;line-height:1.6;color:#b0b7c0;">
                本站为第三方存档，与洛谷官方无关。
              </p>
            </td>
          </tr>
        </table>
        <p style="max-width:480px;margin:16px auto 0;font-size:11px;color:#b0b7c0;text-align:center;">
          © 2026 洛谷存档 · 此邮件由系统自动发送，请勿直接回复
        </p>
      </td>
    </tr>
  </table>
</body>
</html>"""
