# GlitchTip

Private bootstrap of GlitchTip 6.2.3. Two pods each run the web server and
embedded worker. PostgreSQL stores events, tasks, cache, sessions, users, and
OIDC settings. There is no Redis, Valkey, ClickHouse, Kafka, or application PVC.

## Access and identity

The ApplicationSet discovers this directory as the `glitchtip` application.

```bash
kubectl -n glitchtip port-forward service/glitchtip 8000:8000
```

Open http://localhost:8000. Use exactly this hostname and port for Dex's
callback. Keep `config.env` synchronized with the GlitchTip static client in
`src/k8s/platform/dex.yaml`. The discovery endpoint is
https://dex.sgf.dev/.well-known/openid-configuration and the callback is
http://localhost:8000/accounts/oidc/dex/login/callback/.

Dex's GitHub connector restricts login to `sgfdevs` members in
`infra-platform-admins` or `infra-maintainers`. The first authorized SSO login
owns the SGF Devs organization. Further authorized users join as members. Open
password signup and arbitrary organization creation are disabled. No default
password account is created. The public OIDC client uses authorization code
flow with S256 PKCE and no client secret.

Create projects and upload sourcemaps using the GlitchTip CLI. Localhost DSNs
are only useful through the port-forward. Remote applications cannot use this
instance until a reachable ingestion URL is configured. There is deliberately
no ingress, certificate, DNS change, or change to existing Sentry instances.
When publishing it, update the application URL and Dex callback registration,
and use a confidential client with a managed secret for the public web instance.
Keep ingestion outside interactive ForwardAuth. Set tracing and log capture off in SDKs unless intentionally needed.

## Availability and resources

- Two application replicas have required node anti-affinity and a disruption
  budget allowing one replica to be unavailable.
- CNPG has two PostgreSQL instances on separate nodes with local storage and
  required synchronous replication. Writes pause without a synchronous standby.
- SeaweedFS stores uploaded blobs in a retained bucket with two-copy placement.
- Application requests total 512 MiB RAM; PostgreSQL requests total 768 MiB.
  Limits allow headroom. Retention defaults to 30 days; cold storage is disabled.
- The existing VM placement is not physical-host HA. Losing the host containing
  two control-plane VMs loses cluster quorum. This deployment does not change it.

The sync hook runs upstream migrations, creates the PostgreSQL cache table and
partitions, and idempotently configures the organization's Dex provider.
Application pods skip startup migrations. Uploaded files are read server-side
through the internal S3 endpoint; the bucket is not public.

## Backups

The shared K8up schedule backs up daily to the encrypted Restic repository
`sgfdevs-on-prem-k3s-backups/glitchtip`. For an on-demand backup:

```bash
argo submit -n glitchtip --from workflowtemplate/glitchtip-backup
```

Each streamed tar archive contains a custom-format PostgreSQL dump, metadata
including the application's SECRET_KEY, and every S3 blob referenced by the
same exported PostgreSQL snapshot. Blob size/checksum mismatches or missing
objects fail the backup. This avoids depending on local application disks and
does not pause ingestion. Backups need temporary disk space for the database
dump. Inspect K8up failures as the database grows.

## Restore

Restore is an explicit maintenance operation, not automatic startup behavior.
Use the same GlitchTip version as the backup. Keep the application paused if any
step fails. Do not print or commit the archive metadata; it contains SECRET_KEY.

1. Restore the chosen snapshot with Restic, using the B2 credentials and
   `glitchtip-k8up-repo-password`. Use `restic ls <snapshot>` to locate the
   streamed `.tar` file.
2. Validate the archive using `restore.py <archive> --check-only`. Run the
   scripts with PostgreSQL 18 clients, Python, boto3, and psycopg2, using the same
   config/secrets as the PreBackupPod. Its `backupCommand` lists the required
   Alpine packages. Ensure enough staging space for the extracted archive.
3. Before replacing data, pause Argo CD reconciliation:
   `kubectl -n argocd annotate application glitchtip argocd.argoproj.io/skip-reconcile=true --overwrite`.
   Disable the K8up schedule temporarily, wait for existing backups to complete,
   scale the GlitchTip Deployment to zero, and wait until its pods are deleted.
4. The restore script checks application version, SECRET_KEY, archive members,
   dump checksum, and blob checksums before writing anything. Recover the
   original SECRET_KEY into OpenBao if it differs, allow External Secrets to
   refresh, and then rerun validation. Do not simply generate another key.
5. Run `restore.py <archive> --confirm "RESTORE glitchtip"`. It refuses to
   proceed while other application database connections exist. It uploads the
   backed-up blobs, leaves newer unreferenced objects alone, and replaces the
   database in one PostgreSQL transaction.
6. Remove the Argo CD skip-reconcile annotation and sync the application. The
   sync hook reruns migrations before the Deployment resumes and restores the
   declared backup schedule. Verify SSO login, existing issues, and sourcemaps.

The CNPG resource is protected against Argo CD pruning/deletion. The S3 bucket
uses Retain. These protections and replication do not replace off-cluster backups.
