"""SVG information cards generated from archived Luogu feed data."""
from __future__ import annotations

import base64
import hashlib
import html
import random
import re
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, Response
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.redis_client import get_redis
from app.models.luogu_content import Feed
from app.models.luogu_user import LuoguUser
from app.services.content_suppression import ensure_content_visible, visible_content_clause
from app.services.feed_merge import FeedDisplay, merge_feed_rows

router = APIRouter(prefix="/image/feed", tags=["image-card"])

CARD_CACHE_SECONDS = 600
AVATAR_CACHE_SECONDS = 86400
MAX_AVATAR_BYTES = 512 * 1024
ALLOWED_AVATAR_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
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



def _avatar_svg(
    user: LuoguUser | None,
    uid: int,
    *,
    cx: int,
    cy: int,
    r: int,
    clip_id: str,
    font_size: int,
    avatar_href: str | None,
) -> str:
    """Render a circular avatar. The optional image must be an embedded data URI."""
    letter = _xml(_avatar_letter(user, uid))
    image = ""
    if avatar_href:
        size = r * 2
        image = (
            f'<image href="{_xml(avatar_href)}" x="{cx - r}" y="{cy - r}" width="{size}" height="{size}" '
            f'clip-path="url(#{clip_id})" preserveAspectRatio="xMidYMid slice"/>'
        )
    return (
        f'<clipPath id="{clip_id}"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#avatar)"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{max(0, r - 6)}" fill="#fff" opacity="0.18"/>'
        f'<text x="{cx}" y="{cy + int(font_size * 0.35)}" text-anchor="middle" fill="#fff" font-size="{font_size}" font-weight="900">{letter}</text>'
        f'{image}'
    )


def _display_name(user: LuoguUser | None, uid: int) -> str:
    name = (user.name if user else "").strip()
    return name or f"UID {uid}"


