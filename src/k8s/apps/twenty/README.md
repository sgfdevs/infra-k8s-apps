# Twenty empty-instance preview

This deploys Twenty v2.41.0 at https://crm-preview.sgf.dev. It does not change
crm.sgf.dev or read/import the database, assets, or accounts on Bighead.

## Layout

- Two server pods and two worker pods, with per-component node anti-affinity.
- Two CloudNativePG PostgreSQL 16 instances with separate Longhorn volumes.
- Two persistent Valkey 9.0.4 instances with AOF, automatic failover, and
  `noeviction`. Every client uses `twenty-valkey-primary`, never the generic
  Service that also selects read-only replicas.
- Private S3 assets in `sgfdevs-twenty-assets`, using the existing Kubernetes
  OIDC provider and AWS pod-identity webhook. No static S3 keys.
- SES SMTP in us-east-2, restricted to `crm-preview@sgf.dev`. Twenty's system
  email driver does not support the SES API in this release.
- Password authentication remains enabled. No application SSO configuration.

`sgfdevs/infra-app-config` owns the bucket, IAM role, SMTP credentials, and
OpenBao configuration. `sgfdevs/infra-dns` owns the preview hostname. No
OpenSGF DNS changes are needed.

## Preview access

Temporary Traefik BasicAuth protects the empty instance from an unsolicited
first-admin signup. Retrieve `previewUsername` and `previewPassword` from
OpenBao `applications/twenty/app`; do not commit or paste them into logs.
The browser UI uses cookie authentication. Bearer-token integrations are not
supported through this temporary BasicAuth gate; use a private port-forward
for those checks or remove the gate after securing the instance.

The preview has its own generated APP_SECRET. Before any later data migration,
review the source instance's encryption/signing keys and account settings.
Do not import encrypted data under this generated preview key.

## Deployment

The top-level Kustomization is discovered by the apps ApplicationSet after
merge. For initial branch-backed deployment, use
`deploy/twenty-preview-application.yaml`. It creates the same `twenty` Argo CD
Application that the generator will manage from main after merge.

Apply the scoped app-config and DNS plans before syncing the Application.
Normal pods bypass the image entrypoint and never migrate or register cron
jobs. Sync wave 1 runs the one-time bootstrap Job; wave 2 starts application
pods only after the Job succeeds. Wave 3 exposes the ingress.

The bootstrap Job refuses a database that already contains a core schema.
It retains its completed status. Do not delete it to force a resync, and do
not treat it as an upgrade job. If initialization partially fails, inspect
the database and logs before deciding how to recover. Never automatically
drop an existing database.

Scripts use a stable ConfigMap name to keep the completed Job's Pod template
immutable. Reloader rolls the Deployments when their configuration or secrets
change. Image upgrades require a separately reviewed migration procedure.

## Availability limits

Two instances do not provide uninterrupted database or Valkey failover.
PostgreSQL replication is asynchronous. Valkey allows the single survivor to
accept writes with `min-replicas-to-write=0`; recent writes can be lost during
failover. AOF everysec does not eliminate that risk. Pub/sub events are not
replayed after a disconnected subscription.

Server readiness checks HTTP, PostgreSQL, and the Valkey primary role. Worker
readiness checks the dependencies, not successful execution of every queue.
Workers run Node directly so SIGTERM reaches Nest's shutdown hooks. Server
preStop allows endpoint removal to propagate, but the upstream HTTP shutdown
implementation does not guarantee draining every in-flight request.

Before putting real data here, configure and test off-cluster database/WAL
backups, add queue/error/replication alerts, and validate failover and upgrades.
S3 versioning and redundant volumes are not substitutes for database backups.

## Acceptance checks

- Render with `kubectl kustomize src/k8s/apps/twenty` and server-side dry-run.
- Review plans for only the new Twenty resources and preview DNS record.
- Bootstrap Job completes with zero cron-registration failures.
- Both server and worker Deployments have two ready replicas on distinct nodes.
- Database and Valkey each have two healthy instances; the primary Service
  has exactly one writable endpoint.
- Application clients can publish/subscribe across pods through that endpoint.
- Pods receive a projected AWS token and can access their private S3 bucket.
- SES SMTP authentication and delivery to the SES mailbox simulator work.
- Unauthenticated public requests receive 401; preview credentials reach the UI.
- The database contains no user accounts or workspaces before handoff.
