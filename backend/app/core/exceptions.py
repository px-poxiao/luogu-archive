"""自定义异常体系。

分层：
- AppError：应用层异常基类，带 http_status + error_code
- CrawlerError 及子类：爬虫相关
- AuthError / RateLimitError / CaptchaRequired：API 层

在 FastAPI 里通过全局 exception_handler 统一转 JSON 返回。
"""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    """应用层异常基类。子类覆盖 http_status + error_code。"""

    http_status: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str = "", *, data: Any = None) -> None:
        super().__init__(message)
        self.message = message or self.error_code
        self.data = data


# ---------- 通用 ----------
class NotFoundError(AppError):
    http_status = 404
    error_code = "not_found"


class ValidationError(AppError):
    http_status = 422
    error_code = "validation_failed"


class ForbiddenError(AppError):
    http_status = 403
    error_code = "forbidden"


class ConflictError(AppError):
    http_status = 409
    error_code = "conflict"


# ---------- 认证 ----------
class AuthError(AppError):
    http_status = 401
    error_code = "auth_failed"


class TwoFactorRequired(AppError):
    http_status = 401
    error_code = "2fa_required"


# ---------- 限流 / 防刷 ----------
class RateLimitError(AppError):
    http_status = 429
    error_code = "rate_limited"

    def __init__(
        self,
        message: str = "请求过于频繁",
        *,
        retry_after_sec: int = 0,
        data: Any = None,
    ) -> None:
        super().__init__(message, data=data)
        self.retry_after_sec = retry_after_sec


class CaptchaRequired(AppError):
    """触发人机验证。前端收到后应弹出验证码组件。"""

    http_status = 428
    error_code = "captcha_required"


class IpBlocked(AppError):
    http_status = 403
    error_code = "ip_blocked"


# ---------- 爬虫 ----------
class CrawlerError(AppError):
    """爬虫相关错误基类。"""

    http_status = 502
    error_code = "crawler_error"


class CrawlerNotFound(CrawlerError):
    """目标内容不存在（HTTP 404）。不应触发熔断，也不该重试。"""

    error_code = "crawler_not_found"


class CrawlerBlockedError(CrawlerError):
    """被目标站点阻止（403/429）。触发节点熔断。"""

    error_code = "crawler_blocked"


class CrawlerTimeoutError(CrawlerError):
    http_status = 504
    error_code = "crawler_timeout"


class CrawlerAccountInvalid(CrawlerError):
    """Cookie 账号失效（返回"用户尚未登录"）。立即禁用该账号并告警。"""

    error_code = "crawler_account_invalid"


class CrawlerAccountBanned(CrawlerError):
    """Cookie 账号被洛谷封禁（isBanned=true 或其他信号）。最高级别告警。"""

    error_code = "crawler_account_banned"
