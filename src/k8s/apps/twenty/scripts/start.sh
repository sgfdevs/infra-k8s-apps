#!/bin/sh
set -eu

# The generic Valkey Service includes read-only replicas. Every Twenty client,
# including pub/sub and BullMQ, must connect to the primary-only Service.
REDIS_URL="$(node -e 'process.stdout.write(`redis://:${encodeURIComponent(process.env.REDIS_PASSWORD)}@twenty-valkey-primary:6379`)')"
export REDIS_URL
export REDIS_QUEUE_URL="$REDIS_URL"
exec "$@"
