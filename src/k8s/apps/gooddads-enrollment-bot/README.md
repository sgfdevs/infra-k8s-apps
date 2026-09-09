# Good Dads enrollment bot staging

Staging only, at `https://gooddads-enrollment-bot-staging.opensgf.org`, in namespace
`gooddads-enrollment-bot-staging`. There are no production resources or root
Kustomization. `base/` is not deployable by itself. Render `staging/`.

## Merge blocker

`staging/kustomization.yaml` deliberately says `newTag: v0.3.0`, **pending publication**.
This does not claim that the release exists. The image repository is
`ghcr.io/open-sgf/gooddads-enrollment-bot`.

Before merging this directory to `main`, publish and verify the intended image, then
replace `newTag` with `digest: sha256:<verified release digest>` in the same image
entry. Do not paste a guessed digest or merge the placeholder. Kustomize must render
the same immutable image for the app, migration and both init containers.

`../application-set.yaml` discovers `staging/kustomization.yaml` on `main` and enables
automated sync, pruning and self-healing. There is no post-merge deployment pause.
Complete the prerequisite work below before making this overlay discoverable.

The release must include real `MAIL_INTAKE_FORM_RECIPIENT` support from the concurrent
`fix/completed-form-recipient` source work. Confirm that support in the published
artifact, not just in a source checkout. This infrastructure work does not change the
source app or provide a release pipeline or source smoke-test script.

## Rollout order

These are future operator actions requiring separate approval. None are performed by
the offline validation commands below.

1. Create secrets. Review and apply the staging module in
   `sgfdevs/infra-app-config/src/tf/modules/gooddads-enrollment-bot/` through that repo's
   normal approved workflow, before this Kubernetes overlay reaches `main`. It generates
   `APP_KEY` once on initial secret creation, creates the remaining eight properties as
   `CHANGEME` in five grouped documents, and manages the separate SES credentials.
   It binds the staging OpenBao role to service account
   `gooddads-enrollment-bot-secrets` in namespace `gooddads-enrollment-bot-staging` with
   audience `vault`. Do not overwrite already filled secrets or an existing app key.
2. Fill manually. An authorized operator updates each of the `neon`, `dropbox`, `oauth`,
   `sentry` and `notifications` documents under
   `applications/gooddads-enrollment-bot/staging/`, preserving every key listed below
   and replacing every `CHANGEME`. Use only staging Neon and Dropbox accounts and an
   approved test mail recipient. Keep `sentryDsn` present but set it to an empty string
   if unused. Each document has an independent write-only version counter. Keep these
   counters unchanged after manual fill; incrementing a counter or recreating its
   resource resets that document's values to `CHANGEME`.
   Do not put values in Git, terminal history, logs or rendered test fixtures.
   Preserve the generated app key across rollouts. Never generate one at container
   startup. Its separate rotation rules are documented below.
3. Release and pin the image. Publish the intended version, verify GHCR pull access
   from cluster nodes and supported node architectures, and record its real digest in
   `staging/kustomization.yaml`. Run the render checks including `--require-digest`.
   Verify the image's `/up`, migrations, PDF generation and four Supervisor processes
   under UID/GID 33, dropped capabilities and a read-only root with these mounts.
   A local image tag is not proof that the GHCR release exists or can be pulled.
4. Deploy. First confirm DNS and public-edge SNI forwarding for the exact hostname,
   `letsencrypt-prod` issuance for `opensgf.org`, Longhorn/local-path capacity, and
   installed KubeBlocks MySQL, db-operator and External Secrets controllers. Merge only
   after the preceding gates pass. Argo then discovers and syncs the staging app.
   Use a full application sync, not a selective resource sync that skips hooks. Check
   operator readiness and hook completion without displaying secret payloads. Complete
   the manual acceptance tests below before enabling unattended polling or real data.

