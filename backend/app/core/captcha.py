"""人机验证（Turnstile / hCaptcha / 阿里云验证码 2.0）校验。"""
from __future__ import annotations

import asyncio

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_TURNSTILE_VERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_HCAPTCHA_VERIFY = "https://hcaptcha.com/siteverify"
_ALIYUN_ENDPOINTS = {
    "cn": "captcha.cn-shanghai.aliyuncs.com",
    "sgp": "captcha.ap-southeast-1.aliyuncs.com",
}


async def verify_captcha(token: str, ip: str | None = None) -> bool:
    """调第三方验证 token。失败或 provider=none 都返回对应结果。"""
    if settings.CAPTCHA_PROVIDER == "none":
        return True
    if not token:
        return False

    if settings.CAPTCHA_PROVIDER == "aliyun":
        return await _verify_aliyun_captcha(token)

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


async def _verify_aliyun_captcha(token: str) -> bool:
    """调用阿里云 VerifyIntelligentCaptcha 校验前端透传的 CaptchaVerifyParam。"""
    if not (
        settings.CAPTCHA_ALIYUN_ACCESS_KEY_ID
        and settings.CAPTCHA_ALIYUN_ACCESS_KEY_SECRET
        and settings.CAPTCHA_ALIYUN_SCENE_ID
    ):
        log.warning("captcha.aliyun_config_not_set")
        return False

    try:
        from alibabacloud_captcha20230305.client import Client as CaptchaClient
        from alibabacloud_captcha20230305 import models as captcha_models
        from alibabacloud_tea_openapi import models as openapi_models
        from alibabacloud_tea_util import models as util_models
    except Exception as e:
        log.error("captcha.aliyun_sdk_import_failed", error=str(e))
        return False

    endpoint = (
        settings.CAPTCHA_ALIYUN_ENDPOINT
        or _ALIYUN_ENDPOINTS.get(settings.CAPTCHA_ALIYUN_REGION, _ALIYUN_ENDPOINTS["cn"])
    )

    def _call() -> bool:
        config = openapi_models.Config(
            access_key_id=settings.CAPTCHA_ALIYUN_ACCESS_KEY_ID,
            access_key_secret=settings.CAPTCHA_ALIYUN_ACCESS_KEY_SECRET,
        )
        config.endpoint = endpoint
        client = CaptchaClient(config)
        req = captcha_models.VerifyIntelligentCaptchaRequest(
            captcha_verify_param=token,
            scene_id=settings.CAPTCHA_ALIYUN_SCENE_ID,
        )
        resp = client.verify_intelligent_captcha_with_options(req, util_models.RuntimeOptions())
        body = getattr(resp, "body", None)
        result = getattr(body, "result", None)
        ok = bool(
            getattr(body, "success", False)
            and result is not None
            and getattr(result, "verify_result", False)
        )
        if not ok:
            log.warning(
                "captcha.aliyun_verify_failed",
                code=getattr(body, "code", None),
                verify_code=getattr(result, "verify_code", None) if result else None,
                request_id=getattr(body, "request_id", None),
            )
        return ok

    try:
        # 阿里云 SDK 是同步调用，放到线程里避免阻塞 FastAPI 事件循环。
        return await asyncio.to_thread(_call)
    except Exception as e:
        log.error("captcha.aliyun_verify_error", error=str(e))
        return False
