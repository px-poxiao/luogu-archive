#!/usr/bin/env bash
# 验证当前节点是否能用账号 cookie 拿到 /api/feed/list。
# 直接复用项目栈（httpx + http2 + 真实 header + 真实 cookie）。
# 用法：在中心机或 worker 机上 chmod +x test_feed.sh && ./test_feed.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT_DIR/backend"
PY="$BACKEND/.venv/bin/python"

[ -x "$PY" ] || { echo "!! 缺 venv：$PY"; exit 1; }

cd "$BACKEND"
"$PY" - <<'PYEOF'
import asyncio
from app.crawler.cookies import lease_account
from app.crawler.http import fetch_authed
from app.crawler.nodes import NodeKind, get_default_node
from app.core.redis_client import get_redis


async def main():
    node = get_default_node(NodeKind.AUTHED)
    redis = get_redis()
    async with lease_account() as acc:
        if acc is None:
            print("!! 没账号或全被禁用")
            return
        print(f">>> 节点 node_id={node.node_id}  账号 id={acc.account_id} luogu_uid={acc.luogu_uid}")
        try:
            r = await fetch_authed(
                f"/api/feed/list?user={acc.luogu_uid}&page=1",
                node=node, redis=redis,
                cookies=acc.as_cookie_dict(),
                accept_json=True, parse="json",
            )
            print(f"OK  status={r.status}  url={r.url}")
            if r.data and "feeds" in r.data:
                feeds = r.data["feeds"].get("result", [])
                print(f"    feeds count={len(feeds)}")
                if feeds:
                    print(f"    first time={feeds[0].get('time')}")
                    print(f"    first content={feeds[0].get('content', '')[:80]}")
            else:
                print(f"    body head: {r.body_text[:200]}")
        except Exception as e:
            print(f"FAIL {type(e).__name__}: {e}")


asyncio.run(main())
PYEOF
