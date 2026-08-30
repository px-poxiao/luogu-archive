from app.core.config import settings
from app.core.crawl_policy import (
    automatic_cascade_allowed,
    crawl_trigger_allowed,
    proactive_crawling_enabled,
)


def test_default_policy_only_allows_explicit_user_requests(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CRAWLER_PROACTIVE_ENABLED", False)

    for trigger in ("manual", "manual_followup", "passive", "first_time", "admin"):
        assert crawl_trigger_allowed(trigger)

    for trigger in (
        "scheduled",
        "discovery",
        "internal",
        "cascaded_from_article",
        "cascaded_from_user:manual",
        None,
        "",
    ):
        assert not crawl_trigger_allowed(trigger)

    assert not proactive_crawling_enabled()
    assert not automatic_cascade_allowed()


def test_legacy_switch_can_restore_preserved_code(monkeypatch) -> None:
    monkeypatch.setattr(settings, "CRAWLER_PROACTIVE_ENABLED", True)

    assert proactive_crawling_enabled()
    assert automatic_cascade_allowed()
    assert crawl_trigger_allowed("scheduled")
    assert crawl_trigger_allowed("discovery")
