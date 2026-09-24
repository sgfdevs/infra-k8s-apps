#!/bin/sh
set -eu

# Outline accepts Sentinel settings as base64-encoded ioredis options.
# Passwords come from KubeBlocks account Secrets, never from this ConfigMap.
REDIS_URL=$(node -e '
  const options = {
    name: "outline-redis",
    sentinels: [0, 1, 2].map(i => ({
      host: `outline-redis-sentinel-${i}.outline-redis-sentinel-headless`,
      port: 26379,
    })),
    username: "default",
    password: process.env.REDIS_PASSWORD,
    sentinelUsername: "default",
    sentinelPassword: process.env.REDIS_SENTINEL_PASSWORD,
  };
  if (!options.password || !options.sentinelPassword) {
    throw new Error("Redis and Sentinel passwords are required");
  }
  process.stdout.write("ioredis://" + Buffer.from(JSON.stringify(options)).toString("base64"));
')
export REDIS_URL
export REDIS_COLLABORATION_URL="$REDIS_URL"
exec "$@"