SES uses `email-smtp.us-east-2.amazonaws.com:587` with SMTP STARTTLS. The region comes
from `infra-app-config/src/tf/variables.tf` and its AWS provider; the existing
`hack4goodsgf.com/base/configmap.yaml` uses the same endpoint. The sender
`staging-gooddads-enrollment-bot@sgf.dev` matches the staging SES module and its
`SgfDevSESSender` policy. Verify the applied region, sender identity, delivery limits
and any SES sandbox recipient restrictions during rollout. `MAIL_SCHEME=smtp` uses
Symfony's STARTTLS negotiation; this app does not read `MAIL_ENCRYPTION`.

## Secret and environment contract

Paths are relative to the KV v2 mount `applications`. Properties are case-sensitive.
`ExternalSecret` resources produce environment-named Kubernetes keys, and both the
Deployment and migration Job consume the two resulting Secrets with `envFrom`.

Only remote OpenBao storage is split. The two ExternalSecrets and their environment
Secrets remain `gooddads-enrollment-bot-application` and `gooddads-enrollment-bot-ses`;
workload `envFrom` entries are unchanged.

| OpenBao path | OpenBao property | Environment variable | Initial value |
| --- | --- | --- | --- |
| `gooddads-enrollment-bot/staging/laravel` | `appKey` | `APP_KEY` | Automatically generated `base64:<base64>` |
| `gooddads-enrollment-bot/staging/neon` | `neonBaseUrl` | `NEON_BASE_URL` | `CHANGEME` |
| `gooddads-enrollment-bot/staging/neon` | `neonApiKey` | `NEON_API_KEY` | `CHANGEME` |
| `gooddads-enrollment-bot/staging/dropbox` | `dropboxAppKey` | `DROPBOX_APP_KEY` | `CHANGEME` |
| `gooddads-enrollment-bot/staging/dropbox` | `dropboxAppSecret` | `DROPBOX_APP_SECRET` | `CHANGEME` |
| `gooddads-enrollment-bot/staging/oauth` | `dropboxOauthBasicUser` | `DROPBOX_OAUTH_BASIC_USER` | `CHANGEME` |
| `gooddads-enrollment-bot/staging/oauth` | `dropboxOauthBasicPassword` | `DROPBOX_OAUTH_BASIC_PASSWORD` | `CHANGEME` |
| `gooddads-enrollment-bot/staging/sentry` | `sentryDsn` | `SENTRY_LARAVEL_DSN` | `CHANGEME`, operator may set empty |
| `gooddads-enrollment-bot/staging/notifications` | `mailIntakeFormRecipient` | `MAIL_INTAKE_FORM_RECIPIENT` | `CHANGEME` |
| `gooddads-enrollment-bot/staging/ses` | `username` | `MAIL_USERNAME` | Managed SES credential |
| `gooddads-enrollment-bot/staging/ses` | `password` | `MAIL_PASSWORD` | Managed SES credential |

The module generates `APP_KEY` once on initial creation of the `laravel` secret using
an ephemeral `random_bytes` resource with `length = 32`. It stores `base64:<base64>`
through the write-only Vault payload. Keep the Laravel secret's independent write-only
version counter fixed. Incrementing it or recreating the secret resource rotates the
key and can make encrypted tokens and jobs unrecoverable. This counter is independent
of the five placeholder documents' counters. Preserve an existing installation's key
rather than replacing it during rollout. The SES path is unchanged.

SES values are managed credentials, not application placeholders. db-operator creates
`gooddads-enrollment-bot-database`; its `DB`, `USER` and `PASSWORD` keys map to
`DB_DATABASE`, `DB_USERNAME` and `DB_PASSWORD` in both workloads. Neither workload uses
the MySQL root credential. The cluster-scoped `DbInstance` references the generated
root Secret in the staging namespace. The namespace-removal transformer follows
`hack4goodsgf.com` and must remain in the overlay.

