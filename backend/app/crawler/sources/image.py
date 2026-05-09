"""图片镜像下载。

原图挂掉后本站仍可展示历史内容，这是存档站的核心价值之一。

流程：
1. 渲染管线扫描到 `<img src=...>` 或 markdown `![](url)`，对外链图 URL 调
   `ensure_mirror(url)`
2. 本函数查 DB 是否已镜像过；没有则下载到 IMAGE_MIRROR_DIR，写入映射表，
   返回本站 /static/img/<hash>.<ext>
3. 下载失败 / 超限则回退到原 URL，让浏览器自己请求（至少保持当前可用）

设计上不做实时重试：镜像是后台任务，原图暂时不可用不影响当前访问。
"""
from __future__ import annotations

import hashlib
import os
import time as _t
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def _ext_from_url(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"):
        if path.endswith(ext):
            return ext
    return ".bin"


def _hash_key(url: str) -> str:
    """用 URL 的 sha1 做文件名，稳定且跨机器一致。"""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _target_path(url: str) -> tuple[Path, str]:
    """返回 (本地路径, 公开 URL)。分两级目录避免单目录文件数爆炸。"""
    key = _hash_key(url)
    ext = _ext_from_url(url)
    rel = f"{key[:2]}/{key[2:4]}/{key}{ext}"
    local = Path(settings.IMAGE_MIRROR_DIR) / rel
    public = f"{settings.IMAGE_MIRROR_PUBLIC_PREFIX.rstrip('/')}/{rel}"
    return local, public


async def ensure_mirror(url: str, *, max_size_bytes: int | None = None) -> str:
    """若未镜像则下载，返回本站可访问路径。失败则返回原 URL。"""
    if not url.startswith(("http://", "https://")):
        return url

    local, public = _target_path(url)
    if local.exists():
        return public

    max_bytes = max_size_bytes or settings.IMAGE_MIRROR_MAX_SIZE_MB * 1024 * 1024
    try:
        local.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30),
            follow_redirects=True,
        ) as client:
            start = _t.monotonic()
            async with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    log.warning("image.http_error", url=url, status=resp.status_code)
                    return url
                cl = resp.headers.get("content-length")
                if cl and int(cl) > max_bytes:
                    log.warning("image.too_large", url=url, size=cl)
                    return url

                total = 0
                tmp_path = local.with_suffix(local.suffix + ".part")
                with tmp_path.open("wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        total += len(chunk)
                        if total > max_bytes:
                            f.close()
                            os.unlink(tmp_path)
                            log.warning("image.streamed_too_large", url=url, size=total)
                            return url
                        f.write(chunk)
                os.rename(tmp_path, local)
            dur = int((_t.monotonic() - start) * 1000)
            log.info("image.mirrored", url=url, size=total, duration_ms=dur)
            return public
    except Exception as e:
        log.warning("image.download_failed", url=url, error=str(e))
        return url
