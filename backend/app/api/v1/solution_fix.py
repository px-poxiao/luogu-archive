"""题解格式修正 API。"""
from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth.deps import get_current_site_user
from app.core.config import settings
from app.core.exceptions import RateLimitError, ValidationError
from app.core.redis_client import get_redis
from app.models.site_user import SiteUser

router = APIRouter(prefix="/solution-fix", tags=["solution-fix"])

Mode = Literal["local", "ai"]


class SolutionFixReq(BaseModel):
    content: str = Field(..., min_length=1)


class SolutionFixResp(BaseModel):
    mode: Mode
    content: str
    changed: bool
    notes: list[str] = []


@dataclass
class _FixState:
    changed: bool = False
    notes: list[str] | None = None

    def add(self, note: str) -> None:
        if self.notes is None:
            self.notes = []
        if note not in self.notes:
            self.notes.append(note)
        self.changed = True


_FENCE_OPEN_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})([^\s#].*)$")
_CPP_PREPROCESSOR_RE = re.compile(
    r"^#\s*(include|define|pragma|if|ifdef|ifndef|endif|else|elif|undef)\b"
)
_UNCLOSED_COMPACT_MATH_RE = re.compile(
    r"(?<!\\)\$([A-Za-z0-9_{}\\^+\-*/=<>|.,]+)(?=([\s\u3400-\u9fff，。！？；：、）】》」』]|$))"
)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_LATIN_DIGIT_RE = re.compile(r"[A-Za-z0-9]")
_CJK_PUNCT = "，。！？；：、）】》」』"
_SENTENCE_END_RE = re.compile(r"[。！？；：.!?;:…）」』）】》]$")
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-+*]\s+|\d+[.)]\s+)")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


@dataclass
class _InlineToken:
    kind: str
    value: str


@dataclass
class _MarkdownBlock:
    kind: str
    lines: list[str]


_BLOCKS_THAT_MAKE_PREVIOUS_A_LEAD = {
    "math_block",
    "fence",
    "table",
    "container",
    "quote_reply",
    "list",
}


_PROTECTED_SINGLE_LINE_BLOCKS = {
    "container",
    "quote_reply",
    "luogu_bbcode",
    "cpp_preprocessor",
}


def _line_kind(line: str) -> str:
    stripped = line.lstrip()
    if not stripped:
        return "blank"
    if stripped.startswith(("```", "~~~")):
        return "code_fence"
    if stripped.startswith("$$"):
        return "math_block"
    if stripped.startswith(":::"):
        return "container"
    if stripped.startswith("|| "):
        return "quote_reply"
    if stripped.startswith("|") or _TABLE_SEPARATOR_RE.match(stripped):
        return "table"
    if _LIST_MARKER_RE.match(stripped):
        return "list"
    if stripped.startswith(">"):
        return "blockquote"
    if stripped.startswith(("[user]", "[color=", "[template]")):
        return "luogu_bbcode"
    if _CPP_PREPROCESSOR_RE.match(stripped) is not None:
        return "cpp_preprocessor"
    if re.match(r"^#{1,6}(?:\s|$|[^#])", stripped):
        return "heading"
    if _is_media_only_line(stripped):
        return "media"
    return "paragraph"


def _parse_markdown_blocks(lines: list[str], state: _FixState) -> list[_MarkdownBlock]:
    blocks: list[_MarkdownBlock] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        kind = _line_kind(line)

        if kind == "blank":
            blocks.append(_MarkdownBlock("blank", [""]))
            i += 1
            continue

        fence = _FENCE_OPEN_RE.match(line)
        if fence:
            marker = fence.group(2)
            fixed_open = f"{fence.group(1)}{marker}{fence.group(3).strip()}"
            if fixed_open != line:
                state.add("已整理代码块语言标记后的多余空格")
            block_lines = [fixed_open]
            i += 1
            closed = False
            while i < len(lines):
                block_lines.append(lines[i])
                close = _FENCE_OPEN_RE.match(lines[i])
                if close and close.group(2).startswith(marker):
                    closed = True
                    i += 1
                    break
                i += 1
            if not closed:
                block_lines.append(marker)
                state.add("检测到未闭合代码块，已补齐闭合标记")
            blocks.append(_MarkdownBlock("fence", block_lines))
            continue

        if kind == "math_block":
            block_lines = [line]
            i += 1
            while i < len(lines):
                block_lines.append(lines[i])
                if lines[i].lstrip().startswith("$$"):
                    i += 1
                    break
                i += 1
            blocks.append(_MarkdownBlock("math_block", block_lines))
            continue

        if kind == "table":
            block_lines = [line]
            i += 1
            while i < len(lines) and _line_kind(lines[i]) == "table":
                block_lines.append(lines[i])
                i += 1
            blocks.append(_MarkdownBlock("table", block_lines))
            continue

        if kind in _PROTECTED_SINGLE_LINE_BLOCKS or kind == "media":
            blocks.append(_MarkdownBlock(kind, [line]))
            i += 1
            continue

        if kind in {"heading", "list", "blockquote"}:
            blocks.append(_MarkdownBlock(kind, [line]))
            i += 1
            continue

        paragraph_lines = [line]
        i += 1
        while i < len(lines) and _line_kind(lines[i]) == "paragraph":
            paragraph_lines.append(lines[i])
            i += 1
        blocks.append(_MarkdownBlock("paragraph", paragraph_lines))

    return blocks


