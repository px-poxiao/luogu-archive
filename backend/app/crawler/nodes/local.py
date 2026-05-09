"""默认本机节点。单机部署时使用。

未来多机部署时，每个机器启动时根据自己的环境变量构造独立的 LocalNode 实例。
"""
from __future__ import annotations

from app.core.config import settings
from app.crawler.nodes.base import CrawlerNode, NodeKind


class LocalNode(CrawlerNode):
    """本机节点。与 base.CrawlerNode 同，只是取了个别名方便代码意图。"""


# 进程级单例缓存
_anon_node: CrawlerNode | None = None
_authed_node: CrawlerNode | None = None


def get_default_node(kind: NodeKind = NodeKind.ANON) -> CrawlerNode:
    """返回默认匿名 / 认证节点。

    单机阶段只有一个匿名节点 + 一个认证节点。
    未来扩展到多机时，由任务路由根据 queue name 指向不同节点实例，而非这里。
    """
    global _anon_node, _authed_node
    if kind == NodeKind.ANON:
        if _anon_node is None:
            _anon_node = LocalNode(
                node_id="local-anon-01",
                kind=NodeKind.ANON,
                rate_per_sec=settings.CRAWLER_ANON_RATE_PER_SEC,
                burst_capacity=1,
            )
        return _anon_node
    else:
        if _authed_node is None:
            _authed_node = LocalNode(
                node_id="local-authed-01",
                kind=NodeKind.AUTHED,
                rate_per_sec=settings.CRAWLER_AUTH_RATE_PER_SEC,
                burst_capacity=1,
            )
        return _authed_node
