#!/usr/bin/env bash
# MySQL 备份脚本 —— 每日一次，保留 7 天
# 用法：配合 cron
#   0 3 * * * /srv/luogu-archive/scripts/backup-mysql.sh >> /var/log/luogu-archive-backup.log 2>&1
#
# 注意：不要把 .env 里的密码暴露在命令行，而是写入 ~/.my.cnf：
#   [client]
#   user=luogu_archive
#   password=<强密码>
#   host=127.0.0.1

set -euo pipefail

BACKUP_DIR="/var/backups/luogu-archive"
DB_NAME="luogu_archive"
RETENTION_DAYS=7

mkdir -p "$BACKUP_DIR"
DATE=$(date +%Y%m%d_%H%M%S)
OUT="$BACKUP_DIR/${DB_NAME}_${DATE}.sql.gz"

mysqldump \
    --single-transaction \
    --routines --triggers --events \
    --default-character-set=utf8mb4 \
    --set-gtid-purged=OFF \
    "$DB_NAME" \
  | gzip -9 > "$OUT"

echo "[$(date -Iseconds)] backup done: $OUT ($(du -h "$OUT" | cut -f1))"

# 清理超 N 天的旧备份
find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -type f -mtime +${RETENTION_DAYS} -delete
