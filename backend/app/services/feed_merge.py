"""在展示层递归补全犇犇回复中被截断的正文与链接。

洛谷回复会复制被回复犇犇的可见文字，但可能丢失 Markdown 链接或截断尾部。
本模块只生成展示内容，不修改数据库中的原始归档。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models._common import utcnow
from app.models.luogu_content import Feed, FeedCompletion
from app.models.luogu_user import LuoguUser, UserNameVersion


@dataclass(frozen=True)
class FeedDisplay:
    """一条犇犇最终用于展示的正文和补全来源。"""

    content_md: str
    merged_suffix_md: str | None = None
    merged_from_id: int | None = None
    merged_link_md: tuple[str, ...] = ()
    merged_image_md: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplyReference:
    """回复末尾的对象标记和被引用正文。"""

    name: str | None
    uid: int | None
    quoted_prefix: str
    quoted_start: int
    quoted_end: int


@dataclass(frozen=True)
class MarkdownMedia:
    """Markdown 链接或图片及其在可见文字中的范围。"""

    plain_start: int
    plain_end: int
    raw: str
    kind: str
    raw_start: int
    raw_end: int


_REPLY_PATTERN = re.compile(
    r"(?<!\S)\|\|\s*@?"
    r"(?:\[([^\]]{1,128})\]\(/user/(\d+)\)|([^\s:]{1,128}))"
    r"\s*:\s*([\s\S]+)$"
)
_MARKDOWN_MEDIA_PATTERN = re.compile(
    r"(!?)\[([^\]\n]*)\]\(([^)\s]+)(?:\s+[^)]*)?\)"
)
_SOURCE_WINDOW = timedelta(days=3)
_COMPLETED_CACHE_TTL = timedelta(days=1)
_EMPTY_CACHE_TTL = timedelta(hours=1)
_ALGORITHM_VERSION = 2


def _normalize_content(value: str | None) -> str:
    """统一换行符，避免不同平台的换行导致匹配失败。"""

    return (value or "").replace("\r\n", "\n").replace("\r", "\n")


def parse_reply_reference(content_md: str) -> ReplyReference | None:
    """只解析带明确回复对象的 ``|| 用户名: 正文`` 结构。"""

    normalized = _normalize_content(content_md)
    match = _REPLY_PATTERN.search(normalized)
    if match is None:
        return None

    markdown_name, markdown_uid, plain_name, quoted = match.groups()
    name = markdown_name or plain_name or ""
    quoted_prefix = _normalize_content(quoted).strip()
    if not name or not quoted_prefix:
        return None
    return ReplyReference(
        name=name,
        uid=int(markdown_uid) if markdown_uid else None,
        quoted_prefix=quoted_prefix,
        quoted_start=match.start(4),
        quoted_end=match.end(4),
    )


def _plain_text_and_media(content_md: str) -> tuple[str, list[MarkdownMedia]]:
    """链接保留标题，图片视为零宽度内容，并记录它们原本的位置。"""

    parts: list[str] = []
    media: list[MarkdownMedia] = []
    cursor = 0
    plain_length = 0
    for match in _MARKDOWN_MEDIA_PATTERN.finditer(content_md):
        normal = content_md[cursor:match.start()]
        parts.append(normal)
        plain_length += len(normal)

        is_image = match.group(1) == "!"
        label = match.group(2)
        visible_label = "" if is_image else label
        parts.append(visible_label)
        media.append(
            MarkdownMedia(
                plain_start=plain_length,
                plain_end=plain_length + len(visible_label),
                raw=match.group(0),
                kind="image" if is_image else "link",
                raw_start=match.start(),
                raw_end=match.end(),
            )
        )
        plain_length += len(visible_label)
        cursor = match.end()

    parts.append(content_md[cursor:])
    return "".join(parts), media


def _plain_boundaries(content_md: str) -> list[int]:
    """把每个可见文字边界映射回完整 Markdown 的字符边界。"""

    boundaries = [0]
    cursor = 0
    for match in _MARKDOWN_MEDIA_PATTERN.finditer(content_md):
        for raw_index in range(cursor, match.start()):
            boundaries.append(raw_index + 1)

        if match.group(1) == "!":
            # 图片没有可见文字；同一个可见边界直接跨过整段图片 Markdown。
            boundaries[-1] = match.end()
            cursor = match.end()
            continue

        # 链接标题中间的边界落在 ``[标题]`` 内，末尾必须跨过完整链接语法。
        label_length = len(match.group(2))
        for label_index in range(1, label_length + 1):
            boundaries.append(match.start() + 1 + label_index)
        boundaries[-1] = match.end()
        cursor = match.end()

    for raw_index in range(cursor, len(content_md)):
        boundaries.append(raw_index + 1)
    return boundaries


def _collapse_plain_whitespace(value: str) -> tuple[str, list[int]]:
    """折叠可见文字中的连续空白，并保留折叠后边界到原文字的映射。"""

    collapsed: list[str] = []
    boundaries = [0]
    index = 0
    while index < len(value):
        if value[index].isspace():
            end = index + 1
            while end < len(value) and value[end].isspace():
                end += 1
            collapsed.append(" ")
            boundaries.append(end)
            index = end
            continue
        collapsed.append(value[index])
        index += 1
        boundaries.append(index)
    return "".join(collapsed), boundaries


def _collapsed_position(value: str, plain_position: int) -> int:
    """返回普通文字边界在折叠空白后的字符位置。"""

    collapsed, _ = _collapse_plain_whitespace(value[:plain_position])
    return len(collapsed)


def _timestamp(value: datetime) -> float:
    """把数据库时间统一为可比较的 UTC 时间戳。"""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _is_earlier(source: Feed, reply: Feed) -> bool:
    """补全来源必须更早，且与当前回复相隔不超过三天。"""

    source_key = (_timestamp(source.time), int(source.id))
    reply_key = (_timestamp(reply.time), int(reply.id))
    age_seconds = reply_key[0] - source_key[0]
    return source_key < reply_key and age_seconds <= _SOURCE_WINDOW.total_seconds()


def _merge_source_display(
    reply: Feed,
    source: Feed,
    source_display: FeedDisplay,
    reference: ReplyReference,
) -> FeedDisplay | None:
    """把已递归补全的来源正文嵌入当前回复，并保留真实 Markdown 链接。"""

    reply_content = _normalize_content(reply.content_md)
    source_content = _normalize_content(source_display.content_md)
    quote_content = reply_content[reference.quoted_start:reference.quoted_end]
    source_plain, source_media = _plain_text_and_media(source_content)
    quote_plain, quote_media = _plain_text_and_media(quote_content)
    source_match = source_plain
    quote_match = quote_plain
    source_match_boundaries = list(range(len(source_plain) + 1))
    quote_match_boundaries = list(range(len(quote_plain) + 1))
    collapse_whitespace = False
    if not source_match.startswith(quote_match):
        # 图片被回复系统移除时，其前后空白可能合并；仅在来源确实含图片时放宽空白比较。
        if not any(item.kind == "image" for item in source_media):
            return None
        source_match, source_match_boundaries = _collapse_plain_whitespace(source_plain)
        quote_match, quote_match_boundaries = _collapse_plain_whitespace(quote_plain)
        if not source_match.startswith(quote_match):
            return None

        collapse_whitespace = True

    def media_range(item: MarkdownMedia, plain: str) -> tuple[int, int]:
        if not collapse_whitespace:
            return item.plain_start, item.plain_end
        return (
            _collapsed_position(plain, item.plain_start),
            _collapsed_position(plain, item.plain_end),
        )

    existing_link_ranges = {
        media_range(item, quote_plain)
        for item in quote_media
        if item.kind == "link"
    }
    existing_image_counts: dict[int, int] = {}
    for item in quote_media:
        if item.kind == "image":
            image_position, _ = media_range(item, quote_plain)
            existing_image_counts[image_position] = (
                existing_image_counts.get(image_position, 0) + 1
            )
    quote_markdown_boundaries = _plain_boundaries(quote_content)
    insertions: list[tuple[int, int, int, str, str, str]] = []
    for source_order, item in enumerate(source_media):
        item_start, item_end = media_range(item, source_plain)
        if item_end > len(quote_match):
            continue
        if item.kind == "link":
            if (item_start, item_end) in existing_link_ranges:
                continue
        else:
            remaining = existing_image_counts.get(item_start, 0)
            if remaining:
                existing_image_counts[item_start] = remaining - 1
                continue
        quote_plain_start = quote_match_boundaries[item_start]
        quote_plain_end = quote_match_boundaries[item_end]
        inserted_raw = item.raw
        if collapse_whitespace and item.kind == "image":
            # 空白折叠后若图片右侧分隔符消失，把来源中的原始分隔符一并补回。
            trailing_end = item.raw_end
            while (
                trailing_end < len(source_content)
                and source_content[trailing_end].isspace()
            ):
                trailing_end += 1
            quote_raw_position = quote_markdown_boundaries[quote_plain_start]
            quote_has_separator = (
                quote_raw_position < len(quote_content)
                and quote_content[quote_raw_position].isspace()
            )
            if trailing_end > item.raw_end and not quote_has_separator:
                inserted_raw += source_content[item.raw_end:trailing_end]

        insertions.append(
            (
                quote_markdown_boundaries[quote_plain_start],
                quote_markdown_boundaries[quote_plain_end],
                source_order,
                inserted_raw,
                item.kind,
                item.raw,
            )
        )

    merged_quote = quote_content
    for raw_start, raw_end, _, raw_media, _, _ in sorted(insertions, reverse=True):
        merged_quote = merged_quote[:raw_start] + raw_media + merged_quote[raw_end:]

    source_markdown_boundaries = _plain_boundaries(source_content)
    source_plain_cutoff = source_match_boundaries[len(quote_match)]
    suffix = source_content[source_markdown_boundaries[source_plain_cutoff]:]
    if not insertions and not suffix:
        return None

    return FeedDisplay(
        content_md=(
            reply_content[:reference.quoted_start]
            + merged_quote
            + reply_content[reference.quoted_end:]
            + suffix
        ),
        merged_suffix_md=suffix or None,
        merged_from_id=int(source.id),
        merged_link_md=tuple(
            original_raw
            for _, _, _, _, kind, original_raw in insertions
            if kind == "link"
        ),
        merged_image_md=tuple(
            original_raw
            for _, _, _, _, kind, original_raw in insertions
            if kind == "image"
        ),
    )


async def merge_feed_rows(
    db: AsyncSession,
    rows: Sequence[Feed],
) -> dict[int, FeedDisplay]:
    """递归补全一批犇犇，并把结果持久化到 MySQL。"""

    if not rows:
        return {}

    display_cache: dict[int, FeedDisplay] = {}
    resolving: set[int] = set()
    name_uid_cache: dict[str, set[int]] = {}
    history_cache: dict[tuple[int, int], list[Feed]] = {}
    exact_cache: dict[tuple[int, str, int], list[Feed]] = {}
    persistent_cache: dict[int, FeedCompletion | None] = {}
    pending_cache: dict[int, dict] = {}

    initial_ids = [int(row.id) for row in rows]
    cached_rows = (
        await db.execute(
            select(FeedCompletion).where(FeedCompletion.feed_id.in_(initial_ids))
        )
    ).scalars().all()
    persistent_cache.update({int(item.feed_id): item for item in cached_rows})

    def cached_display(item: FeedCompletion) -> FeedDisplay | None:
        """只复用当前算法版本且仍在有效期内的 MySQL 结果。"""

        if int(item.algorithm_version) != _ALGORITHM_VERSION:
            return None
        ttl = _COMPLETED_CACHE_TTL if item.is_completed else _EMPTY_CACHE_TTL
        if _timestamp(utcnow()) - _timestamp(item.computed_at) > ttl.total_seconds():
            return None
        return FeedDisplay(
            content_md=item.content_md,
            merged_suffix_md=item.merged_suffix_md,
            merged_from_id=int(item.merged_from_id) if item.merged_from_id else None,
            merged_link_md=tuple(item.merged_link_md or []),
            merged_image_md=tuple(item.merged_image_md or []),
        )

    async def load_persistent(row_id: int) -> FeedDisplay | None:
        if row_id not in persistent_cache:
            persistent_cache[row_id] = await db.get(FeedCompletion, row_id)
        item = persistent_cache[row_id]
        return cached_display(item) if item is not None else None

    def remember(row_id: int, display: FeedDisplay) -> FeedDisplay:
        """登记本次计算结果，函数结束时批量写入，避免递归中频繁提交。"""

        display_cache[row_id] = display
        is_completed = bool(
            display.merged_suffix_md
            or display.merged_link_md
            or display.merged_image_md
        )
        pending_cache[row_id] = {
            "feed_id": row_id,
            "content_md": display.content_md,
            "merged_suffix_md": display.merged_suffix_md,
            "merged_from_id": display.merged_from_id,
            "merged_link_md": list(display.merged_link_md),
            "merged_image_md": list(display.merged_image_md),
            "is_completed": is_completed,
            "algorithm_version": _ALGORITHM_VERSION,
            "computed_at": utcnow(),
        }
        return display

    async def resolve_uids(reference: ReplyReference) -> set[int]:
        if reference.uid is not None:
            return {reference.uid}
        name = reference.name or ""
        if name in name_uid_cache:
            return name_uid_cache[name]

        uids: set[int] = set()
        users = (
            await db.execute(select(LuoguUser).where(LuoguUser.name == name))
        ).scalars().all()
        uids.update(int(user.uid) for user in users)
        versions = (
            await db.execute(select(UserNameVersion).where(UserNameVersion.name == name))
        ).scalars().all()
        uids.update(int(version.uid) for version in versions)
        name_uid_cache[name] = uids
        return uids

    async def load_history(uid: int, reply: Feed) -> list[Feed]:
        cache_key = (uid, int(reply.id))
        if cache_key not in history_cache:
            loaded = (
                await db.execute(
                    select(Feed)
                    .where(
                        Feed.author_uid == uid,
                        Feed.time >= reply.time - _SOURCE_WINDOW,
                        or_(
                            Feed.time < reply.time,
                            and_(Feed.time == reply.time, Feed.id < reply.id),
                        ),
                    )
                    .order_by(Feed.time.desc(), Feed.id.desc())
                )
            ).scalars().all()
            history_cache[cache_key] = list(loaded)
        return history_cache[cache_key]

    async def load_exact(uid: int, reference: ReplyReference, reply: Feed) -> list[Feed]:
        """先让数据库按原始前缀筛选，绝大多数普通补尾无需扫描用户历史。"""

        cache_key = (uid, reference.quoted_prefix, int(reply.id))
        if cache_key not in exact_cache:
            loaded = (
                await db.execute(
                    select(Feed)
                    .where(
                        Feed.author_uid == uid,
                        Feed.content_md.startswith(reference.quoted_prefix),
                        Feed.time >= reply.time - _SOURCE_WINDOW,
                        or_(
                            Feed.time < reply.time,
                            and_(Feed.time == reply.time, Feed.id < reply.id),
                        ),
                    )
                    .order_by(Feed.time.desc(), Feed.id.desc())
                )
            ).scalars().all()
            exact_cache[cache_key] = list(loaded)
        return exact_cache[cache_key]

    async def resolve(row: Feed) -> FeedDisplay:
        row_id = int(row.id)
        if row_id in display_cache:
            return display_cache[row_id]

        original = FeedDisplay(content_md=_normalize_content(row.content_md))
        if row_id in resolving:
            return original

        persisted = await load_persistent(row_id)
        if persisted is not None:
            display_cache[row_id] = persisted
            return persisted

        reference = parse_reply_reference(row.content_md)
        if reference is None:
            display_cache[row_id] = original
            return original

        uids = await resolve_uids(reference)
        if not uids:
            return remember(row_id, original)

        resolving.add(row_id)
        try:
            exact_candidates: list[Feed] = []
            for uid in uids:
                exact_candidates.extend(await load_exact(uid, reference, row))

            async def try_candidates(candidates: list[Feed]) -> FeedDisplay | None:
                """按发布时间从近到远尝试，命中后立即停止继续追链。"""

                candidates = [
                    source
                    for source in candidates
                    if int(source.id) != row_id and _is_earlier(source, row)
                ]
                candidates.sort(
                    key=lambda source: (_timestamp(source.time), int(source.id)),
                    reverse=True,
                )
                quote_plain, _ = _plain_text_and_media(reference.quoted_prefix)
                seen: set[int] = set()
                for source in candidates:
                    source_id = int(source.id)
                    if source_id in seen:
                        continue
                    seen.add(source_id)
                    # 递归只会补长正文；两边至少一边是另一边的前缀才可能最终匹配。
                    raw_plain, raw_media = _plain_text_and_media(
                        _normalize_content(source.content_md)
                    )
                    compatible = (
                        raw_plain.startswith(quote_plain)
                        or quote_plain.startswith(raw_plain)
                    )
                    if not compatible and any(
                        item.kind == "image" for item in raw_media
                    ):
                        collapsed_raw, _ = _collapse_plain_whitespace(raw_plain)
                        collapsed_quote, _ = _collapse_plain_whitespace(quote_plain)
                        compatible = (
                            collapsed_raw.startswith(collapsed_quote)
                            or collapsed_quote.startswith(collapsed_raw)
                        )
                    if not compatible:
                        continue
                    source_display = await resolve(source)
                    merged = _merge_source_display(row, source, source_display, reference)
                    if merged is not None:
                        return merged
                return None

            merged = await try_candidates(exact_candidates)
            if merged is not None:
                return remember(row_id, merged)

            # 链接语法已经丢失时无法用原始 Markdown 前缀筛选，才回退到用户历史。
            history_candidates: list[Feed] = []
            for uid in uids:
                history_candidates.extend(await load_history(uid, row))
            history_candidates = [
                source
                for source in history_candidates
                if int(source.id) != row_id and _is_earlier(source, row)
            ]
            merged = await try_candidates(history_candidates)
            if merged is not None:
                return remember(row_id, merged)
        finally:
            resolving.discard(row_id)

        return remember(row_id, original)

    for row in rows:
        await resolve(row)

    if pending_cache:
        # MySQL upsert 处理多个请求同时首次计算同一条犇犇的竞争情况。
        statement = mysql_insert(FeedCompletion).values(list(pending_cache.values()))
        statement = statement.on_duplicate_key_update(
            content_md=statement.inserted.content_md,
            merged_suffix_md=statement.inserted.merged_suffix_md,
            merged_from_id=statement.inserted.merged_from_id,
            merged_link_md=statement.inserted.merged_link_md,
            merged_image_md=statement.inserted.merged_image_md,
            is_completed=statement.inserted.is_completed,
            algorithm_version=statement.inserted.algorithm_version,
            computed_at=statement.inserted.computed_at,
        )
        await db.execute(statement)
        await db.commit()
    return {int(row.id): display_cache[int(row.id)] for row in rows}
