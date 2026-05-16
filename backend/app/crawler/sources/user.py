"""用户主页爬虫。

从 `https://<base>/user/<uid>` 取 HTML，提取 lentille-context 里的 data.user
+ data.prizes + data.elo + data.gu + data.dailyCounts 全字段入库。

实现要点：
- 不需要登录
- 判重：introduction 走版本化；name 走 name_versions；数值字段走时间序列
- 用户名违规检测：
  1) 系统格式正则（_user_\d+ / 违规用户名\d+）
  2) 匹配即写 user_name_violation → 隐藏 triggered_at 之前所有 name_versions
"""
from __future__ import annotations

import re
import time as _t
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import db_session
from app.core.exceptions import CrawlerError
from app.core.logging import get_logger
from app.core.redis_client import get_redis
from app.crawler.http import fetch_anon
from app.crawler.lentille import data_from_lentille
from app.crawler.nodes import NodeKind, get_default_node
from app.crawler.sources.base import (
    record_task_done,
    record_task_start,
    sha256_hex,
    task_lock,
    trigger_from,
)
from app.models._common import (
    CrawlTaskStatus,
    LuoguColor,
    NameViolationSource,
    utcnow,
)
from app.models.luogu_user import (
    LuoguUser,
    UserDailyActivity,
    UserEloHistory,
    UserGuHistory,
    UserIntroVersion,
    UserNameVersion,
    UserNameViolation,
    UserNumericSnapshot,
    UserPrize,
)

log = get_logger(__name__)

# 用户名违规的系统默认格式
_VIOLATION_NAME_PATS: list[re.Pattern[str]] = [
    re.compile(r"^_user_\d+$"),
    re.compile(r"^违规用户名\d+$"),
]


async def _enqueue_user_cascades(uid: int) -> None:
    """用户保存按钮 / 首次入库时附带派发：
       1) 当前用户犇犇第一页爬取（带 Cookie）
       2) 库里已记录的、属于该用户的全部文章 + 剪贴板，错峰派发
    """
    from app.models.luogu_content import Article, Paste
    from app.tasks.actors.crawl import (
        crawl_article,
        crawl_paste,
        crawl_user_feeds,
    )

    # 限速参数：避免一次性投出几十条任务把节点打 403/429 → 熔断
    PER_TASK_DELAY_MS = 2000      # 任务之间相隔 2 秒
    MAX_TASKS_PER_TYPE = 30       # 文章 + 剪贴板各最多派 30 条；超量留给下一次保存按钮

    try:
        crawl_user_feeds.send(uid, 1, "cascaded_from_user")
    except Exception as e:
        log.warning("crawl_user.cascade_feed_failed", uid=uid, error=str(e))

    try:
        async with db_session() as session:
            arts = (await session.execute(
                select(Article.article_id).where(Article.author_uid == uid)
                .limit(MAX_TASKS_PER_TYPE)
            )).scalars().all()
            pastes = (await session.execute(
                select(Paste.paste_id).where(Paste.author_uid == uid)
                .limit(MAX_TASKS_PER_TYPE)
            )).scalars().all()
        for i, aid in enumerate(arts):
            try:
                # delay 单位毫秒；让任务在未来错峰执行
                crawl_article.send_with_options(
                    args=(aid, "cascaded_from_user"),
                    delay=i * PER_TASK_DELAY_MS,
                )
            except Exception as e:
                log.warning("crawl_user.cascade_article_failed", aid=aid, error=str(e))
        for i, pid in enumerate(pastes):
            try:
                crawl_paste.send_with_options(
                    args=(pid, "cascaded_from_user"),
                    # 把剪贴板排在文章之后，整体错峰串行
                    delay=(len(arts) + i) * PER_TASK_DELAY_MS,
                )
            except Exception as e:
                log.warning("crawl_user.cascade_paste_failed", pid=pid, error=str(e))
        log.info(
            "crawl_user.cascade_dispatched",
            uid=uid,
            articles=len(arts),
            pastes=len(pastes),
            interval_ms=PER_TASK_DELAY_MS,
        )
    except Exception as e:
        log.warning("crawl_user.cascade_query_failed", uid=uid, error=str(e))


def _is_violation_name(name: str) -> bool:
    return any(p.match(name) for p in _VIOLATION_NAME_PATS)


