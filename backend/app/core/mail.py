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
import html as html_lib

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
    subject = "[洛谷档案馆] 邮箱验证"
    text = (
        "你好，\n\n"
        "感谢注册洛谷档案馆。请点击以下链接完成邮箱验证（24 小时内有效）：\n"
        f"{verify_url}\n\n"
        "如果按钮无法点击，请将上面的链接复制到浏览器地址栏打开。\n"
        "如果这不是你本人的操作，请忽略此邮件。\n"
    )
    html = _verification_html(verify_url)
    return await send_email(to, subject, text, html)


async def send_plugin_result_email(
    to: str,
    *,
    plugin_name: str,
    application_type: str,
    approved: bool,
    reason: str | None = None,
) -> bool:
    """申请审核结果邮件；调用方必须在数据库事务提交后发送。"""
    action_names = {
        "publish": "首次发布",
        "update": "版本更新",
        "recommend": "推荐申请",
        "delete": "删除申请",
    }
    action = action_names.get(application_type, "插件申请")
    result = "已通过" if approved else "未通过"
    subject = f"[洛谷档案馆] {plugin_name}：{action}{result}"
    text = f"插件：{plugin_name}\n申请类型：{action}\n审核结果：{result}\n"
    if reason:
        text += f"原因：{reason}\n"
    html = _plugin_result_html(
        plugin_name=plugin_name,
        action=action,
        approved=approved,
        reason=reason,
    )
    return await send_email(to, subject, text, html)


async def send_plugin_admin_notice(
    recipients: list[str],
    *,
    event_name: str,
    plugin_name: str,
    detail: str,
) -> None:
    """逐个通知管理员；单封邮件失败只记日志，不影响业务事务。"""
    subject = f"[洛谷档案馆] 新的插件{event_name}：{plugin_name}"
    body = f"插件：{plugin_name}\n事件：{event_name}\n{detail}\n请登录管理后台处理。"
    html = _plugin_admin_notice_html(
        event_name=event_name,
        plugin_name=plugin_name,
        detail=detail,
    )
    for recipient in recipients:
        ok = await send_email(recipient, subject, body, html)
        if not ok:
            log.error(
                "email.plugin_admin_notice_failed",
                to=recipient,
                event=event_name,
                plugin=plugin_name,
            )


async def send_takedown_admin_notice(
    recipients: list[str],
    *,
    target_url: str,
    target_type: str,
    target_id: str,
    requester_name: str | None,
    requester_email: str | None,
    reason: str,
    auto_approved: bool,
) -> None:
    """通知管理员有新的内容删除申请。"""
    state = "作者本人申请，已自动批准" if auto_approved else "等待管理员审核"
    subject = f"[洛谷档案馆] 新的内容删除申请：{target_type}/{target_id}"
    body = (
        f"目标：{target_url}\n"
        f"状态：{state}\n"
        f"申请人：{requester_name or '未填写'}\n"
        f"联系邮箱：{requester_email or '未填写'}\n"
        f"理由：{reason}\n"
        "请登录管理后台查看。"
    )
    html = _takedown_admin_notice_html(
        target_url=target_url,
        target_type=target_type,
        target_id=target_id,
        requester_name=requester_name,
        requester_email=requester_email,
        reason=reason,
        auto_approved=auto_approved,
    )
    for recipient in recipients:
        ok = await send_email(recipient, subject, body, html)
        if not ok:
            log.error(
                "email.takedown_admin_notice_failed",
                to=recipient,
                target_type=target_type,
                target_id=target_id,
            )


async def send_takedown_result_email(
    to: str,
    *,
    target_url: str,
    approved: bool,
    reason: str | None = None,
) -> bool:
    """通知申请人内容删除申请的处理结果。"""
    result = "已批准" if approved else "未批准"
    subject = f"[洛谷档案馆] 内容删除申请{result}"
    body = f"目标：{target_url}\n处理结果：{result}\n"
    if reason:
        body += f"处理说明：{reason}\n"
    html = _takedown_result_html(
        target_url=target_url,
        approved=approved,
        reason=reason,
    )
    return await send_email(to, subject, body, html)


