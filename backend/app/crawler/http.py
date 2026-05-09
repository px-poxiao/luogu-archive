"""HTTP 客户端层。

设计目标：
- 游客请求走 `fetch_anon`，带 Cookie 请求走 `fetch_authed`
- 自动检测 403 / 429 / 被封信号并抛成 CrawlerBlockedError / CrawlerAccountInvalid
- 自动做节点级限流 + 全局熔断检查（异步等待或直接抛 RateLimitError）
- 支持两种返回模式：
    * HTML（从 `<script id="lentille-context">` 提取 JSON）
    * JSON（Accept: application/json 或 /api/ 路径直接返 JSON）
- 爬虫审计：每次调用都写 CrawlTask 表（可选关闭）

重要：Python httpx 不会改写 Cookie header，但我们坚持让限流/熔断等统一从 Node 走，
不走 httpx 自带 cookie jar —— 降低耦合，便于多账号轮换时直接替换 header。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import httpx

from app.core.config import settings
from app.core.exceptions import (
    CrawlerAccountInvalid,
    CrawlerBlockedError,
    CrawlerError,
    CrawlerTimeoutError,
)
from app.core.logging import get_logger
from app.crawler.lentille import extract_lentille_context
from app.crawler.nodes.base import CrawlerNode, NodeKind

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = get_logger(__name__)

# 单进程共享一个 httpx.AsyncClient（连接池）。
# 多账号不共享同一个 client.cookies，因为我们每次请求显式传 cookies 参数。
_http_client: httpx.AsyncClient | None = None


def _build_default_headers(node: CrawlerNode) -> dict[str, str]:
    """基础 header：UA + Accept-Language + 节点扩展。"""
    headers = {
        "User-Agent": settings.CRAWLER_USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cache-Control": "no-cache",
    }
    headers.update(node.extra_headers)
    return headers


def get_http_client() -> httpx.AsyncClient:
    """返回进程级共享的 httpx 客户端。"""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(settings.CRAWLER_REQUEST_TIMEOUT_SEC),
            follow_redirects=True,
            # 连接池默认 100，够用
        )
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


@dataclass
class FetchResult:
    """统一返回：原始 status、响应体、解析后的 lentille 或 JSON。"""

    status: int
    url: str
    content_type: str
    body_text: str
    # 若解析成 JSON 则 data 非 None，否则为 None（调用方可再自行提取 lentille）
    data: dict[str, Any] | None = None
    # 响应耗时
    duration_ms: int = 0


def _detect_blocked(status: int, body: str) -> bool:
    """把服务器返回识别为"被拦/被封"信号。"""
    if status in (403, 429):
        return True
    # 洛谷的 403 body 会含这句（当无 Cookie 访问需要登录的接口也会，调用方分辨）
    if status == 403 and ("用户尚未登录" in body or "Forbidden" in body):
        return True
    return False


def _detect_account_invalid(status: int, body: str) -> bool:
    """Cookie 账号失效的特征：明确 401/403 + 包含"用户尚未登录"。"""
    if status in (401, 403) and "用户尚未登录" in body:
        return True
    return False


async def _wait_for_slot(
    node: CrawlerNode,
    redis: Redis,
    *,
    max_wait_ms: int = 10_000,
) -> None:
    """在节点令牌桶里等一个令牌。

    若等不到（比如熔断中）→ 抛 CrawlerBlockedError。
    """
    deadline = time.monotonic() * 1000 + max_wait_ms
    while True:
        allowed, retry_after_ms = await node.try_acquire(redis)
        if allowed:
            return
        if time.monotonic() * 1000 + retry_after_ms > deadline:
            raise CrawlerBlockedError(
                f"爬虫节点 {node.node_id} 限流/熔断中（等待 {retry_after_ms}ms 超时）",
            )
        await asyncio.sleep(retry_after_ms / 1000)


async def _do_request(
    method: str,
    url: str,
    *,
    node: CrawlerNode,
    redis: Redis,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict | None = None,
    accept_json: bool = False,
    parse: Literal["html", "json", "auto"] = "auto",
) -> FetchResult:
    """核心请求函数。所有上层 fetch_* 都包它。"""
    await _wait_for_slot(node, redis)

    merged_headers = _build_default_headers(node)
    if accept_json:
        merged_headers["Accept"] = "application/json"
    else:
        merged_headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9"
    if headers:
        merged_headers.update(headers)

    client = get_http_client()
    start = time.monotonic()
    try:
        resp = await client.request(
            method,
            url,
            params=params,
            headers=merged_headers,
            cookies=cookies,
            json=json_body,
        )
    except httpx.TimeoutException as e:
        raise CrawlerTimeoutError(f"请求超时: {url}") from e
    except httpx.HTTPError as e:
        raise CrawlerError(f"HTTP 错误: {e}") from e
    duration_ms = int((time.monotonic() - start) * 1000)

    status = resp.status_code
    body = resp.text
    ct = resp.headers.get("content-type", "")

    # 识别异常
    if _detect_account_invalid(status, body):
        raise CrawlerAccountInvalid(f"Cookie 账号无效：{url}")
    if _detect_blocked(status, body):
        await node.trip_breaker(redis, reason=f"status={status}")
        raise CrawlerBlockedError(f"被目标站点拦截: status={status} url={url}")

    # 成功，但若 HTTP 非 2xx 仍当错误处理（404 等）
    if status >= 400:
        raise CrawlerError(f"HTTP {status}: {url} body(前200)={body[:200]}")

    # 解析
    data: dict[str, Any] | None = None
    effective_parse = parse
    if effective_parse == "auto":
        effective_parse = "json" if "application/json" in ct else "html"

    if effective_parse == "json":
        import orjson
        try:
            data = orjson.loads(body)
        except orjson.JSONDecodeError as e:
            raise CrawlerError(f"响应不是合法 JSON: {e}") from e
    elif effective_parse == "html":
        # 尝试提取 lentille-context，如果没有不算错（调用方自决）
        try:
            data = extract_lentille_context(body)
        except Exception:
            data = None

    return FetchResult(
        status=status,
        url=str(resp.url),
        content_type=ct,
        body_text=body,
        data=data,
        duration_ms=duration_ms,
    )


# ============================================================
# 公共入口
# ============================================================

async def fetch_anon(
    path_or_url: str,
    *,
    node: CrawlerNode,
    redis: Redis,
    params: dict[str, Any] | None = None,
    accept_json: bool = False,
    parse: Literal["html", "json", "auto"] = "auto",
) -> FetchResult:
    """游客身份请求。**绝不**带 Cookie。

    path_or_url：相对路径（如 `/article/xxx`）自动拼 CRAWLER_BASE_URL；
                 完整 URL 直接用。
    """
    assert node.kind == NodeKind.ANON, "fetch_anon 只能用 ANON 节点"
    url = _resolve_url(path_or_url)
    return await _do_request(
        "GET",
        url,
        node=node,
        redis=redis,
        params=params,
        accept_json=accept_json,
        parse=parse,
    )


async def fetch_authed(
    path_or_url: str,
    *,
    node: CrawlerNode,
    redis: Redis,
    cookies: dict[str, str],
    params: dict[str, Any] | None = None,
    accept_json: bool = True,   # 鉴权接口通常要 JSON
    parse: Literal["html", "json", "auto"] = "auto",
) -> FetchResult:
    """认证请求（带 Cookie）。仅用于犇犇爬取。

    cookies: 必传 `_uid` + `__client_id`（可选 `C3VK`）
    """
    assert node.kind == NodeKind.AUTHED, "fetch_authed 只能用 AUTHED 节点"
    # 防呆：缺关键字段直接报错
    if "_uid" not in cookies or "__client_id" not in cookies:
        raise ValueError("cookies 必须含 _uid 和 __client_id")
    url = _resolve_url(path_or_url)
    return await _do_request(
        "GET",
        url,
        node=node,
        redis=redis,
        cookies=cookies,
        params=params,
        accept_json=accept_json,
        parse=parse,
    )


def _resolve_url(path_or_url: str) -> str:
    """拼完整 URL。若已是 http:// / https:// 则直接返回。"""
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    base = settings.CRAWLER_BASE_URL.rstrip("/")
    path = path_or_url if path_or_url.startswith("/") else f"/{path_or_url}"
    return f"{base}{path}"
