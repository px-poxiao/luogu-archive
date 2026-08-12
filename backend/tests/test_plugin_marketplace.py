"""插件申请快照的安全边界测试。"""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.services.plugin_marketplace import (
    CODE_PREVIEW_MAX_BYTES,
    PluginSnapshot,
    article_summary,
    code_preview,
    code_sha256,
    snapshot_preview_dict,
)


def valid_snapshot(**changes) -> PluginSnapshot:
    values = {
        "summary": "用于验证插件广场字段。",
        "version": "1.0.0",
        "code": "console.log('ok')",
        "download_filename": "plugin.user.js",
        "user_request_level": 1,
        "user_request_analysis": "只在打开页面时请求一次公开接口。",
        "tag_ids": [1, 2],
        "runtime_mode": "userscript",
        "supports_desktop": True,
        "supports_mobile": False,
        "last_verified_on": date(2026, 8, 12),
    }
    values.update(changes)
    return PluginSnapshot(**values)


def test_admin_request_level_overrides_user_level() -> None:
    snapshot = valid_snapshot(user_request_level=1, admin_request_level=3)
    assert snapshot.final_request_level == 3


def test_code_sha256_is_stable() -> None:
    assert code_sha256("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


@pytest.mark.parametrize("filename", ["../plugin.js", "sub/plugin.js", "bad\r\nname.js", "C:\\plugin.js"])
def test_download_filename_rejects_path_and_header_injection(filename: str) -> None:
    with pytest.raises(PydanticValidationError):
        valid_snapshot(download_filename=filename)


def test_code_larger_than_five_mib_is_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        valid_snapshot(code="x" * (5 * 1024 * 1024 + 1))


def test_at_least_one_device_is_required() -> None:
    with pytest.raises(PydanticValidationError):
        valid_snapshot(supports_desktop=False, supports_mobile=False)


def test_summary_can_be_omitted() -> None:
    assert valid_snapshot(summary="").summary is None


def test_article_summary_uses_visible_markdown_text() -> None:
    result = article_summary("# 标题\n\n这是[链接](https://example.com)和 `代码`。", "后备标题")
    assert result == "标题 这是链接和 代码。"


def test_article_summary_is_limited_to_fifty_characters() -> None:
    result = article_summary("这" * 80, "后备标题")
    assert len(result) == 50
    assert result.endswith("…")


def test_code_preview_is_limited_to_one_thousand_lines() -> None:
    code = "\n".join(f"line-{index}" for index in range(1001))
    preview, source_bytes, truncated = code_preview(code)
    assert len(preview.split("\n")) == 1000
    assert "line-1000" not in preview
    assert source_bytes == len(code.encode("utf-8"))
    assert truncated is True


def test_code_preview_is_utf8_safe_and_limited_to_fifty_kib() -> None:
    code = "测试" * 20_000
    preview, source_bytes, truncated = code_preview(code)
    assert len(preview.encode("utf-8")) <= CODE_PREVIEW_MAX_BYTES
    assert source_bytes == len(code.encode("utf-8"))
    assert truncated is True


def test_snapshot_response_does_not_expose_full_code() -> None:
    snapshot = valid_snapshot(code="x" * (CODE_PREVIEW_MAX_BYTES + 100))
    result = snapshot_preview_dict(snapshot)
    assert len(result["code"].encode("utf-8")) == CODE_PREVIEW_MAX_BYTES
    assert result["code_bytes"] == CODE_PREVIEW_MAX_BYTES + 100
    assert result["code_truncated"] is True
