#!/bin/sh
set -eu

# One-time empty-instance initialization, not a data migration or upgrade job.
# Fail closed rather than run the image entrypoint, which swallows failures.
existing="$(psql "$PG_DATABASE_URL" -v ON_ERROR_STOP=1 -tAc "SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'core')")"
if [ "$existing" != "f" ]; then
  echo 'Refusing to initialize a database that already has a core schema.' >&2
  exit 1
fi

yarn database:init:prod
yarn command:prod upgrade
psql "$PG_DATABASE_URL" -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM core."user"; SELECT count(*) FROM core.workspace;'

yarn command:prod cron:register:all > /tmp/cron-registration.log 2>&1
cat /tmp/cron-registration.log
# This command can exit zero after individual registration failures.
grep -Eq 'Cron job registration completed: [0-9]+ successful, 0 failed,' /tmp/cron-registration.log