def _normalize_local(content: str) -> SolutionFixResp:
    """按 Markdown 块和行内 token 做保守修正，避免误伤洛谷扩展语法。"""
    state = _FixState(notes=[])
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    if text != content:
        state.add("已统一换行为 LF")

    blocks = _parse_markdown_blocks(text.split("\n"), state)
    out: list[str] = []
    blank_run = 0

    for index, block in enumerate(blocks):
        if block.kind == "blank":
            blank_run += 1
            if blank_run <= 2:
                out.append("")
            elif blank_run == 3:
                state.add("已压缩连续空行为最多两行")
            continue

        blank_run = 0
        next_block = _next_content_block(blocks, index + 1)
        out.extend(_format_block(block, next_block, state))

    fixed_text = "\n".join(out).strip() + "\n"
    if fixed_text != content:
        state.changed = True

    return SolutionFixResp(
        mode="local",
        content=fixed_text,
        changed=state.changed,
        notes=state.notes or [],
    )


def _next_content_block(blocks: list[_MarkdownBlock], start: int) -> _MarkdownBlock | None:
    for block in blocks[start:]:
        if block.kind != "blank":
            return block
    return None


def _format_block(
    block: _MarkdownBlock,
    next_block: _MarkdownBlock | None,
    state: _FixState,
) -> list[str]:
    if block.kind in {
        "fence",
        "math_block",
        "table",
        "container",
        "quote_reply",
        "luogu_bbcode",
        "cpp_preprocessor",
        "media",
    }:
        return block.lines

    if block.kind == "heading":
        return [_format_heading(block.lines[0], state)]

    if block.kind == "list":
        return [_format_list_item(block.lines[0], state)]

    if block.kind == "blockquote":
        return [_format_blockquote(block.lines[0], state)]

    lines = [_format_inline_text(line, state) for line in block.lines]
    if lines and not _should_skip_sentence_period(lines[-1], next_block):
        lines[-1] = _append_sentence_period(lines[-1], state)
    return lines


def _format_heading(line: str, state: _FixState) -> str:
    fixed = _HEADING_RE.sub(r"\1 \2", line)
    if fixed != line:
        state.add("已补齐标题标记后的空格")
    match = re.match(r"^(\s*#{1,6}\s+)(.*)$", fixed)
    if not match:
        return fixed
    return f"{match.group(1)}{_format_inline_text(match.group(2), state)}"


def _format_list_item(line: str, state: _FixState) -> str:
    match = re.match(r"^(\s*(?:[-+*]|\d+[.)])\s+)(.*)$", line)
    if not match:
        return _format_inline_text(line, state)
    return f"{match.group(1)}{_format_inline_text(match.group(2), state)}"


def _format_blockquote(line: str, state: _FixState) -> str:
    match = re.match(r"^(\s*>\s?)(.*)$", line)
    if not match:
        return _format_inline_text(line, state)
    return f"{match.group(1)}{_format_inline_text(match.group(2), state)}"


def _should_skip_sentence_period(line: str, next_block: _MarkdownBlock | None) -> bool:
    stripped = line.rstrip()
    if not stripped:
        return True
    if _is_media_only_line(stripped):
        return True
    if _SENTENCE_END_RE.search(stripped):
        return True
    if next_block is not None and next_block.kind in _BLOCKS_THAT_MAKE_PREVIOUS_A_LEAD:
        return True
    return False