Non-secret settings live in the ConfigMap. `APP_ENV=staging`, `APP_DEBUG=false`,
`LOG_CHANNEL=stderr`, `DB_CONNECTION=mysql`, and the cache, session and queue drivers
all use the database. `APP_URL` and `DROPBOX_REDIRECT_URI` use the staging HTTPS host;
the callback path is `/dropbox/callback`. OAuth Basic Auth and secure session cookies
are enabled. Uploads use `/staging/gooddads-enrollment-bot` in Dropbox. The app does not
read `APP_TIMEZONE`, so it is intentionally absent. Do not assume the scheduler uses
local Springfield time; confirm the actual schedule and application timezone.

External Secrets refreshes hourly. Environment variables in running processes do not
refresh when a Secret changes. After an approved change, wait for synchronization and
perform an approved app restart. ConfigMap changes also need a restart. No automatic
reloader is enabled here; a Secret refresh must not restart an old image during a
migration. Preserve the app key and keep the migration and app configuration aligned.

## Ordering and runtime

| Argo Sync wave | Resources |
| --- | --- |
| `-3` | Staging Namespace |
| `-2` | OpenBao-auth ServiceAccount |
| `-1` | SecretStore, application ConfigMap, robots ConfigMap |
| `0` | KubeBlocks MySQL Cluster and both ExternalSecrets |
| `1` | Cluster-scoped staging DbInstance |
| `2` | Database and its operator-generated credentials |
| `3` | Sync migration hook, `php8.5 artisan migrate --force --no-interaction` |
| `4` | Document PVC, Deployment, Service, certificate, ingress and middleware |

The migration hook waits for a real application database login with bounded retries,
then runs migrations. A missing generated Secret prevents container startup; the Job
has a 900-second deadline. Failures block the later deployment. Successful hooks are
deleted; failed Jobs remain for diagnosis for up to one day or until the next full
sync replaces them. This is a Sync hook, not PreSync, because its ConfigMap and other
dependencies must already exist.

The application runs one replica with `Recreate`, because one image includes Nginx,
PHP-FPM, the scheduler and queue worker. MySQL follows the existing two-replica
KubeBlocks `semisync` pattern with 10Gi local-path data volumes. `/up` checks readiness;
the image's `/usr/local/bin/healthcheck` also checks all four Supervisor processes for
startup and liveness. Shutdown allows 120 seconds before Kubernetes terminates the pod.

The local Dockerfile and production config establish these paths:

| Mount | Storage and purpose |
| --- | --- |
| `/tmp` | Per-pod emptyDir for Nginx, Supervisor and pdftk temporary files |
| `/var/www/html/bootstrap/cache` | Per-pod emptyDir subdirectory, seeded from the same image by an init container |
| `/var/www/html/storage/framework` | Per-pod emptyDir subdirectory with cache/data, sessions and views directories |
| `/var/www/html/storage/logs` | Per-pod emptyDir subdirectory; normal application logs go to stderr |
| `/var/www/html/storage/app/private` | 10Gi Longhorn RWO PVC for generated participant documents |
| `/var/www/html/public/robots.txt` | Read-only staging ConfigMap file |

All app and migration containers, including init containers, run as UID/GID 33 with
`fsGroup: 33`, read-only roots, no privilege escalation, all capabilities dropped and
no mounted service-account token. The migration uses its own ephemeral private
storage, not the app's RWO PVC, so it cannot contend with an existing app pod.

Never mount over `/var/www/html/storage` or `storage/intake-form`. The image contains
`/var/www/html/storage/intake-form/Enrollment_Form_Fillable_2026-01-27.pdf`; generated
files belong under `storage/app/private/participant-forms`. No public storage symlink
is created. This preserves the template without putting private documents in the
Nginx document root.

On an upgrade, the old app can still run during wave 3. `Recreate` prevents overlap
between old and new app pods in wave 4, but does not quiesce the old scheduler before
migrations. Require backward-compatible migrations or plan an approved maintenance
window. Reverting an image does not roll back the database. There is no automated
backup schedule here. `terminationPolicy: WipeOut`, unprotected Database deletion and
Argo pruning can destroy data; arrange and test database/document backups before real
participant data or destructive changes. Longhorn replication is not a backup.

