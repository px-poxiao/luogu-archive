"""HTML 净化 —— 防 XSS。

用途：最后一层保险。洛谷原文可能嵌 `<script>`、`<iframe>` 等。我们 markdown-it
已经 html=False 禁了直接 HTML，但用户可能嵌入"html-like"字符串，保险起见再过一遍。

实现极简：白名单标签 + 白名单属性。不用 bleach（多一个依赖），
用正则就够。对极端输入不完美，但结合前端 Vue 的文本渲染足以防 XSS。

注意：**不对 a/img 的 href/src 值做 javascript: 协议过滤以外的限制**，
引用 cdn.luogu.com.cn 的图片是正常需求。
"""
from __future__ import annotations

import re

_ALLOWED_TAGS = {
    "a", "p", "br", "strong", "em", "u", "s", "del", "ins", "code", "pre",
    "blockquote", "ol", "ul", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "img", "span", "div", "table", "thead", "tbody", "tr", "td", "th",
    "sub", "sup", "kbd", "mark", "details", "summary", "figure", "figcaption",
    # KaTeX 可能在前端生成的额外标签
    "math", "annotation", "semantics", "mrow", "mi", "mo", "mn", "msub", "msup",
    "mfrac", "msqrt", "mroot", "munder", "mover", "munderover",
}
# class / data-* 属性白名单放行
_ALLOWED_ATTR_PREFIXES = ("data-",)
_ALLOWED_ATTRS = {
    "href", "title", "alt", "src", "class", "id", "target", "rel",
    "colspan", "rowspan", "align", "width", "height", "style",
}

# 危险协议
_DANGEROUS_PROTO = re.compile(r"^\s*(javascript|data|vbscript):", re.IGNORECASE)
# 标签匹配（贪婪但不跨越结尾）
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)([^>]*)>")
_ATTR_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_:-]*)(?:\s*=\s*"([^"]*)"|\s*=\s*\'([^\']*)\'|\s*=\s*([^\s>]*))?')


def _clean_attrs(attrs: str) -> str:
    out: list[str] = []
    for m in _ATTR_RE.finditer(attrs):
        name = m.group(1).lower()
        val = m.group(2) or m.group(3) or m.group(4) or ""
        if not (name in _ALLOWED_ATTRS or any(name.startswith(p) for p in _ALLOWED_ATTR_PREFIXES)):
            continue
        if name in ("href", "src") and _DANGEROUS_PROTO.match(val):
            continue
        # style 只留简单颜色 / 字体尺寸（防 `expression()`、`url(javascript:...)`）
        if name == "style":
            if re.search(r"expression\s*\(|javascript:", val, re.IGNORECASE):
                continue
            # 保留但不做更细粒度验证
        if val == "":
            out.append(name)
        else:
            safe_val = val.replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
            out.append(f'{name}="{safe_val}"')
    return (" " + " ".join(out)) if out else ""


def sanitize_html(html: str) -> str:
    """白名单过滤。"""

    def _repl(m: re.Match[str]) -> str:
        closing = m.group(1) == "/"
        tag = m.group(2).lower()
        attrs = m.group(3) or ""
        if tag not in _ALLOWED_TAGS:
            # 删掉整个标签（只剩文本内容）
            return ""
        if closing:
            return f"</{tag}>"
        clean_attrs = _clean_attrs(attrs)
        # 自闭合
        self_close = attrs.rstrip().endswith("/")
        return f"<{tag}{clean_attrs}{' /' if self_close else ''}>"

    return _TAG_RE.sub(_repl, html)