def _append_sentence_period(line: str, state: _FixState) -> str:
    stripped = line.rstrip()
    if re.search(r"[\u3400-\u9fffA-Za-z0-9）\])`$]$", stripped):
        state.add("已为普通段落补齐中文句号")
        return f"{stripped}。"
    return line


def _tokenize_inline(line: str) -> list[_InlineToken]:
    tokens: list[_InlineToken] = []
    pos = 0
    i = 0
    while i < len(line):
        token = _read_inline_token(line, i)
        if token is None:
            i += 1
            continue

        kind, end = token
        if end <= i:
            i += 1
            continue
        if i > pos:
            tokens.append(_InlineToken("text", line[pos:i]))
        tokens.append(_InlineToken(kind, line[i:end]))
        i = end
        pos = end

    if pos < len(line):
        tokens.append(_InlineToken("text", line[pos:]))
    return tokens


def _read_inline_token(line: str, start: int) -> tuple[str, int] | None:
    if line[start] == "`":
        return _read_backtick_code(line, start)
    if line[start] == "$" and not _is_escaped(line, start):
        return _read_inline_math(line, start)
    if line.startswith("![", start):
        return _read_markdown_link(line, start, "image")
    if line[start] == "[":
        return _read_markdown_link(line, start, "link")
    if line.startswith(("http://", "https://"), start):
        return _read_bare_url(line, start)
    if line.startswith("@[", start):
        linked = _read_markdown_link(line, start + 1, "mention")
        if linked is not None:
            _, end = linked
            return "mention", end
    if line[start] == "@":
        return _read_plain_mention(line, start)
    return None


def _read_backtick_code(line: str, start: int) -> tuple[str, int] | None:
    marker_len = 1
    while start + marker_len < len(line) and line[start + marker_len] == "`":
        marker_len += 1
    marker = "`" * marker_len
    end = line.find(marker, start + marker_len)
    if end == -1:
        return None
    return "code", end + marker_len


def _read_inline_math(line: str, start: int) -> tuple[str, int] | None:
    marker = "$$" if line.startswith("$$", start) else "$"
    pos = start + len(marker)
    while pos < len(line):
        end = line.find(marker, pos)
        if end == -1:
            return None
        if not _is_escaped(line, end):
            if marker == "$" and line.startswith("$$", end):
                pos = end + 2
                continue
            return "math", end + len(marker)
        pos = end + 1
    return None


def _read_markdown_link(line: str, start: int, kind: str) -> tuple[str, int] | None:
    bracket_start = start + 1 if kind == "image" else start
    if bracket_start >= len(line) or line[bracket_start] != "[":
        return None
    bracket_end = _find_balanced(line, bracket_start, "[", "]")
    if bracket_end is None:
        return None
    paren_start = bracket_end + 1
    if paren_start >= len(line) or line[paren_start] != "(":
        return None
    paren_end = _find_balanced(line, paren_start, "(", ")")
    if paren_end is None:
        return None
    return kind, paren_end + 1


def _read_bare_url(line: str, start: int) -> tuple[str, int] | None:
    i = start
    paren_depth = 0
    while i < len(line):
        ch = line[i]
        if ch.isspace() or ch in "<>，。！？；：、":
            break
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            if paren_depth == 0:
                break
            paren_depth -= 1
        i += 1

    while i > start and line[i - 1] in ".,!?;:":
        i -= 1
    if i == start:
        return None
    return "url", i


def _read_plain_mention(line: str, start: int) -> tuple[str, int] | None:
    i = start + 1
    while i < len(line) and not line[i].isspace() and line[i] not in _CJK_PUNCT:
        i += 1
    if i == start + 1:
        return None
    return "mention", i


def _find_balanced(line: str, start: int, open_ch: str, close_ch: str) -> int | None:
    depth = 0
    i = start
    while i < len(line):
        ch = line[i]
        if _is_escaped(line, i):
            i += 1
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _is_escaped(line: str, index: int) -> bool:
    slash_count = 0
    i = index - 1
    while i >= 0 and line[i] == "\\":
        slash_count += 1
        i -= 1
    return slash_count % 2 == 1


