#!/bin/sh
# Ежедневный pg_dump в /backups с ротацией. Запускается сервисом backup из docker-compose.yml.
# Переменные: PGHOST, PGUSER, PGPASSWORD, PGDATABASE (читает сам pg_dump), BACKUP_KEEP_DAYS.
set -u

KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"

while true; do
    ts="$(date +%Y%m%d_%H%M%S)"
    tmp="/backups/.approver_${ts}.tmp"
    out="/backups/approver_${ts}.sql.gz"

    # --no-owner/--no-privileges: дамп можно восстановить под любым пользователем.
    if pg_dump --no-owner --no-privileges | gzip > "$tmp" && [ -s "$tmp" ]; then
        mv "$tmp" "$out"
        echo "backup ok: $out"
        find /backups -name 'approver_*.sql.gz' -mtime "+${KEEP_DAYS}" -delete
    else
        rm -f "$tmp"
        echo "backup FAILED at ${ts}" >&2
    fi

    sleep 86400
done
