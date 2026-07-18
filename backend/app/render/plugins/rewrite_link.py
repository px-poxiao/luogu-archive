"""链接改写：把洛谷原站链接改写为本站路径。

- https://www.luogu.com.cn/article/xxx → /article/xxx
- https://luogu.com/user/12345         → /user/12345
- https://www.luogu.com/paste/abc      → /paste/abc

保留外链（cdn.luogu.com.cn 等图床链接不改）。
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from markdown_it import MarkdownIt

# 洛谷站域名（都改写）
_LUOGU_HOSTS = {
    "www.luogu.com.cn",
    "luogu.com.cn",
    "www.luogu.com",
    "luogu.com",
    "www.luogu.org",
    "luogu.org",
}

# 本站支持的路径前缀，其他路径改写后也能正常渲染（即使 404 也只是本站 404）
_ALLOWED_PATH_PREFIXES = (
    "/article/",
    "/paste/",
    "/user/",
    "/judgement",
    "/feed",
)


def _rewrite_href(href: str) -> str:
    if not href:
        return href
    try:
        u = urlparse(href)
    except Exception:
        return href
    if u.scheme not in ("http", "https"):
        return href
    if u.netloc.lower() not in _LUOGU_HOSTS:
        return href
    # 保留路径、查询、锚点
    path = u.path or "/"
    qs = f"?{u.query}" if u.query else ""
    frag = f"#{u.fragment}" if u.fragment else ""
    # 只改写本站能识别的路径前缀；其他保留原站链接（避免本站 404 误导）
    if any(path.startswith(p) for p in _ALLOWED_PATH_PREFIXES) or path == "/":
        return f"{path}{qs}{frag}"
    return href


def rewrite_link_plugin(md: MarkdownIt) -> None:
    def _replace(tokens, idx, _opts, _env) -> str:
        token = tokens[idx]
        href = token.attrGet("href") or ""
        new_href = _rewrite_href(href)
        if new_href != href:
            token.attrSet("href", new_href)
        # 标记外链
        if new_href.startswith("http"):
            token.attrJoin("rel", "noopener noreferrer")
            token.attrJoin("target", "_blank")
        # 沿用默认渲染
        return md.renderer.renderToken(tokens, idx, _opts)

    md.add_render_rule("link_open", _replace)
