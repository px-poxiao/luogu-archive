"""洛谷页面数据提取。

洛谷有两套前端并存：
1. 新版 SSR：`<script id="lentille-context" type="application/json">{...}</script>`
   （文章、用户、陶片等大部分页面走这个）

2. 老版 SSR：`<script>window._feInjection = JSON.parse(decodeURIComponent("..."));</script>`
   （**剪贴板 /paste/ 走这个**；个别老页面也是）

两种都要能解析。提供 `extract_page_data()` 一站式入口，自动识别哪种。
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

import orjson

# 新版 SSR
_LENTILLE_PATTERN = re.compile(
    r'<script\s+id="lentille-context"\s+type="application/json">(.*?)</script>',
    re.DOTALL,
)

# 老版 SSR —— window._feInjection = JSON.parse(decodeURIComponent("<percent-encoded JSON>"));
# 值是被 encodeURIComponent 两次 wrap 的：外层是 JS 字符串字面量，内层是 URL-encoded。
_FE_INJECTION_PATTERN = re.compile(
    r'window\._feInjection\s*=\s*JSON\.parse\(\s*decodeURIComponent\(\s*"((?:[^"\\]|\\.)*)"\s*\)\s*\)',
    re.DOTALL,
)


class LentilleParseError(ValueError):
    """无法在 HTML 里找到数据，或解析失败。"""


def extract_lentille_context(html: str) -> dict[str, Any]:
    """从洛谷新版页面 HTML 中提取嵌入的 lentille JSON。

    返回顶层对象（含 instance / template / status / data / user / time / theme ...）。
    未找到抛 LentilleParseError。
    """
    m = _LENTILLE_PATTERN.search(html)
    if not m:
        raise LentilleParseError("未在 HTML 中找到 <script id='lentille-context'>")
    raw = m.group(1)
    try:
        return orjson.loads(raw)
    except orjson.JSONDecodeError as e:
        raise LentilleParseError(f"lentille-context JSON 解析失败: {e}") from e


def extract_fe_injection(html: str) -> dict[str, Any]:
    """从洛谷老版页面 HTML 中提取 window._feInjection JSON。

    返回顶层对象（含 code / currentTemplate / currentData / currentUser / currentTime ...）。
    """
    m = _FE_INJECTION_PATTERN.search(html)
    if not m:
        raise LentilleParseError("未在 HTML 中找到 window._feInjection")
    # 这是 JS 字符串字面量内容，里面的 \" 要还原成 "，\\ → \，\\u00xx → 对应字符
    raw_js = m.group(1)
    try:
        # 把 JS 字符串字面量转回真实字符串：最简单的方式是让 JSON 当字符串解析
        decoded_inner = orjson.loads(f'"{raw_js}"')
    except orjson.JSONDecodeError:
        # 兜底：人工处理几个常见转义
        decoded_inner = raw_js.replace("\\\"", "\"").replace("\\\\", "\\")
    # 再 URL-decode
    try:
        json_text = unquote(decoded_inner)
        return orjson.loads(json_text)
    except (orjson.JSONDecodeError, ValueError) as e:
        raise LentilleParseError(f"_feInjection JSON 解析失败: {e}") from e


def extract_page_data(html: str) -> tuple[str, dict[str, Any]]:
    """统一入口：自动识别新版/老版 SSR，返回 (kind, data)。

    kind:
      - "lentille"  -> data 是完整的 lentille 对象（有 data/user/time 等顶层字段）
      - "injection" -> data 是 _feInjection 对象（有 currentData/currentTemplate 等）

    两种都找不到就抛异常。
    """
    try:
        return "lentille", extract_lentille_context(html)
    except LentilleParseError:
        pass
    # 回退到老版
    return "injection", extract_fe_injection(html)


def current_user_from_lentille(ctx: dict[str, Any]) -> dict[str, Any] | None:
    """取出顶层 user 字段（= 当前登录身份，用于 Cookie 账号自检）。

    未登录时返回 None。仅适用于新版 lentille。
    """
    return ctx.get("user")


def data_from_lentille(ctx: dict[str, Any]) -> dict[str, Any]:
    """取 data 字段，容错：可能是 None 或非 dict。"""
    data = ctx.get("data")
    if not isinstance(data, dict):
        return {}
    return data


def current_data_from_injection(ctx: dict[str, Any]) -> dict[str, Any]:
    """老版 _feInjection 的 currentData 字段。"""
    data = ctx.get("currentData")
    if not isinstance(data, dict):
        return {}
    return data