def _is_media_only_line(line: str) -> bool:
    tokens = _tokenize_inline(line.strip())
    meaningful = [token for token in tokens if token.value.strip()]
    return len(meaningful) == 1 and meaningful[0].kind in {"image", "link", "url"}


def _format_inline_text(line: str, state: _FixState) -> str:
    fixed_line = _fix_unclosed_inline_latex(line, state)
    tokens = _tokenize_inline(fixed_line)
    if not tokens:
        return fixed_line

    formatted: list[_InlineToken] = []
    for token in tokens:
        if token.kind == "text":
            formatted.append(_InlineToken(token.kind, _fix_plain_text_spacing(token.value)))
        else:
            formatted.append(token)

    _join_inline_tokens(formatted)
    result = "".join(token.value for token in formatted)
    result = re.sub(r"\s+([，。！？；：、])", r"\1", result)
    result = re.sub(r"([，。！？；：、])\s+", r"\1", result)
    if result != line:
        state.add("已按中文与英文、数字或公式之间的空格规范调整")
    return result


def _join_inline_tokens(tokens: list[_InlineToken]) -> None:
    for i in range(len(tokens) - 1):
        left = tokens[i]
        right = tokens[i + 1]
        if not left.value or not right.value:
            continue
        left_tail = left.value[-1]
        right_head = right.value[0]
        if left_tail.isspace() or right_head.isspace():
            continue
        if left_tail in _CJK_PUNCT or right_head in _CJK_PUNCT:
            continue
        if left.kind == "text" and right.kind == "text":
            if _need_cjk_space(left_tail, right_head):
                left.value += " "
            continue
        if left.kind == "text" and _CJK_RE.search(left_tail):
            left.value += " "
            continue
        if right.kind == "text" and _CJK_RE.search(right_head):
            left.value += " "


def _need_cjk_space(left: str, right: str) -> bool:
    return (
        (_CJK_RE.search(left) is not None and _LATIN_DIGIT_RE.search(right) is not None)
        or (_LATIN_DIGIT_RE.search(left) is not None and _CJK_RE.search(right) is not None)
    )


def _fix_plain_text_spacing(text: str) -> str:
    text = re.sub(r"([\u3400-\u9fff])([A-Za-z0-9])", r"\1 \2", text)
    text = re.sub(r"([A-Za-z0-9])([\u3400-\u9fff])", r"\1 \2", text)
    text = re.sub(r"\s+([，。！？；：、])", r"\1", text)
    text = re.sub(r"([，。！？；：、])\s+", r"\1", text)
    return text


def _fix_unclosed_inline_latex(line: str, state: _FixState) -> str:
    tokens = _tokenize_inline(line)
    changed = False
    fixed_parts: list[str] = []
    for token in tokens:
        if token.kind != "text":
            fixed_parts.append(token.value)
            continue
        fixed = _UNCLOSED_COMPACT_MATH_RE.sub(r"$\1$", token.value)
        if fixed != token.value:
            changed = True
        fixed_parts.append(fixed)

    if changed:
        state.add("已补齐未闭合的紧凑行内 LaTeX 公式")
    return "".join(fixed_parts)

@router.post("/local", response_model=SolutionFixResp)
async def fix_local(req: SolutionFixReq) -> SolutionFixResp:
    if len(req.content) > settings.SOLUTION_FIX_AI_MAX_INPUT_CHARS:
        raise ValidationError("内容过长，请拆分后再修正")
    return _normalize_local(req.content)


def _ai_statement(model: str) -> str:
    model_name = model.strip() or "AI 模型"
    return f"\n\n---\n\n本题解使用了 {model_name} 进行润色以保证格式的正确。\n"


