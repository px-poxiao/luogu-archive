"""CrawlerNode 节点抽象包。

- base.py  基础类（节点身份、限流、熔断）
- local.py 本机默认节点
"""
from app.crawler.nodes.base import CrawlerNode, NodeKind
from app.crawler.nodes.local import LocalNode, get_default_node

__all__ = ["CrawlerNode", "LocalNode", "NodeKind", "get_default_node"]