def _to_color(value: str | None) -> LuoguColor:
    if not value:
        return LuoguColor.Gray
    try:
        return LuoguColor(value)
    except ValueError:
        log.warning("user.unknown_color", color=value)
        return LuoguColor.Gray


def _to_dt(unix_sec: int | float | None) -> datetime | None:
    if not unix_sec:
        return None
    return datetime.fromtimestamp(int(unix_sec), tz=timezone.utc)


async def crawl_one(uid: int, *, trigger: str = "scheduled") -> None:
    """爬取一个用户的主页。"""
    async with task_lock("user", str(uid)) as got:
        if not got:
            log.info("crawl_user.skip_locked", uid=uid)
            return
        await _crawl_one_inner(uid, trigger=trigger)


async def _crawl_one_inner(uid: int, *, trigger: str) -> None:
    node = get_default_node(NodeKind.ANON)
    redis = get_redis()
    url_path = f"/user/{uid}"
    task_id = await record_task_start(
        "user", url_path, trigger=trigger_from(trigger), node_id=node.node_id
    )

    # 进入 fetch 前先看一下用户是否已入库 —— 用于决定是否级联派 feed
    async with db_session() as session:
        was_first_time = (await session.get(LuoguUser, uid)) is None

    start = _t.monotonic()
    try:
        result = await fetch_anon(url_path, node=node, redis=redis)
        if result.data is None:
            raise CrawlerError("用户页无 lentille-context")
        data = data_from_lentille(result.data)
        user_obj = data.get("user")
        if not isinstance(user_obj, dict):
            raise CrawlerError(f"用户页缺少 data.user: uid={uid}")

        async with db_session() as session:
            await _upsert_user(session, uid, user_obj, data)
            await session.commit()

        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.success,
            http_status=result.status,
            duration_ms=dur,
        )

        # 级联派发 feed/article/paste 的两个时机：
        #   1. trigger=manual：用户显式点保存
        #   2. was_first_time：陌生用户首次入库（passive 触发也算）
        # 已收录用户的纯定时/被动刷新不级联，保护 cookie 池。
        if trigger == "manual" or was_first_time:
            await _enqueue_user_cascades(uid)
    except Exception as e:
        dur = int((_t.monotonic() - start) * 1000)
        await record_task_done(
            task_id,
            status=CrawlTaskStatus.failed,
            error_msg=str(e),
            duration_ms=dur,
        )
        log.error("crawl_user.failed", uid=uid, error=str(e))
        raise