def _plugin_result_html(
    *,
    plugin_name: str,
    action: str,
    approved: bool,
    reason: str | None,
) -> str:
    """生成插件申请审核结果邮件，所有用户内容必须先转义。"""
    brand = "#0969da"
    status_color = "#1a7f37" if approved else "#cf222e"
    status_bg = "#dafbe1" if approved else "#ffebe9"
    result = "审核通过" if approved else "审核未通过"
    reason_html = ""
    if reason:
        reason_html = f"""
          <tr>
            <td style="padding:0 32px 24px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f6f8fa;border-left:4px solid {status_color};border-radius:6px;">
                <tr><td style="padding:14px 16px;">
                  <p style="margin:0 0 5px;font-size:13px;font-weight:700;color:#57606a;">审核说明</p>
                  <p style="margin:0;font-size:14px;line-height:1.7;color:#1f2328;word-break:break-word;">{_email_text(reason)}</p>
                </td></tr>
              </table>
            </td>
          </tr>"""

    manage_url = f"{settings.WEB_PUBLIC_ORIGIN.rstrip('/')}/plugin/manage"
    content = f"""
          <tr>
            <td style="padding:36px 32px 20px;">
              <div style="display:inline-block;margin-bottom:18px;padding:5px 11px;border-radius:999px;background-color:{status_bg};color:{status_color};font-size:13px;font-weight:700;">{result}</div>
              <h1 style="margin:0 0 20px;font-size:21px;color:#1f2328;font-weight:700;">插件申请审核结果</h1>
              {_email_info_table((("插件", plugin_name), ("申请类型", action), ("审核结果", result)))}
            </td>
          </tr>
          {reason_html}
          {_email_button_row(manage_url, "查看我的插件", brand)}"""
    return _email_shell(content)


def _plugin_admin_notice_html(
    *,
    event_name: str,
    plugin_name: str,
    detail: str,
) -> str:
    """生成管理员插件通知邮件，并按事件跳转到对应处理页面。"""
    brand = "#0969da"
    admin_path = "/admin/plugin-reports" if event_name == "举报" else "/admin/plugin-applications"
    admin_url = f"{settings.WEB_PUBLIC_ORIGIN.rstrip('/')}{admin_path}"
    content = f"""
          <tr>
            <td style="padding:36px 32px 20px;">
              <div style="display:inline-block;margin-bottom:18px;padding:5px 11px;border-radius:999px;background-color:#ddf4ff;color:#0969da;font-size:13px;font-weight:700;">待处理</div>
              <h1 style="margin:0 0 20px;font-size:21px;color:#1f2328;font-weight:700;">新的插件{html_lib.escape(event_name)}</h1>
              {_email_info_table((("插件", plugin_name), ("事件", event_name)))}
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 24px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f6f8fa;border-left:4px solid {brand};border-radius:6px;">
                <tr><td style="padding:14px 16px;">
                  <p style="margin:0 0 5px;font-size:13px;font-weight:700;color:#57606a;">提交内容</p>
                  <p style="margin:0;font-size:14px;line-height:1.7;color:#1f2328;word-break:break-word;">{_email_text(detail)}</p>
                </td></tr>
              </table>
            </td>
          </tr>
          {_email_button_row(admin_url, "前往管理后台", brand)}"""
    return _email_shell(content)


def _takedown_admin_notice_html(
    *,
    target_url: str,
    target_type: str,
    target_id: str,
    requester_name: str | None,
    requester_email: str | None,
    reason: str,
    auto_approved: bool,
) -> str:
    """生成管理员内容删除通知邮件。"""
    brand = "#0969da"
    state = "已自动批准" if auto_approved else "待处理"
    state_color = "#1a7f37" if auto_approved else brand
    state_bg = "#dafbe1" if auto_approved else "#ddf4ff"
    admin_url = f"{settings.WEB_PUBLIC_ORIGIN.rstrip('/')}/admin/takedowns"
    content = f"""
          <tr>
            <td style="padding:36px 32px 20px;">
              <div style="display:inline-block;margin-bottom:18px;padding:5px 11px;border-radius:999px;background-color:{state_bg};color:{state_color};font-size:13px;font-weight:700;">{state}</div>
              <h1 style="margin:0 0 20px;font-size:21px;color:#1f2328;font-weight:700;">新的内容删除申请</h1>
              {_email_info_table((("内容类型", target_type), ("内容编号", target_id), ("目标地址", target_url), ("申请人", requester_name or "未填写"), ("联系邮箱", requester_email or "未填写")))}
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 24px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f6f8fa;border-left:4px solid {state_color};border-radius:6px;">
                <tr><td style="padding:14px 16px;">
                  <p style="margin:0 0 5px;font-size:13px;font-weight:700;color:#57606a;">申请理由</p>
                  <p style="margin:0;font-size:14px;line-height:1.7;color:#1f2328;word-break:break-word;">{_email_text(reason)}</p>
                </td></tr>
              </table>
            </td>
          </tr>
          {_email_button_row(admin_url, "查看删除申请", brand)}"""
    return _email_shell(content)