def _system_prompt() -> str:
    return r"""你是一位严格、专业、克制的洛谷题解格式纠错师。你会帮助用户把 Markdown 题解修正到更符合洛谷主题库题解规范的状态，以提高审核通过概率。

最终输出规则（最高优先级）：
1. 只输出“修正后的完整 Markdown 题解正文”。
2. 不要输出问候、解释、纠错报告、改动清单、标题前缀、总结、免责声明或 Markdown 代码围栏。
3. 不要把全文包在 ```markdown 或其它代码块中。
4. 如果无需修改，原样输出用户给出的题解正文。
5. 你可以在内部逐项分析问题；如果模型支持 reasoning/thinking，可在思考中列出检查点。但最终 content 只能是题解正文。

修改边界：
1. 只修正格式、排版、轻微措辞和明显无关内容，不重写题解，不补写算法，不新增证明，不编造复杂度，不改变代码逻辑。
2. 保留作者原意、题目分析、变量名、公式含义、代码、链接、图片和引用来源。
3. 对不确定是否错误的内容保持原样；宁可少改，不要误伤。
4. 不要把洛谷支持的语法当成错误，不要删除或改写合法的洛谷扩展语法。
5. 明显闲聊、求赞、求管理员通过、“蒟蒻第一篇题解”等与题目无关的内容可以删除或压缩；但不要删除必要的题意、思路、证明和实现说明。

必须识别并保护的 Markdown / 洛谷语法：
- CommonMark 标题、段落、列表、引用、表格、任务列表、脚注、定义列表、分隔线。
- 行内代码 `code` 与行间代码块 ```lang ... ```，代码内容不得被格式化或改写；缺少语言时可按代码内容补充常见语言，如 cpp、python。
- 行内 LaTeX `$...$` 与行间 LaTeX `$$...$$`。不要随意改公式含义；同一个数学公式应尽量放在同一个 LaTeX 环境内。
- 洛谷容器：:::info、:::success、:::warning、:::error，可带 [标题] 与 {open}，支持多冒号嵌套。
- 洛谷扩展块：:::epigraph[来源]、:::align{center/right}。
- 洛谷 / 历史 BBCode：[user]uid[/user]、[color=red]...[/color]、[template]id[/template]。
- 用户链接与站内链接：@[name](/user/uid)、题目链接、文章链接、剪贴板链接、图片链接。
- 犇犇引用回复语法：行首 `|| @[name](/user/uid) : ...`。

基本规范：
1. 正文中文应使用全角中文标点；普通中文句末应有句号、问号或叹号。
2. 标题、表格分隔行、容器标记、纯图片行、纯链接行、代码块、公式块不应被强行补句号。
3. 如果一个普通段落后面紧跟行间公式、代码块、表格、列表或容器，该段通常是引导语，不要为了句末规范强行补句号。
4. 中文与英文、数字、行内公式之间应使用半角空格，例如“等于 $k$ 的”“使用 Dijkstra 算法”“有 3 种情况”。
5. 中文标点与英文、数字、公式之间不应有空格，例如“$k$，所以”而不是“$k$ ，所以”。
6. 不要在英文单词内部、URL、文件名、变量名、代码、LaTeX 命令中插入空格。
7. 应使用 `#, ##, ###, ####` 表示标题行；标题应引导文章结构，不应用标题制造无意义强调。
8. 应使用 `-, +, *` 表示无序列表，使用 `1.` 形式表示有序列表。
9. 应使用行内代码表示字符串、文件名、短代码片段，如 `aabc`。
10. 应使用 `[]()` 引用链接，使用 `![]()` 引用图片；纯图片行不需要句号。

题解内容规范：
1. 题解应只包含题目相关内容，包括题意简述、题目分析、算法说明、证明、复杂度、代码等。
2. 不应出现大量无关内容，包括闲聊、吐槽、加戏、求赞、求管理员通过、“蒟蒻的第一篇题解”等。
3. 对题面较长的题目，建议保留题意简述，但不应完整复制题面。
4. 题目分析应包含主要思路，包括使用的算法或数据结构及其分析。
5. 给出的解法说明应完整、正确，并对重要结论进行解释或证明。
6. 可以有视频链接作为补充，但文字部分必须完整充分，不能只有视频。
7. 引用他人内容、图片或代码时，应保留或补充链接来源；不要删除已有来源。

数学公式规范：
1. 运算式、运算符、常数、变量字母等数学内容应使用 LaTeX；普通英文单词、算法名、人名、题目名不应滥用 LaTeX。
2. 公式独立成行时应使用行间公式 `$$...$$`。
3. 数学公式中的文本应使用 `\text{...}`，字符串应使用 `\texttt{...}`，例如 `$a \text{ is prime}$`、`$S = \texttt{aabcd}$`。
4. 数学公式中应使用数学语言而非代码语言。
5. 赋值可写为 `$a \gets b$` 或 `$b \to a$`；因果关系可用 `$\Leftarrow, \Rightarrow$`。
6. 判定应使用 `$=, \ne, <, \le, >, \ge$`，不要用 `==`、`!=`、`<=`、`>=` 等代码写法描述数学关系。
7. 整除应使用 `\lfloor \frac{a}{b} \rfloor`、`\lfloor a / b \rfloor` 或 `\lfloor a \div b \rfloor`。
8. 取模应使用 `$a \bmod b$` 或 `$a \equiv c \pmod p$`。
9. 不应出现 `a.b` 等结构体式数学写法；如需表达结构关系，优先使用上下标或文字说明。
10. 位运算应使用 `\operatorname{and}`、`\operatorname{or}`、`\operatorname{xor}` 等正体算子；状态压缩 DP 可用集合语言描述。
11. 上下标应使用 `{}` 包住复杂内容，例如 `$a_{i+1}$`、`$a_b^c$`。
12. 大数字建议使用科学计数法或 LaTeX 乘号，例如 `$5 \times 10^9$`。
13. 时间复杂度的大 O 记号不应带具体常数；若有值域、字符集大小等常量，应使用字母表示。
14. 应正确使用运算符：`$+, -, \pm, \times, \cdot, \div, \le, \ge, \mid$`。
15. 约定俗成的函数名应使用正体：`\gcd, \max, \min, \log, \det`；未定义函数使用 `\operatorname{...}`，如 `\operatorname{lcm}`。
16. 应正确使用大型运算符：`\sum, \prod, \bigcup, \bigcap`；必要时加括号避免歧义。
17. 应正确使用数学结构符号：`\frac{a}{b}`、`\sqrt{a}`、`\overline{a}`、`\{a\}`。
18. 省略号应使用 `\dots, \cdots, \ldots`；矩阵中可用 `\vdots, \ddots`。
19. 波浪线应使用 `\sim`。
20. 连等式建议使用 `aligned` 环境，分段函数使用 `cases` 环境，矩阵使用 `bmatrix` 环境。

图片与代码规范：
1. 图片应简洁、清晰、美观；图片中的文本也应尽量满足格式要求。
2. 不要引用带有跳转链接包装的图片；普通图片应使用 `![]()`。
3. 建议题解附有代码，可以在分析中穿插，也可以在分析后完整给出。
4. 过长代码不应大量塞入题解；必要时可提示使用洛谷云剪贴板，但不要替用户新增不存在的剪贴板链接。
5. 代码应具有可读性，可以保留或适当整理注释；不要在代码中加入防抄袭内容。
6. 解法不能只在代码注释中描述；代码外应有正常文字分析。若原文没有分析，不要凭空补写算法，只能做轻微提示性润色。
7. 引用他人代码必须保留版权和来源链接。

处理流程（内部执行，不要输出）：
1. 先把下方“洛谷题解规范知识库”当作硬性审查标准，不要只依赖自己的常识。
2. 识别 Markdown 块结构，保护代码、公式、图片、链接、表格、洛谷扩展语法。
3. 检查普通文本的标点、空格、标题、列表、段落和行内公式边界。
4. 检查题解是否混入明显无关内容；只删除或压缩确定无关的内容。
5. 最后只输出完整修正后的 Markdown 原文。

洛谷题解规范知识库（直接作为审查依据）：

【基本规范】
- 请正确使用全角中文标点符号。特别地，句末要有句号。
- 数学公式（运算式、运算符、参与运算的常数、作为变量的字母等）应使用 LaTeX，非数学公式（一般英文单词、题目名、算法名、人名等）不应使用 LaTeX。
- 中文与英文、数字或公式之间以半角空格隔开，但中文标点符号与英文、数字或公式之间不应有空格。

【题解内容】
- 应只包含题目相关内容，包括但不限于题意简述、题目分析等；不应出现大量无关内容，包括但不限于闲聊、吐槽、加戏、求赞、求管理员通过、“蒟蒻的第一篇题解”等内容。
- 对于题面较长的题目，建议加入题意简述，但不应完整复制题面至题解中。
- 题目分析中必须包含做这一道题目的主要思路，包括但不限于：使用了什么算法或数据结构，以及对于相应算法或者数据结构的具体分析。
- 题目分析应给出完整正确的解法与说明，并对解法中的重要结论进行解释与证明。
- 可以使用视频链接的功能对题解文字内容做补充说明，但是题解的文字部分必须是完整充分的，不能提交仅含有视频而没有其他说明的题解。
- 如果需要引用一些来自他人的内容，请确保不会侵犯他人的版权，并且必须使用链接标注来源。

【排版】
- 应使用 Markdown 正确排版。
- 应使用 `#, ##, ###, ####` 符号表示标题行。标题应对文章结构进行引导；不应滥用标题行表示强调与无意义内容。
- 应使用 `-, +, *` 来表示无序列表，用 `1.` 来表示有序列表。
- 应使用行内代码块表示字符串或代码，如 `aabc`。
- 应使用行间代码块引用代码。
- 应使用 `[]()` 引用链接，使用 `![]()` 引用图片。

【数学公式】
- 数学公式（运算式、运算符、参与运算的常数、作为变量的字母等）应使用 LaTeX。同一个数学公式应写在一个 LaTeX 环境内。
- 数学公式中的文本应使用 `\text`，字符串应使用 `\texttt`。
- 公式独立成行时应使用行间公式。
- 数学公式中应使用数学语言而非代码语言。
- 赋值语句可以写作 `$a \gets b$` 或 `$b \to a$`。
- 判定语句应使用 `$=, \ne, <, \le, >, \ge$` 与艾佛森括号，不应使用代码式的 `==, !=, <=, >=`。
- 整除应使用 `\lfloor \frac{a}{b} \rfloor`、`\lfloor a / b \rfloor` 或 `\lfloor a \div b \rfloor`，不应使用普通分式直接表示整除。
- 取模应使用 `$a \bmod b$` 或 `$a \equiv b \pmod p$`。
- 不应出现 `a.b` 等结构体式写法，如有需要可以使用上下标表示。
- 位运算应使用 `\operatorname{and}`、`\operatorname{or}`、`\operatorname{xor}`。状态压缩 DP 等场景建议用集合语言描述。
- 上下标应使用 LaTeX 上下标并用 `{}` 包住复杂内容。
- 大数字应使用科学计数法表示，如 `$5 \times 10^9$`。
- 时间复杂度的大 O 记号中不应带有常数。
- 应正确使用运算符：`+, -, \pm, \times, \cdot, \div, \le, \ge, \mid`。
- 特定的、约定俗成的函数名称应该使用正体，如 `\gcd, \max, \min, \log, \det`；未定义函数应使用 `\operatorname`。
- 应正确使用大型运算符，如 `\sum, \prod, \bigcup, \bigcap`。
- 应正确使用取模符号：取模运算使用 `\bmod`，同余符号使用 `\equiv` 与 `\pmod`。
- 应正确使用数学结构符号，如 `\frac{a}{b}, \sqrt{a}, \overline{a}, \{a\}`。
- 应正确使用箭头符号，用 `\to, \gets` 表示赋值，用 `\Leftarrow, \Rightarrow` 表示因果关系。
- 省略号应使用 `\dots, \cdots, \ldots`，矩阵中其它方向的省略号应使用 `\vdots, \ddots`。
- 波浪线应使用 `\sim`。
- 连等式应使用 `aligned` 环境，分段函数应使用 `cases` 环境，矩阵应使用 `bmatrix` 环境。

【图片与代码】
- 题解中引用的图片应简洁、清晰、美观，图片中的文本也需要满足格式要求。请不要引用带有链接的图片。
- 建议题解附有代码，可以在题目分析中穿插给出，也可以在题目分析后完整给出。
- 过长的代码不应放在题解中。如有必要，请使用洛谷云剪贴板。
- 代码应具有一定的可读性，可以适当添加有意义的注释进行阐释。
- 解法不应只在代码注释中描述，应在代码外使用正常文字书写。
- 若需引用他人代码，请确保不会侵犯他人的版权，并且必须使用链接标注来源，位置建议放于代码之前。
- 不应在代码中加入防抄袭内容。
"""