def _strip_markdown(md: str, *, fallback: bool = True) -> str:
    text = md or ""
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"```[\s\S]*?```", " 代码片段 ", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    # Underscores are valid content in usernames, identifiers and code-like text.
    # Removing them as generic Markdown punctuation corrupts the quoted feed.
    text = re.sub(r"[#>*~\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or ("这条犇犇暂时没有可展示的文字。" if fallback else "")


def _wrap_text(text: str, *, line_chars: int, max_lines: int) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ["这条犇犇暂时没有可展示的文字。"]

    lines: list[str] = []
    current = ""
    current_width = 0.0

    def width_of(ch: str) -> float:
        if ch.isspace():
            return 0.35
        if ord(ch) < 128:
            if ch.isalnum() or ch in "@_:/\\":
                return 0.72
            return 0.5
        if ch in "，。！？、；：（）《》“”‘’":
            return 0.72
        return 1.08

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
    await _cache_set_ttl(key, value, CARD_CACHE_SECONDS)


async def _cache_set_ttl(key: str, value: str, ttl: int) -> None:
    try:
        await get_redis().setex(key, ttl, value)
    except Exception:
        pass


async def _avatar_data_uri(user: LuoguUser | None) -> str | None:
    avatar = (user.avatar if user else None) or ""
    if not avatar.startswith(("http://", "https://")):
        return None

    cache_key = f"image:avatar_data:{hashlib.sha256(avatar.encode('utf-8')).hexdigest()}"
    cached = await _cache_get(cache_key)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
            resp = await client.get(avatar, headers={"User-Agent": "luogu-archive/1.0"})
        if resp.status_code != 200 or len(resp.content) > MAX_AVATAR_BYTES:
            return None
        content_type = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in ALLOWED_AVATAR_TYPES:
            return None
        data = base64.b64encode(resp.content).decode("ascii")
        uri = f"data:{content_type};base64,{data}"
        await _cache_set_ttl(cache_key, uri, AVATAR_CACHE_SECONDS)
        return uri
    except Exception:
        return None


def _svg_response(svg: str, *, cache_seconds: int | None = CARD_CACHE_SECONDS) -> Response:
    if cache_seconds is None:
        headers = {
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
        }
    else:
        headers = {
            "Cache-Control": f"public, max-age={cache_seconds}",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
        }

    return Response(
        content=svg,
        media_type="image/svg+xml; charset=utf-8",
        headers=headers,
    )


async def _load_user(db: AsyncSession, uid: int) -> LuoguUser | None:
    return await db.get(LuoguUser, uid)


async def _load_feeds_since(db: AsyncSession, uid: int, since: datetime) -> list[Feed]:
    q = (
        select(Feed)
        .where(Feed.author_uid == uid, Feed.time >= since,
            visible_content_clause("feed", Feed.id, Feed.author_uid))
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


def _activity_svg(uid: int, user: LuoguUser | None, stats: dict[str, object], now: datetime, avatar_href: str | None) -> str:
    name = _xml(_display_name(user, uid))
    avatar = _avatar_svg(user, uid, cx=70, cy=70, r=70, clip_id="avatarClipLarge", font_size=48, avatar_href=avatar_href)
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
    {avatar}
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
    <text x="1060" y="400" text-anchor="end" class="muted">生成于 {generated_at}</text>
    <text x="1060" y="428" text-anchor="end" class="muted">由洛谷档案馆生成 · luogu.ac.cn</text>
  </g>
</svg>'''


def _random_svg(
    uid: int,
    user: LuoguUser | None,
    feed: Feed | None,
    now: datetime,
    avatar_href: str | None,
    display: FeedDisplay | None = None,
) -> str:
    name = _xml(_display_name(user, uid))
    avatar = _avatar_svg(user, uid, cx=31, cy=31, r=31, clip_id="avatarClipSmall", font_size=23, avatar_href=avatar_href)
    generated_time = _xml(_format_time_only(now))
    generated_at = _xml(_format_generated_at(now))

    if feed is None:
        quote_lines = [("暂时没有找到可展示的犇犇。", False)]
        feed_date = now.strftime("%Y-%m-%d")
        feed_id = "暂无 ID"
    else:
        shown_content = display.content_md if display is not None else feed.content_md
        if display is not None and display.merged_suffix_md:
            # 将自动补回部分单独换行并加下划线，图卡也能明确提示来源。
            prefix = shown_content[: -len(display.merged_suffix_md)]
            prefix_text = _strip_markdown(prefix, fallback=False)
            suffix_text = _strip_markdown(display.merged_suffix_md, fallback=False)
            prefix_lines = (
                _wrap_text(prefix_text, line_chars=20, max_lines=3)
                if prefix_text
                else []
            )
            suffix_lines = (
                _wrap_text(suffix_text, line_chars=20, max_lines=max(1, 3 - len(prefix_lines)))
                if suffix_text
                else []
            )
            quote_lines = [(line, False) for line in prefix_lines]
            quote_lines.extend((line, True) for line in suffix_lines)
            quote_lines = quote_lines[:3]
            if not quote_lines:
                quote_lines = [("这条犇犇暂时没有可展示的文字。", False)]
        else:
            quote_lines = [
                (line, False)
                for line in _wrap_text(_strip_markdown(shown_content), line_chars=20, max_lines=3)
            ]
        if display is not None and display.merged_link_md:
            # 图卡无法提供可点击链接，至少把自动补回链接所在的文字行加下划线。
            merged_labels = [
                match.group(1)
                for link in display.merged_link_md
                for match in [re.match(r"\[([^\]]+)\]\(", link)]
                if match is not None
            ]
            quote_lines = [
                (
                    line,
                    merged or any(label in line for label in merged_labels),
                )
                for line, merged in quote_lines
            ]
        feed_date = _to_shanghai(feed.time).strftime("%Y-%m-%d")
        feed_id = f"#{feed.id}"

    def quote_line_svg(line: str, merged: bool, index: int) -> str:
        decoration = (
            ' text-decoration="underline" text-decoration-color="#7db9e8"'
            if merged
            else ""
        )
        title = "<title>此内容由洛谷档案馆根据回复链自动补全</title>" if merged else ""
        return f'<text x="72" y="{72 + index * 46}" class="quote"{decoration}>{title}{_xml(line)}</text>'

    quote_svg = "\n".join(
        quote_line_svg(line, merged, index)
        for index, (line, merged) in enumerate(quote_lines)
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="960" height="420" viewBox="0 0 960 420" role="img" aria-label="{name} 的随机犇犇语录图卡">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f8fbff"/><stop offset="0.56" stop-color="#eef7ff"/><stop offset="1" stop-color="#ecfdf5"/></linearGradient>
    <linearGradient id="avatar" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#38bdf8"/><stop offset="1" stop-color="#10b981"/></linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="18" stdDeviation="20" flood-color="#0f172a" flood-opacity="0.14"/></filter>
    <style>text{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif}}.quote{{fill:#102033;font-size:31px;font-weight:780}}.mark{{fill:#bfdbfe;font-size:120px;font-weight:900}}.name{{fill:#0f172a;font-size:24px;font-weight:850}}.meta{{fill:#64748b;font-size:16px;font-weight:560}}.small{{fill:#64748b;font-size:15px;font-weight:520}}</style>
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
    {avatar}
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
    await ensure_content_visible(db, "user", str(uid))
    cache_key = f"image:feed_activity:{uid}:v3"
    cached = await _cache_get(cache_key)
    if cached:
        return _svg_response(cached)

    now = _now_shanghai()
    since = datetime.combine((now.date() - timedelta(days=89)), time.min, tzinfo=SHANGHAI).astimezone(timezone.utc)
    user = await _load_user(db, uid)
    rows = await _load_feeds_since(db, uid, since)
    avatar_href = await _avatar_data_uri(user)
    svg = _activity_svg(uid, user, _activity_stats(rows, now), now, avatar_href)
    await _cache_set(cache_key, svg)
    return _svg_response(svg)


@router.get("/random/{uid}.svg")
async def feed_random_card(uid: int, db: AsyncSession = Depends(get_db)) -> Response:
    # 随机语录每次访问都重新抽取；这里不能走 Redis / 浏览器缓存。
    await ensure_content_visible(db, "user", str(uid))
    now = _now_shanghai()
    user = await _load_user(db, uid)
    q = (
        select(Feed)
        .where(Feed.author_uid == uid,
            visible_content_clause("feed", Feed.id, Feed.author_uid))
        .order_by(desc(Feed.time))
        .limit(50)
    )
    rows = list((await db.execute(q)).scalars().all())
    feed = random.choice(rows) if rows else None
    merged = await merge_feed_rows(db, rows)
    avatar_href = await _avatar_data_uri(user)
    display = merged.get(int(feed.id)) if feed is not None else None
    svg = _random_svg(uid, user, feed, now, avatar_href, display)
    return _svg_response(svg, cache_seconds=None)