def _takedown_result_html(
    *,
    target_url: str,
    approved: bool,
    reason: str | None,
) -> str:
    """生成申请人内容删除审核结果邮件。"""
    brand = "#0969da"
    status_color = "#1a7f37" if approved else "#cf222e"
    status_bg = "#dafbe1" if approved else "#ffebe9"
    result = "申请已批准" if approved else "申请未批准"
    reason_html = ""
    if reason:
        reason_html = f"""
          <tr>
            <td style="padding:0 32px 24px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f6f8fa;border-left:4px solid {status_color};border-radius:6px;">
                <tr><td style="padding:14px 16px;">
                  <p style="margin:0 0 5px;font-size:13px;font-weight:700;color:#57606a;">处理说明</p>
                  <p style="margin:0;font-size:14px;line-height:1.7;color:#1f2328;word-break:break-word;">{_email_text(reason)}</p>
                </td></tr>
              </table>
            </td>
          </tr>"""
    home_url = settings.WEB_PUBLIC_ORIGIN.rstrip("/")
    content = f"""
          <tr>
            <td style="padding:36px 32px 20px;">
              <div style="display:inline-block;margin-bottom:18px;padding:5px 11px;border-radius:999px;background-color:{status_bg};color:{status_color};font-size:13px;font-weight:700;">{result}</div>
              <h1 style="margin:0 0 20px;font-size:21px;color:#1f2328;font-weight:700;">内容删除申请处理结果</h1>
              {_email_info_table((("目标地址", target_url), ("处理结果", result)))}
            </td>
          </tr>
          {reason_html}
          {_email_button_row(home_url, "返回洛谷档案馆", brand)}"""
    return _email_shell(content)


def _email_text(value: str) -> str:
    """转义邮件中的动态文本，并保留用户输入的自然换行。"""
    return html_lib.escape(value).replace("\n", "<br>")


def _email_info_table(rows: tuple[tuple[str, str], ...]) -> str:
    """生成兼容传统邮件客户端的键值信息表。"""
    cells = "".join(
        f"""<tr>
          <td style="width:88px;padding:8px 12px 8px 0;border-bottom:1px solid #eaecef;color:#8b949e;font-size:14px;vertical-align:top;">{html_lib.escape(label)}</td>
          <td style="padding:8px 0;border-bottom:1px solid #eaecef;color:#1f2328;font-size:14px;font-weight:600;word-break:break-word;">{_email_text(value)}</td>
        </tr>"""
        for label, value in rows
    )
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{cells}</table>'


def _email_button_row(url: str, label: str, color: str) -> str:
    """生成使用 table 布局的邮件操作按钮。"""
    safe_url = html_lib.escape(url, quote=True)
    return f"""
          <tr>
            <td style="padding:4px 32px 32px;">
              <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto;">
                <tr><td align="center" style="border-radius:8px;background-color:{color};">
                  <a href="{safe_url}" target="_blank" style="display:inline-block;padding:12px 32px;font-size:15px;font-weight:600;color:#ffffff;text-decoration:none;border-radius:8px;">{html_lib.escape(label)}</a>
                </td></tr>
              </table>
            </td>
          </tr>"""


def _email_shell(content: str) -> str:
    """复用注册邮件的品牌外框，保持 QQ 邮箱和 Outlook 兼容。"""
    return f"""\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background-color:#f2f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f2f4f7;padding:32px 12px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background-color:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 4px 18px rgba(0,0,0,0.06);">
        <tr><td style="background-color:#0969da;padding:24px 32px;text-align:center;"><span style="color:#ffffff;font-size:20px;font-weight:700;letter-spacing:0.5px;">洛谷档案馆</span></td></tr>
        {content}
        <tr><td style="padding:0 32px;"><div style="border-top:1px solid #eaecef;"></div></td></tr>
        <tr><td style="padding:20px 32px 28px;"><p style="margin:0;font-size:12px;line-height:1.6;color:#8b949e;">本站为第三方存档，与洛谷官方无关。</p></td></tr>
      </table>
      <p style="max-width:520px;margin:16px auto 0;font-size:11px;color:#b0b7c0;text-align:center;">© 2026 洛谷档案馆 · 此邮件由系统自动发送，请勿直接回复</p>
    </td></tr>
  </table>
</body>
</html>"""


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
              <span style="color:#ffffff;font-size:20px;font-weight:700;letter-spacing:0.5px;">洛谷档案馆</span>
            </td>
          </tr>
          <!-- 正文 -->
          <tr>
            <td style="padding:36px 32px 8px;">
              <h1 style="margin:0 0 16px;font-size:21px;color:#1f2328;font-weight:700;">验证你的邮箱</h1>
              <p style="margin:0 0 8px;font-size:15px;line-height:1.7;color:#57606a;">
                你好，感谢注册<strong style="color:#1f2328;">洛谷档案馆</strong>。
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
          © 2026 洛谷档案馆 · 此邮件由系统自动发送，请勿直接回复
        </p>
      </td>
    </tr>
  </table>
</body>
</html>"""
