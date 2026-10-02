#!/bin/sh
set -eu

name="restore-$(date +%s)-$$.zip"
path="/var/lib/clickhouse/backups/$name"
trap 'rm -f "$path"' EXIT HUP INT TERM
cat > "$path"
test -s "$path"
unzip -p "$path" >/dev/null

clickhouse-client --host=127.0.0.1 --user=plausible \
  --password="$CLICKHOUSE_PASSWORD" \
  --query="DROP DATABASE plausible_events_db SYNC" >/dev/null
clickhouse-client --host=127.0.0.1 --user=plausible \
  --password="$CLICKHOUSE_PASSWORD" \
  --query="RESTORE DATABASE plausible_events_db FROM Disk('backups', '$name')" >/dev/null
count=$(clickhouse-client --host=127.0.0.1 --user=plausible \
  --password="$CLICKHOUSE_PASSWORD" \
  --query="SELECT count() FROM system.tables WHERE database = 'plausible_events_db' AND name IN ('events_v2', 'sessions_v2')")
if [ "$count" != 2 ]; then
  echo "Restored ClickHouse database is missing analytics tables." >&2
  exit 1
fi
