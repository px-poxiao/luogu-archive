"""TOTP 2FA（管理员）。

流程：
1) 首次添加管理员：生成 secret，密文存库；secret 明文只在"添加成功"那一刻展示一次
   （管理员扫码加到 Google Authenticator / Authy 等）
2) 登录：用户名密码验证后，要求输入 6 位 TOTP → 校验通过才发 session
"""
from __future__ import annotations

import pyotp
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    return Fernet(settings.ADMIN_TOTP_ENCRYPTION_KEY.encode())


def generate_secret() -> str:
    return pyotp.random_base32()


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise ValueError("TOTP secret 解密失败（加密 key 可能换了）") from e


def provisioning_uri(username: str, secret: str) -> str:
    """返回供二维码使用的 otpauth:// URI。"""
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=username,
        issuer_name=settings.ADMIN_2FA_ISSUER,
    )


def verify(secret: str, code: str) -> bool:
    if not code or not code.isdigit() or len(code) != 6:
        return False
    totp = pyotp.TOTP(secret)
    # valid_window=1：允许前后 30 秒偏差，兼容时钟漂移
    return totp.verify(code, valid_window=1)
