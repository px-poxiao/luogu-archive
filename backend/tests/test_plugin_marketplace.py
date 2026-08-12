"""插件申请快照的安全边界测试。"""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.services.plugin_marketplace import PluginSnapshot, code_sha256


def valid_snapshot(**changes) -> PluginSnapshot:
    values = {
        "name": "测试插件",
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
        "target_pages": "/problem/*",
        "last_verified_on": date(2026, 8, 12),
        "min_compatible_date": date(2026, 1, 1),
        "compatibility_notes": None,
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


def test_compatibility_date_or_note_is_required() -> None:
    with pytest.raises(PydanticValidationError):
        valid_snapshot(min_compatible_date=None, compatibility_notes="")
