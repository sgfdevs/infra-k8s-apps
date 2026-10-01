#!/bin/sh
# K8up captures the custom-format dump directly from stdout.
set -eu
exec pg_dump --host=plausible-db-rw --username=plausible \
  --dbname=plausible --format=custom --no-owner --no-privileges
