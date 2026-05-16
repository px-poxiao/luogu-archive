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
    CrawlerNotFound,
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
    """把服务器返回识别为"节点级被拦"信号 —— 触发熔断时调用。

    重要：只把"我们被洛谷整体拦截"识别为 blocked。
    单个目标用户/页面被洛谷 403（封号、锁主页、隐私设置等）**不算**节点被拦。
    误判会导致一个封号用户拖瘫全站匿名爬虫 5 分钟（节点冷却期）。

    判别规则：
      - 429（频率限制）：明确节点级，必拦
      - 403 + body 含 Cloudflare / 通用 nginx forbidden 标志：节点级
      - 其他 403：当成内容级（404 类）处理，不熔断
    """
    if status == 429:
        return True
    if status == 403:
        b = body.lower()
        cf_signals = (
            "cloudflare",
            "attention required",
            "checking your browser",
            "<title>403 forbidden</title>",  # nginx 默认 403 页
            "请求过于频繁",
            "ip 地址不在白名单",
        )
        if any(s in b for s in cf_signals):
            return True
    return False


def _detect_account_invalid(status: int, body: str, cookies_present: bool) -> bool:
    """Cookie 账号失效的特征：

    - 401 直接判失效
    - 403 + body 含"用户尚未登录"
    - 403 + 我们带了 cookie 请求（理论上不该 403）+ body 是 API JSON 错误（短）
      （洛谷 API 401 风格：返回 403 + JSON 错误体；body 长度 < 1KB）
    """
    if not cookies_present:
        return False  # 匿名请求的 401/403 不算账号失效，是节点级问题
    if status == 401:
        return True
    if status == 403:
        if "用户尚未登录" in body:
            return True
        # 短 body + JSON 关键字 = 多半是 API 鉴权失败而非 Cloudflare 拦截
        if len(body) < 1024 and (body.lstrip().startswith("{") or "errorMessage" in body):
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
    if _detect_account_invalid(status, body, cookies_present=cookies is not None):
        raise CrawlerAccountInvalid(f"Cookie 账号无效：{url}")
    if _detect_blocked(status, body):
        await node.trip_breaker(redis, reason=f"status={status}")
        raise CrawlerBlockedError(f"被目标站点拦截: status={status} url={url}")

    # 404 / 内容级 403（用户被封号/隐私页/不存在）：不熔断、不重试
    if status == 404 or status == 403:
        raise CrawlerNotFound(f"内容不可访问: status={status} url={url}")

    # 其他 4xx/5xx 当作可重试错误
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
    """拼完整 URL。若已是 http:// / https:// 则直接返回。

    按内容类型分派域名：
    - 走主站 www.luogu.com.cn 的路径（更稳定、陶片/题目/犇犇）：
        /judgement, /problem/..., /api/feed/...
    - 其他路径（文章、剪贴板、用户主页、入口发现）走 CRAWLER_BASE_URL（默认海外镜像）。

    目的：海外镜像对某些 API 会 503 或返回 HTML，这些特定内容强制走主站。
    """
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    path = path_or_url if path_or_url.startswith("/") else f"/{path_or_url}"
    # 主站强制路径（最稳定）
    cn_prefixes = ("/judgement", "/problem", "/api/feed")
    if any(path.startswith(p) for p in cn_prefixes):
        base = "https://www.luogu.com.cn"
    else:
        base = settings.CRAWLER_BASE_URL.rstrip("/")
    return f"{base}{path}"
