#!/usr/bin/env bash
# 一键：修 save.py + 清库 + 迁移 + 重启 + 建管理员 + 测试
# 用法： cd /data/luogu-archive && bash scripts/reset-and-test.sh
# 会提示输入 MySQL 密码 + 新管理员账号密码

set -e

ROOT=/data/luogu-archive

echo "========== [1/6] 停服务 =========="
cd "$ROOT"
./stop.sh || true
rm -f run/*.pid

echo ""
echo "========== [2/6] 修 save.py =========="
python3 <<'PY'
p = "/data/luogu-archive/backend/app/api/v1/save.py"
s = open(p).read()
old = '''    # 派发
    if content_type == "article":
        msg = crawl_article.send(ident, "manual")
    elif content_type == "paste":
        msg = crawl_paste.send(ident, "manual")
    elif content_type == "user":
        msg = crawl_user.send(int(ident), "manual")
    elif content_type == "feed":
        # feed 的 ident 格式 "<uid>" 或 "<uid>:<page>"
        if ":" in ident:
            uid_str, page_str = ident.split(":", 1)
            uid, page = int(uid_str), int(page_str)
        else:
            uid, page = int(ident), 1
        msg = crawl_user_feeds.send(uid, page, "manual")
    elif content_type == "judgement":
        msg = crawl_judgement.send("manual")
    elif content_type == "problem":
        msg = crawl_problem_list_page.send(int(ident), "manual")
    elif content_type == "problem_solution":
        msg = crawl_problem_solution.send(ident, "manual")
    else:
        raise ValidationError("未知的 content_type")'''
new = '''    # 派发
    try:
        if content_type == "article":
            msg = crawl_article.send(ident, "manual")
        elif content_type == "paste":
            msg = crawl_paste.send(ident, "manual")
        elif content_type == "user":
            msg = crawl_user.send(int(ident), "manual")
        elif content_type == "feed":
            if ":" in ident:
                uid_str, page_str = ident.split(":", 1)
                uid, page = int(uid_str), int(page_str)
            else:
                uid, page = int(ident), 1
            msg = crawl_user_feeds.send(uid, page, "manual")
        elif content_type == "judgement":
            msg = crawl_judgement.send("manual")
        elif content_type == "problem":
            page = 1 if ident == "list" else int(ident)
            msg = crawl_problem_list_page.send(page, "manual")
        elif content_type == "problem_solution":
            msg = crawl_problem_solution.send(ident, "manual")
        else:
            raise ValidationError("未知的 content_type")
    except ValueError as e:
        raise ValidationError(f"无效的 id: {ident}") from e'''
if old in s:
    open(p, "w").write(s.replace(old, new))
    print("  save.py patched")
elif 'page = 1 if ident == "list" else int(ident)' in s:
    print("  save.py 已经是新版，跳过")
else:
    print("  !! save.py 结构不符，跳过自动修补。需要手动改。")
PY

echo ""
echo "========== [3/6] 改 CRAWLER_BASE_URL =========="
sed -i 's|^CRAWLER_BASE_URL=.*|CRAWLER_BASE_URL=https://www.luogu.com|' "$ROOT/backend/.env"
grep CRAWLER_BASE_URL "$ROOT/backend/.env"

echo ""
echo "========== [4/6] 清空数据库 =========="
echo "请输入 MySQL 的 luogu_archive 用户密码（下面两次都是同一个）："
mysql -u luogu_archive -p luogu_archive <<'SQL'
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS admin_audit_logs, admins, article_versions, articles,
    crawl_tasks, crawler_accounts, feeds, judgements, luogu_users,
    paste_versions, pastes, problem_solution_history, problems,
    save_requests, site_sessions, site_user_follows, site_users,
    takedown_requests, user_daily_activity, user_elo_history,
    user_gu_history, user_intro_versions, user_name_versions,
    user_name_violations, user_numeric_snapshots, user_prizes,
    alembic_version;
SET FOREIGN_KEY_CHECKS = 1;
SQL

echo ""
echo "========== [5/6] 跑迁移 + 建管理员 =========="
cd "$ROOT/backend"
. .venv/bin/activate
alembic upgrade head
echo ""
echo ">>> 交互式创建第一个管理员（请输入用户名/密码）"
echo ">>> 脚本最后会打印 TOTP secret，**立即**加到 Authenticator！"
python -m scripts.create_admin
deactivate

echo ""
echo "========== [6/6] 启动服务 =========="
cd "$ROOT"
./start.sh all
sleep 3
./start.sh status

echo ""
echo "========== 完成。手动触发几个爬取任务测试 =========="
cd "$ROOT/backend"
. .venv/bin/activate
python -c "
from app.tasks.actors.crawl import (crawl_judgement, crawl_user,
    crawl_user_feeds, crawl_problem_list_page)
crawl_judgement.send('manual')
crawl_user.send(1847473, 'manual')
crawl_user.send(8457, 'manual')
for p in range(1, 6):
    crawl_problem_list_page.send(p, 'manual')
print('  已派发 8 个任务')
"
# 犇犇账号还没录入时这条会失败，暂时跳过
deactivate

echo ""
echo ">>> 等 20 秒看结果..."
sleep 20
mysql -u luogu_archive -p luogu_archive -e "
SELECT id, task_type, status, LEFT(error_msg,120) err
FROM crawl_tasks ORDER BY id DESC LIMIT 15;"
echo ""
echo ">>> 表计数："
mysql -u luogu_archive -p luogu_archive -e "
SELECT 'judgements' as t, COUNT(*) c FROM judgements
UNION SELECT 'problems', COUNT(*) FROM problems
UNION SELECT 'feeds', COUNT(*) FROM feeds
UNION SELECT 'luogu_users', COUNT(*) FROM luogu_users
UNION SELECT 'articles', COUNT(*) FROM articles;"

echo ""
echo "完成。"
echo "注意：犇犇爬取需要在管理后台录入一个洛谷 cookie 账号后才能工作。"
echo "登录 https://<你的域名>/admin/login → 爬取账号 → 录入新账号"
