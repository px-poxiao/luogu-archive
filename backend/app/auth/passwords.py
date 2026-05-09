"""argon2 密码哈希。

argon2 比 bcrypt/scrypt 更新、更抗 GPU 破解，OWASP 推荐。
"""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# time_cost/memory_cost/parallelism 用默认即可（≈ 50~100ms 哈希时间）
_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def needs_rehash(hashed: str) -> bool:
    """argon2 参数升级后旧哈希需要重建。"""
    return _hasher.check_needs_rehash(hashed)
