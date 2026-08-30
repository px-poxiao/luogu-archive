"""保存站爬取边界的集中策略。

旧的定时发现和级联代码全部保留，但默认不注册、不派发，并在 worker 消费旧消息时
再次校验。以后若形成符合社区规范的新方案，只需调整配置和这里的判定。
"""
from __future__ import annotations

from app.core.config import settings


# 这些触发源都对应用户或管理员明确指定的单个对象。
_USER_REQUESTED_TRIGGERS = {
    "manual",
    "manual_followup",
    "manual_save",
    "passive",
    "first_time",
    "admin",
}


def proactive_crawling_enabled() -> bool:
    """是否允许定时发现、批量扫描和程序自动级联。"""

    return bool(settings.CRAWLER_PROACTIVE_ENABLED)


def is_user_requested_trigger(trigger: str | None) -> bool:
    """判断任务是否来自用户明确指定对象的操作。"""

    return str(trigger or "").strip().lower() in _USER_REQUESTED_TRIGGERS


def crawl_trigger_allowed(trigger: str | None) -> bool:
    """主动模式关闭时，仅放行明确的用户请求。"""

    return proactive_crawling_enabled() or is_user_requested_trigger(trigger)


def automatic_cascade_allowed() -> bool:
    """文章作者、用户内容等未被用户单独指定的级联是否允许。"""

    return proactive_crawling_enabled()
