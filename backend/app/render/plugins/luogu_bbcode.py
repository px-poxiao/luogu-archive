"""洛谷老式 BBCode 兼容插件。

老版本洛谷 markdown 里混有这些：
- [user]12345[/user]           → 用户链接（等价于 @[name](/user/12345)，但这里只有 uid）
- [color=red]text[/color]      → 彩色文字（有限白名单）
- [template]1234[/template]    → 题目模板（不常用，保留占位）

都不重要但不能挂。用简单的 preprocess 把它们替换成安全的 HTML 片段，
再走 markdown 正常流程。
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from markdown_it import MarkdownIt

# 受信颜色白名单，防 CSS 注入
_ALLOWED_COLORS = {
    "red", "green", "blue", "orange", "purple", "cyan",
    "gray", "black", "white", "yellow", "pink", "brown",
}

_USER_TAG = re.compile(r"\[user\](\d+)\[/user\]", re.IGNORECASE)
_COLOR_TAG = re.compile(r"\[color=([#a-zA-Z0-9]+)\](.*?)\[/color\]", re.IGNORECASE | re.DOTALL)
_TEMPLATE_TAG = re.compile(r"\[template\](\d+)\[/template\]", re.IGNORECASE)


def _preprocess(src: str) -> str:
    # [user]123[/user] → @[UID 123](/user/123) 再走 user_mention_plugin
    src = _USER_TAG.sub(lambda m: f"@[UID {m.group(1)}](/user/{m.group(1)})", src)

    def _color_repl(m):
        color = m.group(1).lower().lstrip("#")
        text = m.group(2)
        if color in _ALLOWED_COLORS:
            safe = color
        elif re.fullmatch(r"[0-9a-f]{3,6}", color):
            safe = f"#{color}"
        else:
            # 不合规颜色直接去掉色块，保留文本
            return text
        return f'<span style="color:{safe}">{text}</span>'

    src = _COLOR_TAG.sub(_color_repl, src)

    # [template]X[/template] → 先渲染成一个占位链接（后续可替换成题目卡片）
    src = _TEMPLATE_TAG.sub(
        lambda m: f'[题目模板 #{m.group(1)}](/problem/{m.group(1)})',
        src,
    )
    return src


def luogu_bbcode_plugin(md: MarkdownIt) -> None:
    """注册 core ruler，在其他规则之前先把 BBCode 转普通 markdown。"""

    def _normalize_bbcode(state) -> None:  # noqa: ANN001 — markdown-it 内部类型
        state.src = _preprocess(state.src)

    md.core.ruler.before("normalize", "luogu_bbcode", _normalize_bbcode)
