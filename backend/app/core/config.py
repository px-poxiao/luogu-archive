from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import CRAWLER_BASE_URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "luogu-archive"
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_LOG_LEVEL: str = "INFO"
    APP_TIMEZONE: str = "Asia/Shanghai"

    WEB_HOST: str = "127.0.0.1"
    WEB_PORT: int = 8000
    WEB_PUBLIC_ORIGIN: str = "http://127.0.0.1:8000"
    WEB_CORS_ORIGINS: str = "http://127.0.0.1:3000"

    DB_HOST: str
    DB_PORT: int = 3306
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10

    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    CRAWLER_BASE_URL: str = CRAWLER_BASE_URL
    CRAWLER_FALLBACK_BASE_URL: str = "https://www.luogu.com.cn"
    CRAWLER_USER_AGENT: str = "Mozilla/5.0"
    CRAWLER_CONTACT_EMAIL: str = ""
    CRAWLER_ANON_RATE_PER_SEC: float = 0.33
    CRAWLER_AUTH_RATE_PER_SEC: float = 0.17
    CRAWLER_AUTH_ACCOUNT_INTERVAL_SEC: int = 5
    CRAWLER_AUTH_QPH_PER_ACCOUNT: int = 300
    CRAWLER_BREAKER_COOLDOWN_SEC: int = 300
    CRAWLER_GLOBAL_BREAKER_NODE_THRESHOLD: int = 3
    CRAWLER_TASK_LOCK_TTL_SEC: int = 30
    CRAWLER_REQUEST_TIMEOUT_SEC: int = 15

    JUDGEMENT_GROUP_TIME_WINDOW_SEC: int = 1800

    ADMIN_2FA_ISSUER: str = "LuoguArchive"
    ADMIN_SESSION_MAX_AGE_SEC: int = 3600
    ADMIN_TOTP_ENCRYPTION_KEY: str

    JWT_SECRET: str
    JWT_ACCESS_TTL_SEC: int = 900
    JWT_REFRESH_TTL_SEC: int = 604800

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@example.com"
    SMTP_USE_TLS: bool = True

    CAPTCHA_PROVIDER: str = "none"
    CAPTCHA_SITE_KEY: str = ""
    CAPTCHA_SECRET: str = ""
    CAPTCHA_TRIGGER_SAVE_PER_MIN: int = 3
    CAPTCHA_TRIGGER_SAVE_PER_10MIN: int = 10
    CAPTCHA_TRIGGER_PAGE_PER_HOUR: int = 600

    SAVE_IP_WINDOW_SEC: int = 60
    SAVE_IP_WINDOW_MAX: int = 5
    SAVE_IP_HOUR_BREAKER_THRESHOLD: int = 10
    SAVE_IP_HOUR_BREAKER_COOLDOWN_SEC: int = 3600

    IMAGE_MIRROR_DIR: str = "data/image_mirror"
    IMAGE_MIRROR_PUBLIC_PREFIX: str = "/static/img"
    IMAGE_MIRROR_MAX_SIZE_MB: int = 20

    DATA_DIR: str = "data"

    @cached_property
    def async_database_url(self) -> str:
        from sqlalchemy.engine import URL

        return URL.create(
            drivername="mysql+aiomysql",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)

    @cached_property
    def sync_database_url(self) -> str:
        from sqlalchemy.engine import URL

        return URL.create(
            drivername="mysql+pymysql",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)


settings = Settings()