// Resolve dependencies from the application, not the mounted scripts directory.
const { createRequire } = require('node:module');
const appRequire = createRequire(`${process.cwd()}/package.json`);
const { Client } = appRequire('pg');
const Redis = appRequire('ioredis');
const database = new Client({
  connectionString: process.env.PG_DATABASE_URL,
  connectionTimeoutMillis: 1500,
  query_timeout: 1500,
});
const redis = new Redis({
  host: 'twenty-valkey-primary',
  port: 6379,
  password: process.env.REDIS_PASSWORD,
  lazyConnect: true,
  connectTimeout: 1500,
  commandTimeout: 1500,
  retryStrategy: () => null,
});
redis.on('error', () => {});
const deadline = setTimeout(() => process.exit(1), 3500);
(async () => {
  await Promise.all([database.connect(), redis.connect()]);
  const [, role] = await Promise.all([database.query('SELECT 1'), redis.role()]);
  if (role[0] !== 'master') throw new Error('Valkey endpoint is not primary');
  if (process.env.READINESS_HTTP === 'true') {
    const response = await fetch('http://127.0.0.1:3000/healthz', {
      signal: AbortSignal.timeout(1500),
    });
    if (!response.ok) throw new Error('HTTP health check failed');
  }
})().catch(() => { process.exitCode = 1; }).finally(async () => {
  redis.disconnect();
  await database.end().catch(() => {});
  clearTimeout(deadline);
});
