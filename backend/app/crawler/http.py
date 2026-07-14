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
from contextlib import asynccontextmanager
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
from app.core.ratelimit import CompletionCooldownLimiter, ratelimit_key
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

    保守判断：默认所有 403 都不熔断（视作目标级问题）。
    只有出现明确的 Cloudflare 拦截标志（强信号），才单次直接熔断。
    其他弱信号（普通 "<title>403 Forbidden</title>" 这种，洛谷"无权限"
    内容也会有）一律不在这里熔断 —— 改由 _CONSECUTIVE_4XX_THRESHOLD 累计
    + 同类资源探针确认（见 _confirm_blocked_via_probe）。
    """
    if status == 429:
        return True
    if status == 403:
        b = body.lower()
        # 强信号：明确的反爬拦截页，命中即熔断
        strong_cf_signals = (
            "cloudflare",
            "attention required",
            "checking your browser",
            "请求过于频繁",
            "ip 地址不在白名单",
        )
        if any(s in b for s in strong_cf_signals):
            return True
    return False


def _probe_url_for(failed_url: str) -> str:
    """根据失败的请求 URL 选探针目标 —— 同类型已知公开可访问的样本。

    文章接口故障最常见的就是某篇文章被设置为不公开 → 403。这种情况下应该
    用一篇**确知公开**的文章去验证节点本身是否可用，而不是用 user/1（用户
    主页几乎不可能 403，会假阴性）。
    """
    if "/article/" in failed_url:
        return "https://www.luogu.com.cn/article/cznleq5o"
    return "https://www.luogu.com.cn/user/1"


# 节点级"连续 403 计数"key（短窗口）
def _consecutive_4xx_key(node_id: str) -> str:
    return f"crawler:node:{node_id}:cons_4xx"


# 节点连续 4xx 阈值（这么多次后做一次自检确认是不是被全站拦了）
_CONSECUTIVE_4XX_THRESHOLD = 8
# 计数器窗口（秒）：在这个窗口内累计达到阈值才算
_CONSECUTIVE_4XX_WINDOW = 120


async def _confirm_blocked_via_probe(node, redis: Redis, *, failed_url: str) -> bool:
    """节点级自检：访问一个稳定页面（同类型已知公开样本），如果连这个都返 4xx，
    说明真的被全站拦了。

    返回 True = 真被拦，应触发熔断
    返回 False = 探针通过，前面那些 403 是目标级问题，不熔断
    """
    probe_url = _probe_url_for(failed_url)
    headers = _build_default_headers(node)
    headers["Accept"] = "text/html,application/xhtml+xml"
    client = get_http_client()
    try:
        async with _request_slots(node, redis):
            r = await client.get(probe_url, headers=headers, timeout=10)
        if r.status_code == 200:
            log.info("crawler.probe_ok", node_id=node.node_id, url=probe_url)
            return False
        log.warning(
            "crawler.probe_failed",
            node_id=node.node_id,
            url=probe_url,
            status=r.status_code,
        )
        return True
    except Exception as e:
        log.warning("crawler.probe_error", node_id=node.node_id, error=str(e))
        # 探针失败不能误熔断（可能是探针自己网络抖了）
        return False


def _detect_account_invalid(status: int, body: str, cookies_present: bool) -> bool:
    """Cookie 账号失效的特征（只有这种情况才禁用账号）：

    - 401 + 带了 cookie：肯定是 cookie 失效（匿名 401 是节点级别）
    - 403 + 带了 cookie + body 含我方失败标志（"用户尚未登录"）

    其他 403（包括 JSON 错误体、Cloudflare 拦截等）一律不算账号失效。
    我们之前犯过的错：把"对方用户被禁言"的 403 也判成 cookie 失效，
    结果误禁了完全好的账号。
    """
    if not cookies_present:
        return False
    if status == 401:
        return True
    if status == 403 and "用户尚未登录" in body:
        return True
    return False


async def _wait_for_slot(
    node: CrawlerNode,
    redis: Redis,
    *,
    deadline: float,
) -> str:
    """等待并占用节点完成冷却门。

    若等不到（比如熔断中）→ 抛 CrawlerBlockedError。
    """
    lease_sec = max(float(settings.CRAWLER_REQUEST_TIMEOUT_SEC) + 30.0, 60.0)
    while True:
        token, retry_after_ms = await node.try_acquire(redis, lease_sec=lease_sec)
        if token is not None:
            return token
        remaining_sec = deadline - time.monotonic()
        if remaining_sec <= 0:
            raise CrawlerBlockedError(
                f"爬虫节点 {node.node_id} 限流/熔断中（等待冷却名额超时）",
            )
        await asyncio.sleep(min(retry_after_ms / 1000, remaining_sec))


async def _wait_for_account_slot(
    account_id: int,
    redis: Redis,
    *,
    deadline: float,
    lease_sec: float,
) -> tuple[str, str]:
    """等待并占用跨 worker 共享的账号完成冷却门。"""
    limiter = CompletionCooldownLimiter(redis)
    key = ratelimit_key("crawler_account_request", str(account_id))

    while True:
        token, retry_after_ms = await limiter.acquire(
            key,
            lease_sec=lease_sec,
        )
        if token is not None:
            return key, token
        remaining_sec = deadline - time.monotonic()
        if remaining_sec <= 0:
            raise CrawlerBlockedError(
                f"爬取账号 {account_id} 请求限流中（等待冷却名额超时）"
            )
        await asyncio.sleep(min(retry_after_ms / 1000, remaining_sec))


async def _finish_account_slot(
    redis: Redis,
    slot: tuple[str, str],
) -> bool:
    key, token = slot
    return await CompletionCooldownLimiter(redis).finish(
        key,
        token,
        cooldown_sec=max(float(settings.CRAWLER_AUTH_ACCOUNT_INTERVAL_SEC), 0.001),
    )


async def _cancel_account_slot(
    redis: Redis,
    slot: tuple[str, str],
) -> bool:
    key, token = slot
    return await CompletionCooldownLimiter(redis).release(key, token)


@asynccontextmanager
async def _request_slots(
    node: CrawlerNode,
    redis: Redis,
    *,
    account_id: int | None = None,
):
    """在一次 HTTP 请求期间占用账号门和域名门，结束后分别开始冷却。"""
    account_cooldown_sec = (
        max(float(settings.CRAWLER_AUTH_ACCOUNT_INTERVAL_SEC), 0.001)
        if account_id is not None
        else 0.0
    )
    max_wait_sec = max(node.cooldown_sec, account_cooldown_sec)
    deadline = time.monotonic() + max_wait_sec
    # 账号门先获取，租约需覆盖剩余等待预算、请求超时和清理余量。
    account_lease_sec = max_wait_sec + float(settings.CRAWLER_REQUEST_TIMEOUT_SEC) + 30.0

    account_slot: tuple[str, str] | None = None
    if account_id is not None:
        account_slot = await _wait_for_account_slot(
            account_id,
            redis,
            deadline=deadline,
            lease_sec=account_lease_sec,
        )

    try:
        node_token = await _wait_for_slot(node, redis, deadline=deadline)
    except BaseException:
        if account_slot is not None:
            await _cancel_account_slot(redis, account_slot)
        raise

    try:
        yield
    finally:
        finish_calls = [node.finish_request(redis, node_token)]
        if account_slot is not None:
            finish_calls.append(_finish_account_slot(redis, account_slot))
        results = await asyncio.gather(*finish_calls, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                log.error("crawler.cooldown_finish_failed", error=str(result))


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
    account_id: int | None = None,
) -> FetchResult:
    """核心请求函数。所有上层 fetch_* 都包它。

    cookies 参数路径下，使用一个**临时**的 httpx client（不共用全局 _http_client），
    避免长期进程里匿名请求积累的 Cloudflare cookie 与显式传入的 cookie 冲突
    导致 403。匿名路径继续使用共享 client + 连接池。
    """
    merged_headers = _build_default_headers(node)
    if accept_json:
        merged_headers["Accept"] = "application/json"
    else:
        merged_headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9"
    if headers:
        merged_headers.update(headers)

    use_isolated_client = cookies is not None
    start = time.monotonic()
    async with _request_slots(node, redis, account_id=account_id):
        try:
            if use_isolated_client:
                # 一次性 client，每次请求干净的 cookie jar，不被旧 __cf_bm 污染
                async with httpx.AsyncClient(
                    http2=True,
                    timeout=httpx.Timeout(settings.CRAWLER_REQUEST_TIMEOUT_SEC),
                    follow_redirects=True,
                ) as isolated:
                    resp = await isolated.request(
                        method,
                        url,
                        params=params,
                        headers=merged_headers,
                        cookies=cookies,
                        json=json_body,
                    )
            else:
                resp = await get_http_client().request(
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

    # 调试：cookie 路径下的 4xx 把发出去的 cookie key 打出来（不打值），
    # 帮排查"cookie 实际是不是传出去了"
    if cookies and status >= 400:
        sent_cookie_keys = sorted(cookies.keys()) if cookies else []
        log.warning(
            "fetch.authed_4xx",
            url=str(resp.url),
            status=status,
            sent_cookie_keys=sent_cookie_keys,
            req_cookie_header_present="cookie" in {k.lower() for k in resp.request.headers.keys()},
            body_head=body[:300],
        )

    # 识别异常
    if _detect_account_invalid(status, body, cookies_present=cookies is not None):
        raise CrawlerAccountInvalid(f"Cookie 账号无效：{url}")

    # 429（上游主动节流）→ 直接熔断，不需探针
    if status == 429:
        await node.trip_breaker(redis, reason="status=429")
        raise CrawlerBlockedError(f"被目标站点拦截: status=429 url={url}")

    # 403 / 404：先累计连续 4xx 计数；达阈值 → 探针自检 → 探针失败才熔断。
    # 不管 body 里有没有 "cloudflare" 字样，都走这个路径 —— 洛谷被官方 ban
    # 的文章 / 被封禁用户都会返 403 + 含 cloudflare 元数据，单次熔断会
    # 把整个节点锁死 5 分钟，全站保存不了。
    if status == 404 or status == 403:
        if status == 403:
            cnt_key = _consecutive_4xx_key(node.node_id)
            cnt = await redis.incr(cnt_key)
            if cnt == 1:
                await redis.expire(cnt_key, _CONSECUTIVE_4XX_WINDOW)
            if cnt >= _CONSECUTIVE_4XX_THRESHOLD:
                # 清掉计数，避免下一次又触发自检
                await redis.delete(cnt_key)
                if await _confirm_blocked_via_probe(node, redis, failed_url=url):
                    await node.trip_breaker(redis, reason=f"probe_failed after {cnt} consecutive 403s")
                    raise CrawlerBlockedError(f"探针失败：节点 {node.node_id} 似乎被全站拦截")
                # 探针通过：之前的 403 都是目标级问题，没事
                log.info(
                    "crawler.probe_passed",
                    node_id=node.node_id,
                    consecutive_403=cnt,
                )
        raise CrawlerNotFound(f"内容不可访问: status={status} url={url}")

    # 其他 4xx/5xx 当作可重试错误
    if status >= 400:
        raise CrawlerError(f"HTTP {status}: {url} body(前200)={body[:200]}")

    # 200 时清掉连续 4xx 计数（一切正常）
    if status == 200:
        try:
            await redis.delete(_consecutive_4xx_key(node.node_id))
        except Exception:
            pass

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
    node: CrawlerNode | None = None,
    redis: Redis,
    params: dict[str, Any] | None = None,
    accept_json: bool = False,
    parse: Literal["html", "json", "auto"] = "auto",
) -> FetchResult:
    """游客身份请求。**绝不**带 Cookie。

    path_or_url：相对路径（如 `/article/xxx`）自动拼 CRAWLER_BASE_URL；
                 完整 URL 直接用。

    node 不传时按目标域名自动选：走 luogu.com.cn 主站 → cn 限速节点（0.1 req/s）；
    走海外镜像 luogu.com → 默认 anon 节点。
    """
    from app.crawler.nodes.local import get_default_node

    url = _resolve_url(path_or_url)
    if node is None:
        cn = "luogu.com.cn" in url
        node = get_default_node(NodeKind.ANON, cn=cn)
    assert node.kind == NodeKind.ANON, "fetch_anon 只能用 ANON 节点"
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
    node: CrawlerNode | None = None,
    redis: Redis,
    cookies: dict[str, str],
    account_id: int,
    params: dict[str, Any] | None = None,
    accept_json: bool = True,   # 鉴权接口通常要 JSON
    parse: Literal["html", "json", "auto"] = "auto",
) -> FetchResult:
    """认证请求（带 Cookie）。仅用于犇犇爬取。

    cookies: 必传 `_uid` + `__client_id`（可选 `C3VK`）

    node 不传时按目标域名自动选 cn / 海外。
    """
    from app.crawler.nodes.local import get_default_node

    if "_uid" not in cookies or "__client_id" not in cookies:
        raise ValueError("cookies 必须含 _uid 和 __client_id")
    url = _resolve_url(path_or_url)
    if node is None:
        cn = "luogu.com.cn" in url
        node = get_default_node(NodeKind.AUTHED, cn=cn)
    assert node.kind == NodeKind.AUTHED, "fetch_authed 只能用 AUTHED 节点"
    return await _do_request(
        "GET",
        url,
        node=node,
        redis=redis,
        cookies=cookies,
        params=params,
        accept_json=accept_json,
        parse=parse,
        account_id=account_id,
    )


def _resolve_url(path_or_url: str) -> str:
    """拼完整 URL。若已是 http:// / https:// 则直接返回。

    按内容类型分派域名：
    - 仅 /judgement 和 /problem 强制走主站 www.luogu.com.cn
    - 其他路径（含 /api/feed 犇犇接口）走 CRAWLER_BASE_URL（默认海外镜像）
    """
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    path = path_or_url if path_or_url.startswith("/") else f"/{path_or_url}"
    cn_prefixes = ("/judgement", "/problem")
    if any(path.startswith(p) for p in cn_prefixes):
        base = "https://www.luogu.com.cn"
    else:
        base = settings.CRAWLER_BASE_URL.rstrip("/")
    return f"{base}{path}"
