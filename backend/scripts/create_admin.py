"""CLI 工具：新建管理员。

用法：
    cd backend
    python -m scripts.create_admin

交互式输入用户名、密码、显示名。执行后在终端输出 TOTP 二维码的 otpauth:// URI，
也可选打印为 QR 字符到控制台（如果安装了 qrcode）。

生产环境首次用来创建超级管理员；后续新增也走这个脚本，不做 Web 端注册。
"""
from __future__ import annotations

import asyncio
import getpass
import sys

from sqlalchemy import select

from app.auth.passwords import hash_password
from app.auth.totp import encrypt_secret, generate_secret, provisioning_uri
from app.core.db import db_session
from app.models.admin import Admin


async def main() -> None:
    username = input("管理员用户名: ").strip()
    display_name = input("显示名（可与用户名相同）: ").strip() or username
    password = getpass.getpass("密码（至少 10 位）: ")
    password2 = getpass.getpass("确认密码: ")
    if password != password2 or len(password) < 10:
        print("两次输入不一致，或密码长度不足。", file=sys.stderr)
        sys.exit(1)

    async with db_session() as session:
        q = select(Admin).where(Admin.username == username)
        if (await session.execute(q)).scalar_one_or_none() is not None:
            print("用户名已存在。", file=sys.stderr)
            sys.exit(1)

        secret = generate_secret()
        admin = Admin(
            username=username,
            password_hash=hash_password(password),
            totp_secret_encrypted=encrypt_secret(secret),
            display_name=display_name,
        )
        session.add(admin)
        await session.commit()

    uri = provisioning_uri(username, secret)
    print("\n========= 管理员创建成功 =========")
    print(f"用户名: {username}")
    print(f"TOTP 明文 secret（**只显示这一次**，请立即加入 Authy/Google Authenticator）：\n  {secret}")
    print(f"或扫描下面的 otpauth URI：\n  {uri}")
    print("\n（扫码或手动输入 secret 后，下次登录需要附带 6 位 TOTP 验证码）")


if __name__ == "__main__":
    asyncio.run(main())