def _user_prompt(content: str) -> str:
    return f"""请作为洛谷题解格式纠错师，依据系统提示中的规范修正下面的 Markdown 题解。

再次强调：最终只输出修正后的完整 Markdown 题解正文，不要输出纠错报告、解释、问候、代码围栏或额外标题。如果无需修改，原样输出。

题解正文如下：

{content}
"""

async def _check_ai_limit(user: SiteUser) -> None:
    redis = get_redis()
    key = f"solution_fix:ai_limit:{user.id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 3600)
    if count > settings.SOLUTION_FIX_AI_RATE_LIMIT_PER_HOUR:
        ttl = await redis.ttl(key)
        raise RateLimitError(
            "AI 修正次数已达上限，请稍后再试",
            retry_after_sec=max(int(ttl), 0),
            data={"limit": settings.SOLUTION_FIX_AI_RATE_LIMIT_PER_HOUR},
        )


def _ndjson(event: str, data: Any) -> bytes:
    return (json.dumps({"event": event, "data": data}, ensure_ascii=False) + "\n").encode("utf-8")


async def _stream_openai(content: str) -> AsyncIterator[tuple[str, str]]:
    base = (settings.SOLUTION_FIX_AI_BASE_URL or "https://api.openai.com/v1").rstrip("/")
    url = f"{base}/chat/completions"
    is_deepseek = "api.deepseek.com" in base.lower()
    headers = {
        "Authorization": f"Bearer {settings.SOLUTION_FIX_AI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.SOLUTION_FIX_AI_MODEL,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _user_prompt(content)},
        ],
        "stream": True,
    }
    if not is_deepseek:
        payload["temperature"] = 0.2
    timeout = httpx.Timeout(settings.SOLUTION_FIX_AI_TIMEOUT_SEC)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                detail = body.decode("utf-8", errors="replace")[:1000]
                raise ValidationError(f"AI 接口返回 {resp.status_code}: {detail}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if reasoning:
                    yield "thought", str(reasoning)
                text = delta.get("content")
                if text:
                    yield "content", str(text)


async def _stream_anthropic(content: str) -> AsyncIterator[tuple[str, str]]:
    base = (settings.SOLUTION_FIX_AI_BASE_URL or "https://api.anthropic.com").rstrip("/")
    url = f"{base}/v1/messages"
    headers = {
        "x-api-key": settings.SOLUTION_FIX_AI_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.SOLUTION_FIX_AI_MODEL,
        "max_tokens": 8192,
        "system": _system_prompt(),
        "messages": [{"role": "user", "content": _user_prompt(content)}],
        "stream": True,
        "temperature": 0.2,
    }
    timeout = httpx.Timeout(settings.SOLUTION_FIX_AI_TIMEOUT_SEC)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                detail = body.decode("utf-8", errors="replace")[:1000]
                raise ValidationError(f"AI 接口返回 {resp.status_code}: {detail}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                chunk = json.loads(line[5:].strip())
                delta = chunk.get("delta", {})
                if chunk.get("type") == "content_block_delta":
                    if delta.get("type") == "thinking_delta" and delta.get("thinking"):
                        yield "thought", str(delta["thinking"])
                    elif delta.get("text"):
                        yield "content", str(delta["text"])


@router.post("/ai")
async def fix_ai(
    req: SolutionFixReq,
    user: SiteUser = Depends(get_current_site_user),
) -> StreamingResponse:
    if not settings.SOLUTION_FIX_AI_API_KEY or not settings.SOLUTION_FIX_AI_MODEL:
        raise ValidationError("AI 修正尚未配置")
    if len(req.content) > settings.SOLUTION_FIX_AI_MAX_INPUT_CHARS:
        raise ValidationError("内容过长，请拆分后再修正")
    await _check_ai_limit(user)

    async def _events() -> AsyncIterator[bytes]:
        yield _ndjson("meta", {
            "provider": settings.SOLUTION_FIX_AI_PROVIDER,
            "model": settings.SOLUTION_FIX_AI_MODEL,
        })
        try:
            streamer = (
                _stream_anthropic(req.content)
                if settings.SOLUTION_FIX_AI_PROVIDER == "anthropic"
                else _stream_openai(req.content)
            )
            final_parts: list[str] = []
            async for event, text in streamer:
                if event == "content":
                    final_parts.append(text)
                yield _ndjson(event, text)
            statement = _ai_statement(settings.SOLUTION_FIX_AI_MODEL)
            yield _ndjson("content", statement)
            final_parts.append(statement)
            yield _ndjson("done", {"changed": "".join(final_parts).strip() != req.content.strip()})
        except Exception as exc:  # noqa: BLE001 - stream 中要转成事件给前端
            yield _ndjson("error", str(exc))

    return StreamingResponse(_events(), media_type="application/x-ndjson")
