"""用户提及插件：`@[name](/user/uid)` → 脱敏 / 链接 / 颜色。

这是洛谷犇犇、文章里大量出现的语法。一条犇犇里可能出现 5~10 次。

实现思路：行内规则（inline rule），扫描到 `@[` 开头尝试匹配 `@[NAME](/user/UID)`。
匹配成功生成一个 token，在 renderer 阶段根据 RenderContext 决定最终 HTML。
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from markdown_it import MarkdownIt
    from markdown_it.rules_inline import StateInline

# 最大名字长度，防病态输入
_NAME_MAX = 64
_MENTION_PAT = re.compile(rf"@\[([^\]]{{1,{_NAME_MAX}}})\]\(/user/(\d+)\)")


def _user_mention_rule(state: StateInline, silent: bool) -> bool:
    """InlineRule：识别 @[name](/user/uid)。"""
    if state.src[state.pos] != "@":
        return False
    m = _MENTION_PAT.match(state.src, state.pos)
    if not m:
        return False
    name = m.group(1)
    uid = int(m.group(2))

    if not silent:
        token = state.push("luogu_user_mention", "", 0)
        token.meta = {"uid": uid, "name": name}
        token.markup = m.group(0)
        token.content = name

    state.pos = m.end()
    return True


def _render_user_mention(tokens, idx, _opts, env) -> str:
    ctx = env.get("luogu_ctx")
    token = tokens[idx]
    uid = token.meta["uid"]
    name = token.meta["name"]

    # 统一走 RenderContext 判断脱敏
    hidden = ctx.should_mask(uid, name) if ctx else False
    display = f"UID {uid}" if hidden else name

    # 全部改写到本站路径 /user/<uid>
    site_origin = (ctx.site_origin if ctx else "").rstrip("/")
    href = f"{site_origin}/user/{uid}"

    return (
        f'<a class="lg-user-mention" data-uid="{uid}" '
        f'href="{href}"'
        f'{" data-hidden=\"1\"" if hidden else ""}>'
        f"@{_escape(display)}</a>"
    )


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def user_mention_plugin(md: MarkdownIt) -> None:
    """注册到 MarkdownIt 实例。"""
    md.inline.ruler.before("link", "luogu_user_mention", _user_mention_rule)
    md.add_render_rule("luogu_user_mention", _render_user_mention)
