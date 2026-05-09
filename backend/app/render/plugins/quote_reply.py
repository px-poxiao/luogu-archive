"""引用回复插件：`|| @[name](/user/uid) : 内容` → 引用卡片。

洛谷犇犇里的引用回复语法。示例：
    || @[FFTotoro](/user/556366) : 今天似乎有不少人过生日。
    祝 @[Larunatrecy](/user/128215) 生日快乐。

行首出现 `|| ` 开头（必须包含 @ 提及 + 冒号），后续直到空行都视作引用块。
渲染为 blockquote，被引用者用 user_mention 渲染。

实现：Block Rule，扫描 `|| ` 开头的行，捕获整段，作为一个特殊 block token，
内部的剩余文本再走 inline 解析。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from markdown_it import MarkdownIt
    from markdown_it.rules_block import StateBlock


def _quote_reply_rule(state: StateBlock, startLine: int, endLine: int, silent: bool) -> bool:
    pos = state.bMarks[startLine] + state.tShift[startLine]
    max_pos = state.eMarks[startLine]
    if pos + 2 > max_pos:
        return False
    src = state.src
    # 必须以 "|| " 开头
    if src[pos] != "|" or src[pos + 1] != "|" or src[pos + 2] != " ":
        return False

    # 向后扫描直到空行
    nextLine = startLine + 1
    while nextLine < endLine:
        line_start = state.bMarks[nextLine] + state.tShift[nextLine]
        line_end = state.eMarks[nextLine]
        if line_start >= line_end:
            break
        nextLine += 1

    if silent:
        return True

    # 提取内容（去掉行首 "|| "）
    inner_lines = []
    for i in range(startLine, nextLine):
        s = state.bMarks[i] + state.tShift[i]
        e = state.eMarks[i]
        line = src[s:e]
        if i == startLine and line.startswith("|| "):
            line = line[3:]
        inner_lines.append(line)
    content = "\n".join(inner_lines)

    # 生成 token
    token_open = state.push("luogu_quote_reply_open", "blockquote", 1)
    token_open.attrSet("class", "lg-quote-reply")
    token_open.markup = "||"
    token_open.block = True
    token_open.map = [startLine, nextLine]

    # 把内部内容塞 inline token 让 markdown-it 走标准行内解析
    token_inline = state.push("inline", "", 0)
    token_inline.content = content.strip()
    token_inline.children = []
    token_inline.map = [startLine, nextLine]

    state.push("luogu_quote_reply_close", "blockquote", -1)

    state.line = nextLine
    return True


def quote_reply_plugin(md: MarkdownIt) -> None:
    md.block.ruler.before("paragraph", "luogu_quote_reply", _quote_reply_rule)
