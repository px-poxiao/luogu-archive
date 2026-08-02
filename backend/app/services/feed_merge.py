"""犇犇回复的缺失后缀补全。

洛谷的回复文本会把被回复犇犇的一部分复制到正文里，但复制内容可能只包含
纯文字前缀，原犇犇后面的图片 Markdown、链接或后续文字就不会出现在回复中。
本模块只在展示层临时补全，不修改 ``feeds`` 表里的原始归档。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.luogu_content import Feed
from app.models.luogu_user import LuoguUser, UserNameVersion


@dataclass(frozen=True)
class FeedDisplay:
    """一条犇犇的展示正文和可视化补全信息。"""

    content_md: str
    merged_suffix_md: str | None = None
    merged_from_id: int | None = None
    merged_link_md: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplyReference:
    """从回复文本里解析出的被引用用户名和正文前缀。"""

    name: str | None
    uid: int | None
    quoted_prefix: str
    quoted_start: int
    quoted_end: int


@dataclass(frozen=True)
class MarkdownLink:
    """原文中的 Markdown 链接及其在可见文本中的范围。"""

    plain_start: int
    plain_end: int
    raw: str


# 同时支持复制按钮生成的纯文本用户标记和洛谷 Markdown 提及格式。
# 回复标记可以出现在一行开头，也可以出现在回复者自己的文字之后。
_REPLY_PATTERN = re.compile(
    r"(?<!\S)\|\|\s*@?"
    r"(?:\[([^\]]{1,128})\]\(/user/(\d+)\)|([^\s:]{1,128}))"
    r"\s*:\s*([\s\S]+)$"
)
_MARKDOWN_LINK_PATTERN = re.compile(
    r"(?<!\!)\[([^\]\n]*)\]\(([^)\s]+)(?:\s+[^)]*)?\)"
)


def _normalize_content(value: str | None) -> str:
    """统一换行符，避免 Windows 换行导致前缀匹配失效。"""

    return (value or "").replace("\r\n", "\n").replace("\r", "\n")


def parse_reply_reference(content_md: str) -> ReplyReference | None:
    """解析一条犇犇中的回复引用。

    只识别带回复对象标记的 ``|| 用户名 : 内容`` 结构；内容或对象标记为空时不补全。
    """

    normalized = _normalize_content(content_md)
    match = _REPLY_PATTERN.search(normalized)
    if match is None:
        return None

    markdown_name, markdown_uid, plain_name, quoted = match.groups()
    name = markdown_name or plain_name or ""
    uid = int(markdown_uid) if markdown_uid else None

    quoted_prefix = _normalize_content(quoted).strip()
    if not name or not quoted_prefix:
        return None
    return ReplyReference(
        name=name,
        uid=uid,
        quoted_prefix=quoted_prefix,
        quoted_start=match.start(4),
        quoted_end=match.end(4),
    )


def _plain_text_and_links(content_md: str) -> tuple[str, list[MarkdownLink]]:
    """去掉普通 Markdown 链接语法，但保留链接标题和位置。"""

    parts: list[str] = []
    links: list[MarkdownLink] = []
    cursor = 0
    plain_length = 0
    for match in _MARKDOWN_LINK_PATTERN.finditer(content_md):
        normal = content_md[cursor:match.start()]
        parts.append(normal)
        plain_length += len(normal)

        label = match.group(1)
        parts.append(label)
        links.append(
            MarkdownLink(
                plain_start=plain_length,
                plain_end=plain_length + len(label),
                raw=match.group(0),
            )
        )
        plain_length += len(label)
        cursor = match.end()

    tail = content_md[cursor:]
    parts.append(tail)
    return "".join(parts), links


def _plain_boundaries(content_md: str) -> list[int]:
    """返回每个可见字符边界对应的原始 Markdown 下标。"""

    boundaries = [0]
    cursor = 0
    for match in _MARKDOWN_LINK_PATTERN.finditer(content_md):
        for raw_index in range(cursor, match.start()):
            boundaries.append(raw_index + 1)
        for label_index in range(1, len(match.group(1)) + 1):
            boundaries.append(match.start() + label_index)
        cursor = match.end()

    for raw_index in range(cursor, len(content_md)):
        boundaries.append(raw_index + 1)
    return boundaries


def _timestamp(value: datetime) -> float:
    """把数据库可能返回的 naive UTC 时间统一成可比较的时间戳。"""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _append_suffix(reply: Feed, source: Feed, prefix: str) -> FeedDisplay | None:
    """若 source 正好以前缀开头，则返回带补全后缀的展示对象。"""

    source_content = _normalize_content(source.content_md)
    if not source_content.startswith(prefix):
        return None
    suffix = source_content[len(prefix):]
    if not suffix:
        return None
    # 只在回复正文原样追加；suffix 自身保留换行，图片 Markdown 仍能正常解析。
    return FeedDisplay(
        content_md=_normalize_content(reply.content_md) + suffix,
        merged_suffix_md=suffix,
        merged_from_id=int(source.id),
    )


def _merge_missing_links(
    reply: Feed,
    source: Feed,
    reference: ReplyReference,
) -> FeedDisplay | None:
    """在可见文字相同的前提下，把原文中缺失的链接补回回复引用。"""

    reply_content = _normalize_content(reply.content_md)
    source_content = _normalize_content(source.content_md)
    quote_content = reply_content[reference.quoted_start:reference.quoted_end]

    source_plain, source_links = _plain_text_and_links(source_content)
    quote_plain, quote_links = _plain_text_and_links(quote_content)
    if source_plain != quote_plain or not source_links:
        return None

    existing_ranges = {
        (link.plain_start, link.plain_end)
        for link in quote_links
    }
    boundaries = _plain_boundaries(quote_content)
    insertions: list[tuple[int, int, str]] = []
    for link in source_links:
        if link.plain_end > len(quote_plain):
            continue
        if (link.plain_start, link.plain_end) in existing_ranges:
            continue
        raw_start = boundaries[link.plain_start]
        raw_end = boundaries[link.plain_end]
        insertions.append((raw_start, raw_end, link.raw))

    if not insertions:
        return None

    merged_quote = quote_content
    for raw_start, raw_end, raw_link in sorted(insertions, reverse=True):
        merged_quote = (
            merged_quote[:raw_start]
            + raw_link
            + merged_quote[raw_end:]
        )

    return FeedDisplay(
        content_md=(
            reply_content[:reference.quoted_start]
            + merged_quote
            + reply_content[reference.quoted_end:]
        ),
        merged_from_id=int(source.id),
        merged_link_md=tuple(raw_link for _, _, raw_link in insertions),
    )


async def merge_feed_rows(
    db: AsyncSession,
    rows: Sequence[Feed],
) -> dict[int, FeedDisplay]:
    """为一批即将展示的犇犇寻找可严格匹配的原文后缀。

    查询会补充当前分页之外的候选原文，因此“回复在首页、原文在更早分页”时也能
    正常工作。候选只允许来自回复时间之前的同一用户，且正文必须以前缀逐字开头。
    """

    result = {
        int(row.id): FeedDisplay(content_md=_normalize_content(row.content_md))
        for row in rows
    }
    if not rows:
        return result

    references: list[tuple[Feed, ReplyReference]] = []
    for row in rows:
        reference = parse_reply_reference(row.content_md)
        if reference is not None:
            references.append((row, reference))
    if not references:
        return result

    names = {
        reference.name
        for _, reference in references
        if reference.uid is None and reference.name is not None
    }
    name_to_uids: dict[str, set[int]] = {}
    if names:
        current_users = (
            await db.execute(select(LuoguUser).where(LuoguUser.name.in_(names)))
        ).scalars().all()
        for user in current_users:
            name_to_uids.setdefault(user.name, set()).add(int(user.uid))

        # 回复可能引用的是用户旧昵称；历史昵称也属于“用户名相同”的严格匹配。
        old_names = (
            await db.execute(
                select(UserNameVersion).where(UserNameVersion.name.in_(names))
            )
        ).scalars().all()
        for version in old_names:
            name_to_uids.setdefault(version.name, set()).add(int(version.uid))

    reference_uids: dict[int, set[int]] = {}
    for row, reference in references:
        if reference.uid is not None:
            reference_uids[int(row.id)] = {reference.uid}
        else:
            reference_uids[int(row.id)] = name_to_uids.get(reference.name, set())

    # 用 startswith 先在数据库过滤候选，避免把某个活跃用户的全部历史加载进内存。
    conditions = []
    for row, reference in references:
        uids = reference_uids[int(row.id)]
        for uid in uids:
            conditions.append(
                and_(
                    Feed.author_uid == uid,
                    Feed.content_md.startswith(reference.quoted_prefix),
                )
            )
    if not conditions:
        return result

    current_ids = [int(row.id) for row in rows]
    candidate_query = select(Feed).where(
        or_(*conditions),
        Feed.id.not_in(current_ids),
    )
    candidates = (await db.execute(candidate_query)).scalars().all()
    candidates_by_uid: dict[int, list[Feed]] = {}
    candidate_ids: set[int] = set()

    def add_candidates(items: Sequence[Feed]) -> None:
        """加入候选原文并按犇犇 ID 去重。"""

        for candidate in items:
            candidate_id = int(candidate.id)
            if candidate_id in candidate_ids:
                continue
            candidate_ids.add(candidate_id)
            candidates_by_uid.setdefault(int(candidate.author_uid or 0), []).append(candidate)

    for candidate in candidates:
        add_candidates([candidate])
    for row in rows:
        add_candidates([row])

    unresolved: list[tuple[Feed, ReplyReference]] = []
    for reply, reference in references:
        possible_uids = reference_uids[int(reply.id)]
        possible_sources = [
            source
            for uid in possible_uids
            for source in candidates_by_uid.get(uid, [])
            if int(source.id) != int(reply.id)
            and (
                _timestamp(source.time) < _timestamp(reply.time)
                or (
                    _timestamp(source.time) == _timestamp(reply.time)
                    and int(source.id) < int(reply.id)
                )
            )
        ]
        possible_sources.sort(
            key=lambda source: (_timestamp(source.time), int(source.id)),
            reverse=True,
        )
        for source in possible_sources:
            display = _append_suffix(reply, source, reference.quoted_prefix)
            if display is not None:
                result[int(reply.id)] = display
                break
        else:
            unresolved.append((reply, reference))

    # 原文含链接、回复只保留链接标题时，原始 Markdown 无法用 startswith 过滤。
    # 仅对前一步未命中的用户拉取候选，避免普通分页额外扫描所有历史犇犇。
    fallback_uids = {
        uid
        for reply, _ in unresolved
        for uid in reference_uids[int(reply.id)]
    }
    if fallback_uids:
        latest_reply = max(unresolved, key=lambda item: _timestamp(item[0].time))[0]
        fallback_query = select(Feed).where(
            Feed.author_uid.in_(fallback_uids),
            Feed.id.not_in(current_ids),
            Feed.time <= latest_reply.time,
        )
        add_candidates((await db.execute(fallback_query)).scalars().all())

    for reply, reference in unresolved:
        possible_uids = reference_uids[int(reply.id)]
        possible_sources = [
            source
            for uid in possible_uids
            for source in candidates_by_uid.get(uid, [])
            if int(source.id) != int(reply.id)
            and (
                _timestamp(source.time) < _timestamp(reply.time)
                or (
                    _timestamp(source.time) == _timestamp(reply.time)
                    and int(source.id) < int(reply.id)
                )
            )
        ]
        possible_sources.sort(
            key=lambda source: (_timestamp(source.time), int(source.id)),
            reverse=True,
        )
        for source in possible_sources:
            display = _merge_missing_links(reply, source, reference)
            if display is not None:
                result[int(reply.id)] = display
                break

    return result
