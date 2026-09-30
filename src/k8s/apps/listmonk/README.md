# Listmonk

Fresh PostgreSQL 18 database, ClusterIP access only, and daily encrypted database backups. No migration, public ingress, certificate, or DNS changes.

```sh
kubectl --context sgfdevs-k3s -n listmonk port-forward service/listmonk 9000:9000
```

Create the admin account on the first visit. SMTP and S3 settings live in Listmonk's database and are not configured by these manifests.

- S3 bucket: `sgfdevs-listmonk-uploads`, region `us-east-2`, private bucket type, empty bucket path, public URL `/uploads`. Leave both AWS key fields blank to use the pod-local IMDS sidecar at `169.254.169.254:80`.
- SMTP: `listmonk-smtp` contains the SES username, password, host, port, sender address, and configuration set. Use STARTTLS and the `X-SES-CONFIGURATION-SET: application-sgf-dev-listmonk` header.

The temporary uploads directory is an `emptyDir` for Listmonk's initial filesystem defaults. Do not upload media until S3 is configured. The network init container needs `NET_ADMIN`, but the metadata server and Listmonk run as non-root.
