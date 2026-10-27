#!/bin/sh
set -eu

: "${CLICKHOUSE_PASSWORD:?CLICKHOUSE_PASSWORD is required}"
export CLICKHOUSE_PASSWORD

client() {
  clickhouse-client --host=127.0.0.1 --user=plausible \
    --password="$CLICKHOUSE_PASSWORD" "$@"
}

for dictionary in acquisition_channel_paid_sources_dict acquisition_channel_source_category_dict location_data_dict; do
  definition=$(client --query="SHOW CREATE DICTIONARY plausible_events_db.$dictionary FORMAT TSVRaw")
  # Restored dictionary sources retain the old server's credentials. Preserve
  # their schema and layout, but quote the current password without shell eval.
  query=$(printf '%s\n' "$definition" | awk '
    BEGIN {
      password = ENVIRON["CLICKHOUSE_PASSWORD"]
      escaped = ""
      for (i = 1; i <= length(password); i++) {
        c = substr(password, i, 1)
        if (c == "\\" || c == "\047") escaped = escaped "\\"
        if (c == "\n") c = "\\n"
        if (c == "\r") c = "\\r"
        if (c == "\t") c = "\\t"
        escaped = escaped c
      }
      marker = "PASSWORD \047[HIDDEN]\047"
      credential = "PASSWORD \047" escaped "\047"
    }
    NR == 1 {
      if ($0 !~ /^CREATE DICTIONARY /) exit 1
      sub(/^CREATE DICTIONARY /, "CREATE OR REPLACE DICTIONARY ")
    }
    {
      position = index($0, marker)
      if (position) {
        $0 = substr($0, 1, position - 1) credential substr($0, position + length(marker))
        replacements++
      }
      print
    }
    END { if (replacements != 1) exit 1 }
  ')
  # A syntax error can echo the credential-bearing query. Keep it out of logs.
  if ! printf '%s\n' "$query" | client >/dev/null 2>/dev/null; then
    echo "Failed to repair ClickHouse dictionary: $dictionary" >&2
    exit 1
  fi
done

# Exercise the same dictionary lookups used by event/session inserts and stats.
client --multiquery --query="
  SELECT dictHas('plausible_events_db.acquisition_channel_paid_sources_dict', tuple('google'));
  SELECT dictGet('plausible_events_db.acquisition_channel_source_category_dict', 'category', tuple('google'));
  SELECT dictGet('plausible_events_db.location_data_dict', 'name', tuple('country', 'US'));
" >/dev/null
