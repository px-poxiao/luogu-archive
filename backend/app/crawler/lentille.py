"""lentille-context 提取与解析。

洛谷所有 SSR 页面都会在 HTML 里嵌入：
    <script id="lentille-context" type="application/json">{...}</script>

我们爬虫的主力路径就是解析这个 JSON。也支持：
- 同 URL + `Accept: application/json` 直接拿 JSON（陶片就是这样）
- API 路径直接返 JSON（犇犇 `/api/feed/list`）

本模块提供统一入口：给一段 HTML 或字节，吐出结构化数据。
"""
from __future__ import annotations

import re
from typing import Any

import orjson

# 尽量精准匹配，避免 HTML 注释里类似内容混淆
_LENTILLE_PATTERN = re.compile(
    r'<script\s+id="lentille-context"\s+type="application/json">(.*?)</script>',
    re.DOTALL,
)


class LentilleParseError(ValueError):
    """无法在 HTML 里找到 lentille-context，或解析失败。"""


def extract_lentille_context(html: str) -> dict[str, Any]:
    """从洛谷 HTML 中提取嵌入的 lentille JSON。

    返回顶层对象（含 instance / template / status / data / user / time / theme ...）。
    """
    m = _LENTILLE_PATTERN.search(html)
    if not m:
        raise LentilleParseError("未在 HTML 中找到 <script id='lentille-context'>")
    raw = m.group(1)
    try:
        return orjson.loads(raw)
    except orjson.JSONDecodeError as e:
        raise LentilleParseError(f"lentille-context JSON 解析失败: {e}") from e


def current_user_from_lentille(ctx: dict[str, Any]) -> dict[str, Any] | None:
    """取出顶层 user 字段（= 当前登录身份，用于 Cookie 账号自检）。

    未登录时返回 None。
    """
    return ctx.get("user")


def data_from_lentille(ctx: dict[str, Any]) -> dict[str, Any]:
    """取 data 字段，容错：可能是 None 或非 dict。"""
    data = ctx.get("data")
    if not isinstance(data, dict):
        return {}
    return data
