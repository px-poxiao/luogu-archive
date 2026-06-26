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
_INLINE_PROTECTED_RE = re.compile(
    r"(`+[^`]*`+|\$[^$\n]+\$|!\[[^\]]*\]\([^)]+\)|\[[^\]]+\]\([^)]+\)|"
    r"https?://[^\s]+|@[^\s]+)",
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
_LEADING_TEXT_RE = re.compile(
    r"(?:如下|如下所示|如下图|代码如下|证明如下|过程如下|"
    r"为|是|有|即|得到|可得|推出|转移为|转移方程为|方程为|式子为|表达式为|公式为)$"
)


def _next_meaningful_line(lines: list[str], start: int) -> str | None:
    for raw in lines[start:]:
        if raw.strip():
            return raw
    return None


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
    return "paragraph"


def _looks_like_block_lead(line: str) -> bool:
    stripped = line.strip()
    stripped = re.sub(r"[：:]$", "", stripped)
    return _LEADING_TEXT_RE.search(stripped) is not None


def _next_block_blocks_period(next_line: str | None) -> bool:
    if next_line is None:
        return False
    return _line_kind(next_line) in {
        "math_block",
        "code_fence",
        "container",
        "quote_reply",
        "table",
        "list",
    }


def _normalize_local(content: str) -> SolutionFixResp:
    """只做保守的 Markdown 排版修正，避免误伤洛谷扩展语法。"""
    state = _FixState(notes=[])
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    if text != content:
        state.add("已统一换行为 LF")

    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    fence_marker = ""
    blank_run = 0

    for index, raw in enumerate(lines):
        line = raw.rstrip() if raw.strip() == "" else raw
        if line != raw:
            state.add("已清理空白行中的多余空格")

        fence = _FENCE_OPEN_RE.match(line)
        if fence:
            marker = fence.group(2)
            if not in_fence:
                info = fence.group(3).strip()
                fixed = f"{fence.group(1)}{marker}{info}"
                if fixed != line:
                    line = fixed
                    state.add("已整理代码块语言标记后的多余空格")
                in_fence = True
                fence_marker = marker
            elif marker.startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            blank_run = 0
            out.append(line)
            continue

        if in_fence:
            out.append(line)
            continue

        if line.strip() == "":
            blank_run += 1
            if blank_run <= 2:
                out.append("")
            elif blank_run == 3:
                state.add("已压缩连续空行为最多两行")
            continue

        blank_run = 0

        # 按块级类型保护洛谷扩展、公式块、表格和预处理器；普通段落再做行内修正。
        stripped = line.lstrip()
        kind = _line_kind(line)
        protected = kind in {
            "container",
            "quote_reply",
            "math_block",
            "table",
            "luogu_bbcode",
            "cpp_preprocessor",
        }

        if not protected:
            fixed = _HEADING_RE.sub(r"\1 \2", line)
            if fixed != line:
                line = fixed
                state.add("已补齐标题标记后的空格")
            line = _fix_unclosed_inline_latex(line, state)
            line = _fix_text_spacing(line, state)
            line = _fix_sentence_period(line, state, _next_meaningful_line(lines, index + 1))

        out.append(line)

    if in_fence:
        out.append(fence_marker)
        state.add("检测到未闭合代码块，已补齐闭合标记")

    fixed_text = "\n".join(out).strip() + "\n"
    if fixed_text != content:
        state.changed = True

    return SolutionFixResp(
        mode="local",
        content=fixed_text,
        changed=state.changed,
        notes=state.notes or [],
    )


def _is_text_token(token: str) -> bool:
    return not _INLINE_PROTECTED_RE.fullmatch(token)


def _split_inline_protected(line: str) -> list[str]:
    parts: list[str] = []
    pos = 0
    for match in _INLINE_PROTECTED_RE.finditer(line):
        if match.start() > pos:
            parts.append(line[pos:match.start()])
        parts.append(match.group(0))
        pos = match.end()
    if pos < len(line):
        parts.append(line[pos:])
    return parts


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
    parts = _split_inline_protected(line)
    changed = False
    fixed_parts: list[str] = []
    for part in parts:
        if not _is_text_token(part):
            fixed_parts.append(part)
            continue
        fixed = _UNCLOSED_COMPACT_MATH_RE.sub(r"$\1$", part)
        if fixed != part:
            changed = True
        fixed_parts.append(fixed)

    if changed:
        state.add("已补齐未闭合的紧凑行内 LaTeX 公式")
    return "".join(fixed_parts)


def _fix_text_spacing(line: str, state: _FixState) -> str:
    parts = _split_inline_protected(line)
    if not parts:
        return line

    normalized: list[str] = []
    for part in parts:
        normalized.append(_fix_plain_text_spacing(part) if _is_text_token(part) else part)

    result = "".join(normalized)

    # 在中文与行内公式/代码/链接边界之间补空格，同时不在中文标点旁保留空格。
    for i in range(len(normalized) - 1):
        left = normalized[i]
        right = normalized[i + 1]
        if not left or not right:
            continue
        left_tail = left[-1]
        right_head = right[0]
        if left_tail.isspace() or right_head.isspace():
            continue
        if left_tail in _CJK_PUNCT or right_head in _CJK_PUNCT:
            continue
        if _need_cjk_space(left_tail, right_head):
            normalized[i] = f"{left} "
        elif _CJK_RE.search(left_tail) and not _is_text_token(right):
            normalized[i] = f"{left} "
        elif not _is_text_token(left) and _CJK_RE.search(right_head):
            normalized[i] = f"{left} "

    result = "".join(normalized)
    result = re.sub(r"\s+([，。！？；：、])", r"\1", result)
    result = re.sub(r"([，。！？；：、])\s+", r"\1", result)
    if result != line:
        state.add("已按中文与英文、数字或公式之间的空格规范调整")
    return result


def _fix_sentence_period(line: str, state: _FixState, next_line: str | None = None) -> str:
    stripped = line.rstrip()
    if not stripped:
        return line
    if _line_kind(stripped) != "paragraph":
        return line
    if _SENTENCE_END_RE.search(stripped):
        return line
    if _next_block_blocks_period(next_line) and _looks_like_block_lead(stripped):
        return line
    if re.search(r"[\u3400-\u9fffA-Za-z0-9）\])`$]$", stripped):
        state.add("已为普通段落补齐中文句号")
        return f"{stripped}。"
    return line


@router.post("/local", response_model=SolutionFixResp)
async def fix_local(req: SolutionFixReq) -> SolutionFixResp:
    if len(req.content) > settings.SOLUTION_FIX_AI_MAX_INPUT_CHARS:
        raise ValidationError("内容过长，请拆分后再修正")
    return _normalize_local(req.content)


def _ai_statement(model: str) -> str:
    model_name = model.strip() or "AI 模型"
    return f"\n\n---\n\n本题解使用了 {model_name} 进行润色以保证格式的正确。\n"


def _system_prompt() -> str:
    return """你是洛谷题解格式修正助手。你的任务是输出“修正后的题解正文”，不要输出解释、标题、前后缀或 Markdown 代码围栏。

必须遵守：
1. 保留作者原意、算法、复杂度、代码、变量名、证明逻辑，不编造新内容。
2. 不要把洛谷支持的语法当作错误，不要删除或改写它们。
3. 保留并正确处理洛谷/本站支持的 Markdown 与扩展语法：
   - CommonMark 标题、列表、引用、表格、任务列表、脚注、定义列表、代码块。
   - 行内/块级 LaTeX：$...$、$$...$$，不要随意改公式内容。
   - 洛谷容器：:::info、:::success、:::warning、:::error，可带 [标题] 与 {open}；支持多冒号嵌套。
   - 洛谷扩展块：:::epigraph[来源]、:::align{center/right}。
   - 洛谷/历史 BBCode：[user]uid[/user]、[color=red]...[/color]、[template]id[/template]。
   - 用户链接：@[name](/user/uid)，洛谷链接、题目链接、文章链接、图片链接。
   - 犇犇引用回复语法：行首 || @[name](/user/uid) : ...
4. 可以修正明显的排版问题：标题/列表空格、过多空行、代码块闭合、代码块语言标记、段落空行、标点/空格不一致。
5. 普通中文正文句末应有中文句号、问号或叹号；不要给标题、代码、表格分隔行、容器标记强行加句号。
6. 中文和英文、数字或行内公式之间应使用半角空格，例如“等于 $k$ 的”；中文标点与英文、数字或公式之间不应有空格。
7. 如果行内 LaTeX 明显未闭合，例如“$k 的取值”，应修为“$k$ 的取值”；不要误改块级 $$...$$。
8. 如果发现内容质量问题，你不应进行更改，你只需要关注格式信息。
9. 如果无需修改，原样输出。
"""


def _user_prompt(content: str) -> str:
    return f"""请按洛谷题解规范修正下面的题解正文，只输出修正后的正文。

题解正文：

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
    if is_deepseek:
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = "high"
    else:
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