async def _upsert_user(
    session: AsyncSession,
    uid: int,
    user_obj: dict,
    data: dict,
) -> None:
    """核心：把爬到的 user_obj + data.prizes/elo/gu/dailyCounts 写库。"""
    now = utcnow()
    name = user_obj.get("name") or f"UID_{uid}"

    # ---------- 主表 upsert ----------
    existing = await session.get(LuoguUser, uid)
    color = _to_color(user_obj.get("color"))
    intro = user_obj.get("introduction") or ""

    if existing is None:
        existing = LuoguUser(
            uid=uid,
            name=name,
            avatar=user_obj.get("avatar"),
            background=user_obj.get("background"),
            slogan=user_obj.get("slogan"),
            badge=user_obj.get("badge"),
            introduction=intro,
            color=color,
            is_admin=bool(user_obj.get("isAdmin")),
            is_banned=bool(user_obj.get("isBanned")),
            ccf_level=int(user_obj.get("ccfLevel") or 0),
            xcpc_level=int(user_obj.get("xcpcLevel") or 0),
            following_count=int(user_obj.get("followingCount") or 0),
            follower_count=int(user_obj.get("followerCount") or 0),
            ranking=user_obj.get("ranking"),
            passed_problem_count=user_obj.get("passedProblemCount"),
            submitted_problem_count=user_obj.get("submittedProblemCount"),
            register_time=_to_dt(user_obj.get("registerTime")),
            first_crawled_at=now,
            last_crawled_at=now,
        )
        session.add(existing)
        await session.flush()
        # 新建时第一条 name_version / intro_version
        session.add(
            UserNameVersion(uid=uid, name=name, first_seen_at=now, last_seen_at=now)
        )
        if intro:
            session.add(
                UserIntroVersion(
                    uid=uid,
                    content=intro,
                    content_hash=sha256_hex(intro),
                    crawled_at=now,
                )
            )
    else:
        # ---- 名字变更检测 ----
        if name != existing.name:
            # 关闭旧版本
            stmt = (
                update(UserNameVersion)
                .where(
                    UserNameVersion.uid == uid,
                    UserNameVersion.name == existing.name,
                )
                .values(last_seen_at=now)
            )
            await session.execute(stmt)
            session.add(
                UserNameVersion(uid=uid, name=name, first_seen_at=now, last_seen_at=now)
            )
        else:
            # 只更新旧版本的 last_seen_at
            stmt = (
                update(UserNameVersion)
                .where(
                    UserNameVersion.uid == uid,
                    UserNameVersion.name == name,
                )
                .values(last_seen_at=now)
            )
            await session.execute(stmt)

        # ---- introduction 变更检测 ----
        if intro != (existing.introduction or ""):
            new_hash = sha256_hex(intro)
            # 判重（唯一键也能拦住，这里先查避免异常）
            q = select(UserIntroVersion).where(
                UserIntroVersion.uid == uid,
                UserIntroVersion.content_hash == new_hash,
            )
            if (await session.execute(q)).scalar_one_or_none() is None:
                session.add(
                    UserIntroVersion(
                        uid=uid,
                        content=intro,
                        content_hash=new_hash,
                        crawled_at=now,
                    )
                )

        # ---- 数值字段时间序列 ----
        await _snap_numeric(session, uid, "following_count", int(user_obj.get("followingCount") or 0), existing.following_count)
        await _snap_numeric(session, uid, "follower_count", int(user_obj.get("followerCount") or 0), existing.follower_count)
        if user_obj.get("ranking") is not None:
            await _snap_numeric(session, uid, "ranking", int(user_obj["ranking"]), existing.ranking or 0)

        # ---- 更新主表最新快照 ----
        existing.name = name
        existing.avatar = user_obj.get("avatar")
        existing.background = user_obj.get("background")
        existing.slogan = user_obj.get("slogan")
        existing.badge = user_obj.get("badge")
        existing.introduction = intro
        existing.color = color
        existing.is_admin = bool(user_obj.get("isAdmin"))
        existing.is_banned = bool(user_obj.get("isBanned"))
        existing.ccf_level = int(user_obj.get("ccfLevel") or 0)
        existing.xcpc_level = int(user_obj.get("xcpcLevel") or 0)
        existing.following_count = int(user_obj.get("followingCount") or 0)
        existing.follower_count = int(user_obj.get("followerCount") or 0)
        existing.ranking = user_obj.get("ranking")
        existing.passed_problem_count = user_obj.get("passedProblemCount")
        existing.submitted_problem_count = user_obj.get("submittedProblemCount")
        existing.last_crawled_at = now

    # ---------- 用户名违规检测 ----------
    await _check_and_record_name_violation(session, uid, name, now)

    # ---------- prizes ----------
    await _sync_prizes(session, uid, data.get("prizes") or [])

    # ---------- elo ----------
    await _sync_elo(session, uid, data.get("elo") or [])

    # ---------- gu ----------
    gu = data.get("gu")
    if isinstance(gu, dict):
        await _snap_gu(session, uid, gu)

    # ---------- dailyCounts ----------
    await _sync_daily(session, uid, data.get("dailyCounts") or [])


async def _snap_numeric(
    session: AsyncSession,
    uid: int,
    field: str,
    new_value: int,
    prev_value: int,
) -> None:
    """数值字段变化才存一行时间序列。"""
    if new_value == prev_value:
        return
    session.add(
        UserNumericSnapshot(uid=uid, field_name=field, value=new_value)
    )


async def _check_and_record_name_violation(
    session: AsyncSession,
    uid: int,
    name: str,
    now: datetime,
) -> None:
    """用户名违规检测 + 级联隐藏。

    命中条件：
    - 当前 name 匹配系统格式（不论 isBanned）
    之后的级联：把 triggered_at 之前的所有 name_versions is_hidden=true。
    """
    if not _is_violation_name(name):
        return

    # 是否已有记录（同 uid 只记第一次，后续再命中不重复触发）
    q = select(UserNameViolation).where(UserNameViolation.uid == uid).limit(1)
    if (await session.execute(q)).scalar_one_or_none() is not None:
        return

    session.add(
        UserNameViolation(
            uid=uid,
            trigger_source=NameViolationSource.SYSTEM_NAME_PATTERN,
            source_ref=None,
            reason_raw=f"系统格式匹配: name={name}",
            matched_keywords={"pattern": "system_name", "name": name},
            triggered_at=now,
        )
    )
    # 隐藏此刻之前的所有 name_versions（包括当前这次也会被标记 hidden，
    # 因为新 version 的 first_seen_at = now，比较时用 <= now）
    stmt = (
        update(UserNameVersion)
        .where(
            UserNameVersion.uid == uid,
            UserNameVersion.first_seen_at <= now,
        )
        .values(is_hidden=True)
    )
    await session.execute(stmt)
    log.warning("user.name_violation_triggered", uid=uid, name=name)


