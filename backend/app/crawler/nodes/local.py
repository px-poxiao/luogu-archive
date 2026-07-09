"""Default local crawler nodes.

Rate limits are per worker and per target domain:
- luogu.com.cn: 1 request / 10 seconds.
- luogu.com: 1 request / 1 second.

Within the same worker, anonymous and authenticated nodes share the same domain
bucket.  Different workers must use different NODE_ID values, so their buckets
remain independent.
"""
from __future__ import annotations

from app.core.config import settings
from app.crawler.nodes.base import CrawlerNode, NodeKind


class LocalNode(CrawlerNode):
    """Local crawler node."""


_CN_RATE_PER_SEC = 0.1
_COM_RATE_PER_SEC = 1.0


def _worker_scope_id() -> str:
    return settings.NODE_ID.strip() or "local"


def _resolve_node_id(kind: NodeKind, *, cn: bool) -> str:
    base = settings.NODE_ID.strip()
    suffix_kind = "anon" if kind == NodeKind.ANON else "authed"
    suffix_domain = "-cn" if cn else ""
    if not base:
        return f"local-{suffix_kind}{suffix_domain}-01"
    return f"{base}-{suffix_kind}{suffix_domain}"


def _domain_rate_limit_scope(*, cn: bool) -> str:
    domain = "luogu.com.cn" if cn else "luogu.com"
    return f"{_worker_scope_id()}:domain:{domain}"


_nodes: dict[tuple[NodeKind, bool], CrawlerNode] = {}


def get_default_node(kind: NodeKind = NodeKind.ANON, *, cn: bool = False) -> CrawlerNode:
    """Return the local node for this worker, identity kind and domain."""
    key = (kind, cn)
    cached = _nodes.get(key)
    if cached is not None:
        return cached

    node = LocalNode(
        node_id=_resolve_node_id(kind, cn=cn),
        kind=kind,
        rate_per_sec=_CN_RATE_PER_SEC if cn else _COM_RATE_PER_SEC,
        burst_capacity=1,
        rate_limit_scope=_domain_rate_limit_scope(cn=cn),
    )
    _nodes[key] = node
    return node