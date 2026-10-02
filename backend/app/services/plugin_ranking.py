"""插件广场智能排序表达式。"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import case, desc, func, select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from app.models.plugin import Plugin, PluginUsageEvent, PluginVersion


def usage_statistics(today: date) -> Subquery:
    """汇总近 30 天按访客、按日去重的使用数据。"""

    seven_days_ago = today - timedelta(days=6)
    thirty_days_ago = today - timedelta(days=29)
    return (
        select(
            PluginUsageEvent.plugin_id.label("plugin_id"),
            func.count(func.distinct(PluginUsageEvent.visitor_key)).label("usage_30d"),
            func.count(
                func.distinct(
                    case(
                        (
                            PluginUsageEvent.event_date >= seven_days_ago,
                            PluginUsageEvent.visitor_key,
                        ),
                        else_=None,
                    )
                )
            ).label("usage_7d"),
        )
        .where(PluginUsageEvent.event_date >= thirty_days_ago)
        .group_by(PluginUsageEvent.plugin_id)
        .subquery("plugin_usage_statistics")
    )


def recent_usage_columns(statistics: Subquery) -> tuple[ColumnElement, ColumnElement]:
    """返回带零值兜底的 30 天和 7 天使用量。"""

    return (
        func.coalesce(statistics.c.usage_30d, 0),
        func.coalesce(statistics.c.usage_7d, 0),
    )


def smart_score(
    statistics: Subquery,
    today: date,
) -> ColumnElement:
    """组合使用量、时效、人工标记和请求等级，返回可排序分值。"""

    usage_30d, usage_7d = recent_usage_columns(statistics)
    verified_days = func.greatest(0, func.datediff(today, PluginVersion.last_verified_on))
    published_days = func.greatest(0, func.datediff(today, Plugin.approved_at))

    # 对数压缩可防止头部插件仅凭历史体量永久垄断；两个时间窗口分别衡量
    # 稳定使用和短期活跃。验证、新品加分都会随时间平滑归零。
    usage_score = func.log(1 + usage_30d) * 18
    trend_score = func.log(1 + usage_7d) * 12
    verification_score = func.greatest(0, 12 - verified_days * (12 / 90))
    newcomer_score = func.greatest(0, 10 - published_days * (10 / 14))
    trust_score = case((Plugin.is_official.is_(True), 15), else_=0) + case(
        (Plugin.is_recommended.is_(True), 8), else_=0
    )
    request_penalty = case(
        (PluginVersion.final_request_level == 1, 3),
        (PluginVersion.final_request_level == 2, 10),
        (PluginVersion.final_request_level == 3, 22),
        else_=0,
    )
    return (
        usage_score
        + trend_score
        + verification_score
        + newcomer_score
        + trust_score
        - request_penalty
    )


def plugin_ordering(
    sort_mode: str,
    statistics: Subquery,
    today: date,
) -> tuple[ColumnElement, ...]:
    """根据公开排序模式生成稳定的 SQL ORDER BY。"""

    usage_30d, usage_7d = recent_usage_columns(statistics)
    if sort_mode == "latest":
        return desc(Plugin.updated_at), desc(Plugin.id)
    if sort_mode == "usage":
        return desc(usage_30d), desc(usage_7d), desc(Plugin.updated_at), desc(Plugin.id)
    if sort_mode == "verified":
        return (
            desc(PluginVersion.last_verified_on),
            desc(Plugin.updated_at),
            desc(Plugin.id),
        )
    return desc(smart_score(statistics, today)), desc(Plugin.updated_at), desc(Plugin.id)
