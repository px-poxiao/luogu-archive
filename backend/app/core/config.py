"""应用全局配置 —— 从 .env 加载，类型安全。

用法：
    from app.core.config import settings
    settings.DB_HOST, settings.CRAWLER_BASE_URL ...

所有环境变量集中在这一个文件，避免散落各处。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从 .env 读取。字段名对应 .env.example 中的 key。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 基础 ----------
    APP_NAME: str = "luogu-archive"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_DEBUG: bool = True
    APP_LOG_LEVEL: str = "INFO"
    APP_TIMEZONE: str = "Asia/Shanghai"

    # ---------- Web ----------
    WEB_HOST: str = "0.0.0.0"
    WEB_PORT: int = 8000
    WEB_PUBLIC_ORIGIN: str = "http://localhost:3000"
    WEB_CORS_ORIGINS: str = "http://localhost:3000"  # 逗号分隔字符串

    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔字符串拆成 list，供 CORSMiddleware 使用。"""
        return [o.strip() for o in self.WEB_CORS_ORIGINS.split(",") if o.strip()]

    # ---------- 数据库 ----------
    DB_HOST: str
    DB_PORT: int = 3306
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10

    @property
    def async_database_url(self) -> str:
        """SQLAlchemy 异步驱动使用的连接串。"""
        return (
            f"mysql+aiomysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )

    @property
    def sync_database_url(self) -> str:
        """同步连接串，Alembic 迁移使用。"""
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )

    # ---------- Redis ----------
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    # ---------- 爬虫 ----------
    CRAWLER_BASE_URL: str = "https://www.luogu.com.cn"
    CRAWLER_FALLBACK_BASE_URL: str = "https://luogu.com"
    CRAWLER_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/79.0.3945.130 Safari/537.36"
    )
    CRAWLER_CONTACT_EMAIL: str = "archive-bot@example.com"
    CRAWLER_ANON_RATE_PER_SEC: float = 0.33
    CRAWLER_AUTH_RATE_PER_SEC: float = 0.17
    CRAWLER_AUTH_QPH_PER_ACCOUNT: int = 300
    CRAWLER_BREAKER_COOLDOWN_SEC: int = 300
    CRAWLER_GLOBAL_BREAKER_NODE_THRESHOLD: int = 3
    CRAWLER_TASK_LOCK_TTL_SEC: int = 30
    CRAWLER_REQUEST_TIMEOUT_SEC: int = 15

    # ---------- 陶片 ----------
    JUDGEMENT_GROUP_TIME_WINDOW_SEC: int = 1800

    # ---------- 管理员 ----------
    ADMIN_2FA_ISSUER: str = "LuoguArchive"
    ADMIN_SESSION_MAX_AGE_SEC: int = 3600
    ADMIN_TOTP_ENCRYPTION_KEY: str

    # ---------- JWT ----------
    JWT_SECRET: str
    JWT_ACCESS_TTL_SEC: int = 900
    JWT_REFRESH_TTL_SEC: int = 604800

    # ---------- 邮件 ----------
    SMTP_HOST: str = "smtp.example.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = "noreply@example.com"
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@example.com"
    SMTP_USE_TLS: bool = True

    # ---------- 人机验证 ----------
    CAPTCHA_PROVIDER: Literal["turnstile", "hcaptcha", "none"] = "turnstile"
    CAPTCHA_SITE_KEY: str = ""
    CAPTCHA_SECRET: str = ""
    CAPTCHA_TRIGGER_SAVE_PER_MIN: int = 3
    CAPTCHA_TRIGGER_SAVE_PER_10MIN: int = 10
    CAPTCHA_TRIGGER_PAGE_PER_HOUR: int = 600

    # ---------- 保存按钮限流 ----------
    SAVE_IP_WINDOW_SEC: int = 60
    SAVE_IP_WINDOW_MAX: int = 5
    SAVE_IP_HOUR_BREAKER_THRESHOLD: int = 10
    SAVE_IP_HOUR_BREAKER_COOLDOWN_SEC: int = 3600

    # ---------- 图片镜像 ----------
    IMAGE_MIRROR_DIR: str = "./data/image_mirror"
    IMAGE_MIRROR_PUBLIC_PREFIX: str = "/static/img"
    IMAGE_MIRROR_MAX_SIZE_MB: int = 20

    # ---------- 数据目录 ----------
    DATA_DIR: str = "./data"

    @field_validator("CRAWLER_USER_AGENT")
    @classmethod
    def _append_contact_to_ua(cls, v: str) -> str:
        """若 UA 没带联系信息，开发期允许；生产期由 deploy 脚本校验。"""
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例。第一次调用时从 .env 读取，之后复用。"""
    return Settings()  # type: ignore[call-arg]


# 快捷别名，方便导入
settings: Settings = get_settings()
