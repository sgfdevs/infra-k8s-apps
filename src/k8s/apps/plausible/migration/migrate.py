#!/usr/bin/env python3
"""Catch up analytics from the old Docker instance without stopping either app.

Run after DNS switches and again after old traffic drains:
  python3 migrate.py

The initial PostgreSQL/ClickHouse copy is separate. This script only imports
missing event rows and new or newer source-owned sessions. Historical ambiguous
session keys and equal-version differences are left untouched. Both collectors
use process-local session caches and randomly generated session IDs, so a cold
new collector does not update the imported source sessions.
"""

import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import uuid

DB = "plausible_events_db"
STAGE = "plausible_migration"
KUBE = ["kubectl", "--context", "sgfdevs-k3s", "--request-timeout=30s", "-n", "plausible"]
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "ubuntu@bighead.levizitting.com"]
KEY = "site_id, toDate(start), user_id, session_id"
MATCH = "s.site_id=t.site_id AND toDate(s.start)=toDate(t.start) AND s.user_id=t.user_id AND s.session_id=t.session_id"


def execute(args, data=None):
    result = subprocess.run(args, input=data, capture_output=True, timeout=120)
    if result.returncode:
        # Do not print client errors containing imported rows or credentials.
        raise RuntimeError(f"{args[0]} failed with exit {result.returncode}; no automatic retry")
    return result.stdout


def source(query):
    command = ["sudo", "-n", "docker", "exec", "sgfdevs-plausible-plausible_events_db-1",
               "clickhouse-client", "--readonly=1", "--query", query]
    return execute(SSH + [shlex.join(command)])


def target(query, data=None):
    shell = 'exec clickhouse-client --host=127.0.0.1 --user=plausible --password="$CLICKHOUSE_PASSWORD" "$@"'
    return execute(KUBE + ["exec", "-i", "plausible-clickhouse-0", "-c", "clickhouse", "--",
                          "sh", "-ec", shell, "sh", "--query_id", "plausible-migration-" + uuid.uuid4().hex,
                          "--query", query], data)


def scalar(query):
    return int(target(query + " FORMAT TSV").strip())


def columns(table, reader):
    query = (f"SELECT name, type FROM system.columns WHERE database='{DB}' AND table='{table}' "
             "AND default_kind != 'ALIAS' ORDER BY position FORMAT JSONEachRow")
    return [json.loads(line) for line in reader(query).splitlines()]


def names(schema, alias="", negative=False):
    return ", ".join("toInt8(-1) AS sign" if negative and c["name"] == "sign"
                     else alias + "`" + c["name"].replace("`", "\\`") + "`" for c in schema)


def insert(table, schema, data):
    if data:
        target(f"INSERT INTO {table} ({names(schema)}) "
               "SETTINGS insert_allow_materialized_columns=1, async_insert=0 FORMAT Native", data)


def main():
    os.umask(0o077)
    work = Path.home() / ".local/state/plausible-migration"
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    work.chmod(0o700)
    with (work / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        active = scalar("SELECT count() FROM system.processes WHERE query_id LIKE 'plausible-migration-%' AND query NOT LIKE '%system.processes%'")
        if active:
            raise RuntimeError("An earlier migration query is still running; wait before retrying")
        schemas = {table: columns(table, source) for table in ["events_v2", "sessions_v2"]}
        for table, schema in schemas.items():
            if not schema or schema != columns(table, target):
                raise RuntimeError(f"Source/target schema mismatch for {table}")
        target(f"DROP DATABASE IF EXISTS {STAGE} SYNC")
        target(f"CREATE DATABASE {STAGE}")
        for table, schema in schemas.items():
            target(f"CREATE TABLE {STAGE}.{table} AS {DB}.{table} ENGINE=MergeTree")
            final = " FINAL" if table == "sessions_v2" else ""
            insert(f"{STAGE}.{table}", schema, source(f"SELECT {names(schema)} FROM {DB}.{table}{final} FORMAT Native"))

        events = schemas["events_v2"]
        missing = f"SELECT {names(events)} FROM {STAGE}.events_v2 EXCEPT ALL SELECT {names(events)} FROM {DB}.events_v2"
        count = scalar(f"SELECT count() FROM ({missing})")
        if count:
            # EXCEPT ALL preserves repeated identical events. Recompute on retry.
            target(f"INSERT INTO {DB}.events_v2 ({names(events)}) "
                   f"SETTINGS insert_allow_materialized_columns=1, async_insert=0 {missing}")
        print(f"Missing events imported: {count}", flush=True)

        sessions = schemas["sessions_v2"]
        target(f"CREATE TABLE {STAGE}.current_sessions AS {DB}.sessions_v2 ENGINE=MergeTree")
        target(f"INSERT INTO {STAGE}.current_sessions ({names(sessions)}) "
               f"SETTINGS insert_allow_materialized_columns=1 SELECT {names(sessions)} FROM {DB}.sessions_v2 FINAL")
        eligible_source = f"SELECT {KEY} FROM {STAGE}.sessions_v2 GROUP BY {KEY} HAVING count()=1 AND sum(sign)=1"
        eligible_target = f"SELECT {KEY} FROM {STAGE}.current_sessions GROUP BY {KEY} HAVING count()=1 AND sum(sign)=1"
        updates = (f"FROM {STAGE}.sessions_v2 s INNER JOIN {STAGE}.current_sessions t ON {MATCH} "
                   f"WHERE (s.site_id,toDate(s.start),s.user_id,s.session_id) IN ({eligible_source}) "
                   f"AND (t.site_id,toDate(t.start),t.user_id,t.session_id) IN ({eligible_target}) AND s.events>t.events")
        target(f"CREATE TABLE {STAGE}.changes AS {DB}.sessions_v2 ENGINE=MergeTree")
        target(f"INSERT INTO {STAGE}.changes ({names(sessions)}) SETTINGS insert_allow_materialized_columns=1 "
               f"SELECT {names(sessions, 't.', negative=True)} {updates} UNION ALL "
               f"SELECT {names(sessions, 's.')} {updates} UNION ALL "
               f"SELECT {names(sessions)} FROM {STAGE}.sessions_v2 WHERE ({KEY}) IN ({eligible_source}) "
               f"AND ({KEY}) NOT IN (SELECT {KEY} FROM {STAGE}.current_sessions)")
        changes = scalar(f"SELECT count() FROM {STAGE}.changes")
        ambiguous = scalar(f"SELECT count() FROM (SELECT {KEY} FROM {STAGE}.sessions_v2 GROUP BY {KEY} HAVING count()!=1 OR sum(sign)!=1)")
        if changes:
            if changes >= 1000000:
                raise RuntimeError("Session batch exceeds the single-block limit; no session changes applied")
            # Stage first, then send one block so each cancellation/replacement
            # pair commits together in its partition. Never resend a saved batch.
            data = target(f"SELECT {names(sessions)} FROM {STAGE}.changes FORMAT Native")
            target(f"INSERT INTO {DB}.sessions_v2 ({names(sessions)}) "
                   "SETTINGS insert_allow_materialized_columns=1, async_insert=0, max_insert_block_size=1000000, "
                   "min_insert_block_size_rows=1000000, min_insert_block_size_bytes=536870912 FORMAT Native", data)
        print(f"Signed session rows imported: {changes}; ambiguous source keys left untouched: {ambiguous}", flush=True)
        target(f"DROP DATABASE {STAGE} SYNC")


if __name__ == "__main__":
    main()
