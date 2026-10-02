#!/bin/sh
# The backup pod captures stdout for the bundle. Send status text to stderr.
set -eu

name="k8up-$(date +%s)-$$.zip"
path="/var/lib/clickhouse/backups/$name"
trap 'rm -f "$path"' EXIT HUP INT TERM

clickhouse-client --host=127.0.0.1 --user=plausible \
  --password="$CLICKHOUSE_PASSWORD" \
  --query="BACKUP DATABASE plausible_events_db TO Disk('backups', '$name')" >/dev/null
test -s "$path"
cat "$path"
