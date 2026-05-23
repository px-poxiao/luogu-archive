"""默认本机节点。

单机部署：NODE_ID 留空。
多机部署：每台 worker 在 .env 设 `NODE_ID=worker-X`，节点 ID 自动派生：
    海外镜像（luogu.com）  → anon / authed
    主站（luogu.com.cn）   → anon-cn / authed-cn

主站的速率比海外镜像严得多（洛谷官方限制 0.1 req/s = 10s/req），
所以主站走独立节点，独立 token bucket、独立熔断状态，
不会因为海外镜像高频访问把主站计数器搞乱。
"""
from __future__ import annotations

from app.core.config import settings
from app.crawler.nodes.base import CrawlerNode, NodeKind


class LocalNode(CrawlerNode):
    """本机节点。"""


# .com.cn 主站速率上限（与海外镜像独立）
_CN_RATE_PER_SEC = 0.1


def _resolve_node_id(kind: NodeKind, *, cn: bool) -> str:
    base = settings.NODE_ID.strip()
    suffix_kind = "anon" if kind == NodeKind.ANON else "authed"
    suffix_domain = "-cn" if cn else ""
    if not base:
        return f"local-{suffix_kind}{suffix_domain}-01"
    return f"{base}-{suffix_kind}{suffix_domain}"


# 进程级单例缓存：4 个节点（anon / authed × 海外 / 主站）
_nodes: dict[tuple[NodeKind, bool], CrawlerNode] = {}


def get_default_node(kind: NodeKind = NodeKind.ANON, *, cn: bool = False) -> CrawlerNode:
    """返回当前进程的对应节点。

    cn=True → 走 luogu.com.cn 主站，速率 0.1 req/s（10s/req）
    cn=False → 走海外镜像 luogu.com，速率取 settings.CRAWLER_*_RATE_PER_SEC
    """
    key = (kind, cn)
    cached = _nodes.get(key)
    if cached is not None:
        return cached

    if cn:
        rate = _CN_RATE_PER_SEC
    elif kind == NodeKind.ANON:
        rate = settings.CRAWLER_ANON_RATE_PER_SEC
    else:
        rate = settings.CRAWLER_AUTH_RATE_PER_SEC

    node = LocalNode(
        node_id=_resolve_node_id(kind, cn=cn),
        kind=kind,
        rate_per_sec=rate,
        burst_capacity=1,
    )
    _nodes[key] = node
    return node