## Manual acceptance

Use synthetic participants and staging integrations. These tests send mail, upload
files and mutate database state, so operators must approve and run them separately.

- Confirm the migration succeeds, expected tables exist, the Deployment has one ready
  pod, all four Supervisor processes run, `/up` returns 200, and logs show no permission
  errors. Confirm `schedule:list` actually contains the intended Neon polling schedule;
  a running scheduler alone does not prove polling is configured.
- Confirm HTTP redirects to HTTPS, the TLS certificate covers the exact hostname,
  responses include `X-Robots-Tag: noindex, nofollow, noarchive, nosnippet`, and
  `/robots.txt` disallows `/`. Noindex is not access control; OAuth Basic Auth protects
  only the OAuth routes, not the whole site.
- Register exactly
  `https://gooddads-enrollment-bot-staging.opensgf.org/dropbox/callback` in the staging
  Dropbox app. Check unauthenticated and incorrect Basic Auth requests are rejected.
  Complete `/dropbox/authorize` and the callback in one browser session; verify secure
  session cookies survive the redirect and invalid/replayed OAuth state is rejected.
- Run the source's `dropbox:test-upload` command, then `dropbox:test-upload --expire-token`
  in an approved staging session to test upload and token refresh. Verify files land
  only under the staging upload path. Do not print tokens. Remove synthetic uploads
  after testing. Restart the app and confirm authorization persists in MySQL.
- Fetch and process a synthetic Neon participant through the actual polling/queue flow.
  Verify the bundled template produces a filled, flattened PDF, the private file
  survives a pod recreation, Dropbox receives the intended document, and SES delivers
  it only to `MAIL_INTAKE_FORM_RECIPIENT`. Confirm no old hard-coded recipient receives
  mail. Check failed jobs and repeat processing for unintended duplicates.
- If Sentry is enabled, send an approved synthetic error and confirm staging reporting
  without participant data. If disabled, confirm an empty DSN does not break startup
  or exception handling. Do not leave `CHANGEME` in any application property.

## Offline validation

From this repository root, with Kustomize, PyYAML, Kubeconform, KubeLinter and yamllint
available:

```sh
app=src/k8s/apps/gooddads-enrollment-bot
kustomize build "$app/base" > /tmp/gooddads-base.yaml
kustomize build "$app/staging" > /tmp/gooddads-staging.yaml
python3 "$app/validate-render.py" /tmp/gooddads-staging.yaml
kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.36.2 \
  /tmp/gooddads-base.yaml /tmp/gooddads-staging.yaml
kube-linter lint /tmp/gooddads-base.yaml /tmp/gooddads-staging.yaml
yamllint -d '{extends: relaxed, rules: {line-length: disable}}' "$app"
# Required before merge. This deliberately fails while newTag is pending.
python3 "$app/validate-render.py" --require-digest /tmp/gooddads-staging.yaml
```

The render contract checks all 18 staging resources, namespace scope, generated
resource references, exact secret mappings, sync ordering, image consistency,
security contexts, storage mounts and ingress wiring. It reads only the rendered YAML.
With uv, `uv run --no-project --with pyyaml python` can replace `python3` above.

The CI-compatible Kubeconform command skips unknown CRDs. For full schema coverage,
use schemas extracted from KubeBlocks `v1.0.2` and db-operator chart `3.12.0`, plus the
CRDs-catalog schemas for External Secrets, cert-manager and Traefik. The generic
catalog's Database v1beta1 schema has an obsolete required `backup` field; use the
pinned db-operator chart schema instead. Offline schema checks cannot prove controller
reconciliation, admission/CEL rules, storage provisioning, DNS, release availability
or integration delivery. Those remain rollout acceptance gates.