async def _sync_prizes(session: AsyncSession, uid: int, prizes: list) -> None:
    """OI 奖项同步（只增不减，UNIQUE 拦重复）。"""
    from sqlalchemy.dialects.mysql import insert as mysql_insert

    if not prizes:
        return
    rows = []
    for item in prizes:
        p = item.get("prize") if isinstance(item, dict) else None
        if not isinstance(p, dict):
            continue
        rows.append(
            {
                "uid": uid,
                "year": int(p.get("year") or 0),
                "contest": p.get("contest") or "",
                "event": p.get("event"),
                "prize": p.get("prize") or "",
            }
        )
    if not rows:
        return
    # 使用 INSERT IGNORE 语义避免 UNIQUE 冲突
    stmt = mysql_insert(UserPrize).values(rows).prefix_with("IGNORE")
    await session.execute(stmt)


async def _sync_elo(session: AsyncSession, uid: int, elo_list: list) -> None:
    from sqlalchemy.dialects.mysql import insert as mysql_insert

    if not elo_list:
        return
    rows = []
    for item in elo_list:
        contest = item.get("contest") if isinstance(item, dict) else None
        if not isinstance(contest, dict):
            continue
        rows.append(
            {
                "uid": uid,
                "rating": int(item.get("rating") or 0),
                "time": _to_dt(item.get("time")) or utcnow(),
                "contest_id": int(contest.get("id") or 0),
                "contest_name": contest.get("name") or "",
                "prev_diff": item.get("prevDiff"),
            }
        )
    if not rows:
        return
    stmt = mysql_insert(UserEloHistory).values(rows).prefix_with("IGNORE")
    await session.execute(stmt)


async def _snap_gu(session: AsyncSession, uid: int, gu: dict) -> None:
    """咕值每次抓到都对比上一条，值有变才存。"""
    scores = gu.get("scores") or {}
    new = {
        "rating": int(gu.get("rating") or 0),
        "time": _to_dt(gu.get("time")) or utcnow(),
        "social": int(scores.get("social") or 0),
        "basic": int(scores.get("basic") or 0),
        "contest": int(scores.get("contest") or 0),
        "practice": int(scores.get("practice") or 0),
        "prize": int(scores.get("prize") or 0),
    }
    # 取最新一条对比
    q = (
        select(UserGuHistory)
        .where(UserGuHistory.uid == uid)
        .order_by(UserGuHistory.time.desc())
        .limit(1)
    )
    latest = (await session.execute(q)).scalar_one_or_none()
    if latest is not None:
        same = (
            latest.rating == new["rating"]
            and latest.social == new["social"]
            and latest.basic == new["basic"]
            and latest.contest == new["contest"]
            and latest.practice == new["practice"]
            and latest.prize == new["prize"]
        )
        if same:
            return
    session.add(UserGuHistory(uid=uid, **new))


async def _sync_daily(session: AsyncSession, uid: int, daily: list) -> None:
    """打卡热图：每条 (date, count) 走 upsert。"""
    from sqlalchemy.dialects.mysql import insert as mysql_insert

    rows = []
    for item in daily:
        # 洛谷返回形式：[{"date": "2026-01-01", "count": 3}, ...]（格式猜测）
        if not isinstance(item, dict):
            continue
        d_val = item.get("date")
        c_val = item.get("count")
        if not d_val or c_val is None:
            continue
        # 尝试解析日期
        try:
            from datetime import date as _d
            if isinstance(d_val, str):
                y, m, day = d_val.split("-")
                d_obj = _d(int(y), int(m), int(day))
            else:
                continue
        except Exception:
            continue
        rows.append({"uid": uid, "date": d_obj, "count": int(c_val)})
    if not rows:
        return
    stmt = mysql_insert(UserDailyActivity).values(rows)
    stmt = stmt.on_duplicate_key_update(count=stmt.inserted.count)
    await session.execute(stmt)
