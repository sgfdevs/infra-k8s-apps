# Plausible

A new private Plausible CE instance. It does not reuse the databases, keys, or hostname routing of the instance on bighead.

- Plausible CE v3.2.1, one replica with Recreate updates because analytics session caches are process-local.
- CloudNativePG PostgreSQL 18.6, two instances on different nodes with 10Gi local-path volumes.
- ClickHouse 24.12.6.70, one non-root instance with a 10Gi Longhorn volume. No Keeper or new operator.
- Requests total 450m CPU and 2Gi memory, excluding temporary initialization and backup pods.
- Application and ClickHouse images are digest-pinned. Application keys, ClickHouse authentication, and SES SMTP credentials come from OpenBao through External Secrets.
- No public ingress, certificate, LoadBalancer, NodePort, or DNS change.

## Private access

```sh
kubectl --context sgfdevs-k3s -n plausible port-forward service/plausible 18000:8000
```

Open `http://localhost:18000` and claim the initial administrator account. Email verification is enabled and subsequent registration is invite-only. The configured BASE_URL matches this URL. Before adding ingress, update BASE_URL to the intended public HTTPS URL.

The install sync hook creates any missing databases and applies the application's ordered PostgreSQL/ClickHouse schema updates before the application starts. It does not import existing data. Readiness checks `/api/health`; liveness only checks the listening socket so database failover does not trigger application restarts.

The image's bundled country geolocation database is used. City-level MaxMind configuration can be added separately.

## Backups and recovery

The shared K8up schedule retains backups in the encrypted B2 repository `sgfdevs-on-prem-k3s-backups/plausible`:

- PostgreSQL custom-format dump from `plausible-postgres`.
- ClickHouse native ZIP backup streamed from the ClickHouse pod, with temporary files removed afterward.
- SECRET_KEY_BASE and TOTP_VAULT_KEY archive from `plausible-keys`.

Raw database PVC copies are excluded. The application PVC only holds regenerable cache and temporary files. The restic repository password is stored separately in OpenBao at `applications/plausible/backup`; preserve it in the OpenBao backup.

PostgreSQL and ClickHouse backups are independently consistent, not a single cross-database transaction. For recovery, select dumps from the same scheduled run and inspect their timestamps and paths with `restic snapshots` and `restic ls`. Test restoration into empty isolated databases before replacing a live instance. Use `pg_restore --exit-on-error --single-transaction --no-owner --no-privileges` for PostgreSQL and ClickHouse `RESTORE DATABASE ... AS ... FROM Disk('backups', 'archive.zip')` after staging the ZIP in `/var/lib/clickhouse/backups`.

A live restore must suspend Argo reconciliation, stop Plausible ingestion, and prevent concurrent scheduled backups first. Restore the original application keys along with the databases before resuming. Do not rotate the OpenTofu secret version as part of a routine deployment or restore.

Longhorn storage replication permits rescheduling the single ClickHouse instance; it is not continuous database availability. Recreate application updates cause a brief outage and can interrupt in-flight analytics sessions. PostgreSQL local-path volumes cannot be expanded in place.
