"""SVG information cards generated from archived Luogu feed data."""
from __future__ import annotations

import html
import random
import re
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.redis_client import get_redis
from app.models.luogu_content import Feed
from app.models.luogu_user import LuoguUser

router = APIRouter(prefix="/image/feed", tags=["image-card"])

CARD_CACHE_SECONDS = 600
SHANGHAI = ZoneInfo("Asia/Shanghai")
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _xml(value: object) -> str:
    return html.escape(str(value), quote=True)


def _to_shanghai(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(SHANGHAI)


def _now_shanghai() -> datetime:
    return datetime.now(SHANGHAI)


def _format_generated_at(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M")


def _format_time_only(now: datetime) -> str:
    return now.strftime("%H:%M")


def _avatar_letter(user: LuoguUser | None, uid: int) -> str:
    name = (user.name if user else "").strip()
    if name:
        return name[0].upper()
    return str(uid)[0]


def _display_name(user: LuoguUser | None, uid: int) -> str:
    name = (user.name if user else "").strip()
    return name or f"UID {uid}"


def _strip_markdown(md: str) -> str:
    text = md or ""
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"```[\s\S]*?```", " 代码片段 ", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[#>*_~\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or "这条犇犇暂时没有可展示的文字。"


def _wrap_text(text: str, *, line_chars: int, max_lines: int) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ["这条犇犇暂时没有可展示的文字。"]

    lines: list[str] = []
    current = ""
    current_width = 0.0

    def width_of(ch: str) -> float:
        if ch.isspace():
            return 0.5
        return 0.55 if ord(ch) < 128 else 1.0

    for ch in text:
        w = width_of(ch)
        if current and current_width + w > line_chars:
            lines.append(current.rstrip())
            current = ch.lstrip()
            current_width = width_of(current) if current else 0.0
            if len(lines) == max_lines:
                break
        else:
            current += ch
            current_width += w

    if len(lines) < max_lines and current.strip():
        lines.append(current.strip())

    if len(lines) > max_lines:
        lines = lines[:max_lines]

    consumed = "".join(lines)
    if len(consumed) < len(text) and lines:
        lines[-1] = lines[-1].rstrip("，。,. ") + "…"
    return lines or ["这条犇犇暂时没有可展示的文字。"]


async def _cache_get(key: str) -> str | None:
    try:
        raw = await get_redis().get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return str(raw)


async def _cache_set(key: str, value: str) -> None:
    try:
        await get_redis().setex(key, CARD_CACHE_SECONDS, value)
    except Exception:
        pass


def _svg_response(svg: str) -> Response:
    return Response(
        content=svg,
        media_type="image/svg+xml; charset=utf-8",
        headers={
            "Cache-Control": f"public, max-age={CARD_CACHE_SECONDS}",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
        },
    )


async def _load_user(db: AsyncSession, uid: int) -> LuoguUser | None:
    return await db.get(LuoguUser, uid)


async def _load_feeds_since(db: AsyncSession, uid: int, since: datetime) -> list[Feed]:
    q = (
        select(Feed)
        .where(Feed.author_uid == uid, Feed.time >= since)
        .order_by(desc(Feed.time))
    )
    return list((await db.execute(q)).scalars().all())


def _activity_stats(rows: list[Feed], now: datetime) -> dict[str, object]:
    today = now.date()
    seven_dates = [today - timedelta(days=i) for i in range(6, -1, -1)]
    counts = {day: 0 for day in seven_dates}
    hour_counts: Counter[int] = Counter()
    latest_hour_for_tie: dict[int, datetime] = {}
    active_dates: set = set()

    for row in rows:
        local_time = _to_shanghai(row.time)
        day = local_time.date()
        active_dates.add(day)
        if day in counts:
            counts[day] += 1
            hour_counts[local_time.hour] += 1
            old = latest_hour_for_tie.get(local_time.hour)
            if old is None or local_time > old:
                latest_hour_for_tie[local_time.hour] = local_time

    daily = [counts[day] for day in seven_dates]
    total_7 = sum(daily)

    start_day = today if today in active_dates else today - timedelta(days=1)
    streak = 0
    cursor = start_day
    while cursor in active_dates:
        streak += 1
        cursor -= timedelta(days=1)
        if streak >= 90:
            break

    if today not in active_dates and (today - timedelta(days=1)) not in active_dates:
        streak = 0

    if hour_counts:
        max_count = max(hour_counts.values())
        tied = [h for h, c in hour_counts.items() if c == max_count]
        common_hour = max(tied, key=lambda h: latest_hour_for_tie.get(h, datetime.min.replace(tzinfo=SHANGHAI)))
        common_hour_text = f"{common_hour:02d}:00"
    else:
        common_hour_text = "暂无"

    return {
        "dates": seven_dates,
        "daily": daily,
        "total_7": total_7,
        "streak": "90+" if streak >= 90 else str(streak),
        "common_hour": common_hour_text,
    }


def _activity_svg(uid: int, user: LuoguUser | None, stats: dict[str, object], now: datetime) -> str:
    name = _xml(_display_name(user, uid))
    letter = _xml(_avatar_letter(user, uid))
    generated_at = _xml(_format_generated_at(now))
    daily = list(stats["daily"])
    dates = list(stats["dates"])
    max_count = max(max(daily), 1)

    chart_left = 520
    chart_top = 148
    chart_width = 540
    chart_height = 178
    step = chart_width / 6
    points: list[tuple[float, float, int]] = []
    for idx, count in enumerate(daily):
        x = chart_left + idx * step
        y = chart_top + chart_height - (count / max_count) * chart_height
        points.append((x, y, int(count)))

    path = " ".join(("M" if idx == 0 else "L") + f"{x:.1f},{y:.1f}" for idx, (x, y, _) in enumerate(points))
    circles = "\n".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#0ea5e9" stroke="#fff" stroke-width="3"/>'
        f'<text x="{x:.1f}" y="{max(34, y - 16):.1f}" text-anchor="middle" class="pointValue">{count}</text>'
        for x, y, count in points
    )
    labels = "\n".join(
        f'<text x="{chart_left + idx * step:.1f}" y="360" text-anchor="middle" class="axis">{_xml(WEEKDAY_LABELS[day.weekday()])}</text>'
        for idx, day in enumerate(dates)
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="520" viewBox="0 0 1200 520" role="img" aria-label="{name} 的犇犇活跃统计图卡">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f8fbff"/><stop offset="0.56" stop-color="#eef7ff"/><stop offset="1" stop-color="#ecfdf5"/></linearGradient>
    <linearGradient id="avatar" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#38bdf8"/><stop offset="1" stop-color="#10b981"/></linearGradient>
    <linearGradient id="line" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#2563eb"/><stop offset="1" stop-color="#10b981"/></linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="18" stdDeviation="22" flood-color="#0f172a" flood-opacity="0.14"/></filter>
    <style>text{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif}}.name{{fill:#0f172a;font-size:38px;font-weight:900}}.muted{{fill:#64748b;font-size:18px;font-weight:520}}.label{{fill:#64748b;font-size:17px;font-weight:650}}.value{{fill:#0f172a;font-size:31px;font-weight:850}}.title{{fill:#0f172a;font-size:32px;font-weight:850}}.axis{{fill:#64748b;font-size:15px;font-weight:560}}.pointValue{{fill:#0f172a;font-size:16px;font-weight:800}}</style>
  </defs>
  <rect width="1200" height="520" rx="38" fill="url(#bg)"/>
  <circle cx="1060" cy="78" r="168" fill="#bfdbfe" opacity="0.38"/><circle cx="120" cy="430" r="154" fill="#bbf7d0" opacity="0.30"/>
  <rect x="42" y="42" width="1116" height="436" rx="34" fill="#fff" fill-opacity="0.78" stroke="#d9e8f4" filter="url(#shadow)"/>
  <rect x="66" y="66" width="360" height="388" rx="28" fill="#fff" fill-opacity="0.52" stroke="#e1edf7"/>
  <rect x="454" y="66" width="680" height="388" rx="28" fill="#fff" fill-opacity="0.44" stroke="#e1edf7"/>
  <g transform="translate(102 104)">
    <circle cx="70" cy="70" r="70" fill="url(#avatar)"/><circle cx="70" cy="70" r="64" fill="#fff" opacity="0.18"/><text x="70" y="88" text-anchor="middle" fill="#fff" font-size="48" font-weight="900">{letter}</text>
    <text x="0" y="184" class="name">{name}</text><text x="0" y="218" class="muted">UID {uid}</text>
    <g transform="translate(0 276)"><text x="0" y="0" class="label">近 7 天</text><text x="0" y="42" class="value">{stats['total_7']}</text></g>
    <g transform="translate(124 276)"><text x="0" y="0" class="label">连续活跃</text><text x="0" y="42" class="value">{_xml(stats['streak'])} 天</text></g>
    <g transform="translate(256 276)"><text x="0" y="0" class="label">常上线</text><text x="0" y="42" class="value" font-size="27">{_xml(stats['common_hour'])}</text></g>
  </g>
  <g>
    <text x="502" y="116" class="title">近 7 天犇犇统计</text>
    <line x1="520" y1="326" x2="1060" y2="326" stroke="#dbeafe" stroke-width="2"/>
    <line x1="520" y1="267" x2="1060" y2="267" stroke="#e8f1fb" stroke-width="1"/>
    <line x1="520" y1="208" x2="1060" y2="208" stroke="#e8f1fb" stroke-width="1"/>
    <line x1="520" y1="149" x2="1060" y2="149" stroke="#e8f1fb" stroke-width="1"/>
    <path d="{path}" fill="none" stroke="url(#line)" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
    {circles}
    {labels}
    <text x="1060" y="420" text-anchor="end" class="muted">生成于 {generated_at}</text>
  </g>
</svg>'''


def _random_svg(uid: int, user: LuoguUser | None, feed: Feed | None, now: datetime) -> str:
    name = _xml(_display_name(user, uid))
    letter = _xml(_avatar_letter(user, uid))
    generated_time = _xml(_format_time_only(now))
    generated_at = _xml(_format_generated_at(now))

    if feed is None:
        quote_lines = ["暂时没有找到可展示的犇犇。"]
        feed_date = now.strftime("%Y-%m-%d")
        feed_id = "暂无 ID"
    else:
        quote_lines = _wrap_text(_strip_markdown(feed.content_md), line_chars=28, max_lines=3)
        feed_date = _to_shanghai(feed.time).strftime("%Y-%m-%d")
        feed_id = f"#{feed.id}"

    quote_svg = "\n".join(
        f'<text x="72" y="{72 + idx * 52}" class="quote">{_xml(line)}</text>'
        for idx, line in enumerate(quote_lines)
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="960" height="420" viewBox="0 0 960 420" role="img" aria-label="{name} 的随机犇犇语录图卡">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f8fbff"/><stop offset="0.56" stop-color="#eef7ff"/><stop offset="1" stop-color="#ecfdf5"/></linearGradient>
    <linearGradient id="avatar" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#38bdf8"/><stop offset="1" stop-color="#10b981"/></linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="18" stdDeviation="20" flood-color="#0f172a" flood-opacity="0.14"/></filter>
    <style>text{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif}}.quote{{fill:#102033;font-size:36px;font-weight:780}}.mark{{fill:#bfdbfe;font-size:120px;font-weight:900}}.name{{fill:#0f172a;font-size:24px;font-weight:850}}.meta{{fill:#64748b;font-size:16px;font-weight:560}}.small{{fill:#64748b;font-size:15px;font-weight:520}}</style>
  </defs>
  <rect width="960" height="420" rx="30" fill="url(#bg)"/>
  <circle cx="825" cy="80" r="132" fill="#bfdbfe" opacity="0.34"/><circle cx="118" cy="372" r="128" fill="#bbf7d0" opacity="0.32"/>
  <rect x="34" y="34" width="892" height="352" rx="28" fill="#fff" fill-opacity="0.84" stroke="#dbeafe" filter="url(#shadow)"/>
  <g transform="translate(82 82)">
    <text x="0" y="82" class="mark">“</text>
    {quote_svg}
  </g>
  <line x1="82" y1="246" x2="878" y2="246" stroke="#dbeafe" stroke-width="2"/>
  <g transform="translate(82 286)">
    <circle cx="31" cy="31" r="31" fill="url(#avatar)"/><text x="31" y="42" text-anchor="middle" fill="#fff" font-size="23" font-weight="900">{letter}</text>
    <text x="78" y="27" class="name">{name}</text><text x="78" y="54" class="meta">UID {uid}</text>
  </g>
  <g transform="translate(878 292)">
    <text x="0" y="0" text-anchor="end" class="meta">{_xml(feed_date)} · {_xml(feed_id)}</text>
    <text x="0" y="30" text-anchor="end" class="small">生成于 {generated_time}</text>
    <text x="0" y="58" text-anchor="end" class="small">由洛谷档案馆生成 · luogu.ac.cn</text>
  </g>
</svg>'''


@router.get("/activity/{uid}.svg")
async def feed_activity_card(uid: int, db: AsyncSession = Depends(get_db)) -> Response:
    cache_key = f"image:feed_activity:{uid}:v1"
    cached = await _cache_get(cache_key)
    if cached:
        return _svg_response(cached)

    now = _now_shanghai()
    since = datetime.combine((now.date() - timedelta(days=89)), time.min, tzinfo=SHANGHAI).astimezone(timezone.utc)
    user = await _load_user(db, uid)
    rows = await _load_feeds_since(db, uid, since)
    svg = _activity_svg(uid, user, _activity_stats(rows, now), now)
    await _cache_set(cache_key, svg)
    return _svg_response(svg)


@router.get("/random/{uid}.svg")
async def feed_random_card(uid: int, db: AsyncSession = Depends(get_db)) -> Response:
    cache_key = f"image:feed_random:{uid}:v1"
    cached = await _cache_get(cache_key)
    if cached:
        return _svg_response(cached)

    now = _now_shanghai()
    user = await _load_user(db, uid)
    q = (
        select(Feed)
        .where(Feed.author_uid == uid)
        .order_by(desc(Feed.time))
        .limit(50)
    )
    rows = list((await db.execute(q)).scalars().all())
    feed = random.choice(rows) if rows else None
    svg = _random_svg(uid, user, feed, now)
    await _cache_set(cache_key, svg)
    return _svg_response(svg)