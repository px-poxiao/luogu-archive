"""人机验证（Turnstile / hCaptcha）校验。"""
from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_TURNSTILE_VERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_HCAPTCHA_VERIFY = "https://hcaptcha.com/siteverify"


async def verify_captcha(token: str, ip: str | None = None) -> bool:
    """调第三方验证 token。失败或 provider=none 都返回对应结果。"""
    if settings.CAPTCHA_PROVIDER == "none":
        return True
    if not token:
        return False
    if not settings.CAPTCHA_SECRET:
        log.warning("captcha.secret_not_set")
        return False

    if settings.CAPTCHA_PROVIDER == "turnstile":
        url = _TURNSTILE_VERIFY
    elif settings.CAPTCHA_PROVIDER == "hcaptcha":
        url = _HCAPTCHA_VERIFY
    else:
        return False

    data = {"secret": settings.CAPTCHA_SECRET, "response": token}
    if ip:
        data["remoteip"] = ip

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, data=data)
            result = resp.json()
            return bool(result.get("success", False))
    except Exception as e:
        log.error("captcha.verify_failed", error=str(e))
        return False
