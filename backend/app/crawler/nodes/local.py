"""默认本机节点。

单机部署：NODE_ID 留空，使用 "local-anon-01" / "local-authed-01"。
多机部署：每台 worker 在 .env 设 `NODE_ID=worker-X`，
        匿名节点 ID 自动派生为 "{NODE_ID}-anon"，认证节点为 "{NODE_ID}-authed"。
        这样多个 worker 在 redis 里限流 / 熔断各自独立。
"""
from __future__ import annotations

from app.core.config import settings
from app.crawler.nodes.base import CrawlerNode, NodeKind


class LocalNode(CrawlerNode):
    """本机节点。与 base.CrawlerNode 同，只是取了个别名方便代码意图。"""


def _resolve_node_id(kind: NodeKind) -> str:
    base = settings.NODE_ID.strip()
    if not base:
        return "local-anon-01" if kind == NodeKind.ANON else "local-authed-01"
    suffix = "anon" if kind == NodeKind.ANON else "authed"
    return f"{base}-{suffix}"


# 进程级单例缓存
_anon_node: CrawlerNode | None = None
_authed_node: CrawlerNode | None = None


def get_default_node(kind: NodeKind = NodeKind.ANON) -> CrawlerNode:
    """返回当前进程的匿名 / 认证节点。

    每个 worker 进程对应一对节点（anon + authed）。多 worker 部署时
    NODE_ID 在 .env 里区分，每台 worker 的限流 / 熔断各自独立。
    """
    global _anon_node, _authed_node
    if kind == NodeKind.ANON:
        if _anon_node is None:
            _anon_node = LocalNode(
                node_id=_resolve_node_id(NodeKind.ANON),
                kind=NodeKind.ANON,
                rate_per_sec=settings.CRAWLER_ANON_RATE_PER_SEC,
                burst_capacity=1,
            )
        return _anon_node
    else:
        if _authed_node is None:
            _authed_node = LocalNode(
                node_id=_resolve_node_id(NodeKind.AUTHED),
                kind=NodeKind.AUTHED,
                rate_per_sec=settings.CRAWLER_AUTH_RATE_PER_SEC,
                burst_capacity=1,
            )
        return _authed_node
