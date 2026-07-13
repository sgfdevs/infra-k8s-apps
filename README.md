# infra-k8s-apps

Kubernetes desired state for the three-node SGF k3s cluster. Argo CD reconciles this repository from `ssh://git@github.com/sgfdevs/infra-k8s-apps.git`; Flux is not used.

## Architecture

- `src/k8s/bootstrap/operators/base`: cert-manager, CloudNativePG, External Secrets, K8up, Longhorn, and Prometheus CRDs.
- `src/k8s/bootstrap/operators/dependent`: OpenTelemetry, Reloader, and Valkey operators installed after the base layer.
- `src/k8s/bootstrap/projects`: restricted Argo CD projects for platform and application sources.
- `src/k8s/platform`: Argo CD Applications for cluster configuration, storage, identity, observability, and shared services.
- `src/k8s/apps`: an ApplicationSet that discovers application directories. No example workloads are shipped.

The platform includes Argo CD, cert-manager, External Secrets, Longhorn, SeaweedFS, CloudNativePG, Dex, oauth2-proxy, OpenBao, Headlamp, Grafana, Prometheus, Loki, Tempo, Thanos, Alloy, OpenTelemetry, K8up, and Prometheus Pushgateway. Workloads are spread across three nodes where the component supports replicas. Proxmox telemetry and dashboards are intentionally absent.

## Ingress And TLS

The existing public edge remains external to this repository. Public DNS and edge forwarding must send SNI traffic to the SGF Traefik nodes; TLS terminates in this cluster using the `letsencrypt-prod` ClusterIssuer. No private CA, trust-manager, node Tailscale, edge DNS, or public-edge configuration is managed here.

Public platform names are:

- `argocd.sgf.dev`
- `sso.sgf.dev`
- `auth.sgf.dev`
- `grafana.sgf.dev`
- `secrets.sgf.dev`
- `headlamp.sgf.dev`
- `longhorn.sgf.dev`
- `seaweedfs.sgf.dev`
- `traefik.sgf.dev`

Dex uses the SGF GitHub organization and limits loaded teams to `sgfdevs:platform-admins`. Argo CD and Grafana consume group claims for native authorization. OpenBao OIDC must bind its administrator policy to the same group during application configuration. Headlamp, Longhorn, SeaweedFS, and Traefik use the single oauth2-proxy deployment through a Traefik ForwardAuth middleware restricted to `sgfdevs:platform-admins`. Traefik does not trust client-supplied forwarded headers for this middleware.

## Bootstrap

Do not run these commands until all external prerequisites below exist.

1. Give the cluster nodes AWS access to the SGF SSM prefix and B2 backup parameters.
2. Install base operators: `kubectl apply -k src/k8s/bootstrap/operators/base`.
3. Wait for base operators and CRDs to become ready.
4. Install dependent operators: `kubectl apply -k src/k8s/bootstrap/operators/dependent`.
5. Install Argo CD: `kubectl apply -k src/k8s/platform/argocd/install`.
6. Configure Argo CD repository SSH credentials for this private GitHub repository.
7. Install projects: `kubectl apply -k src/k8s/bootstrap/projects`.
8. Seed platform Applications: `kubectl apply -k src/k8s/platform`.
9. Seed application discovery: `kubectl apply -k src/k8s/apps`.

Argo CD then owns reconciliation. Review sync waves and application health before allowing automated recovery on a rebuilt cluster.

## External Prerequisites

### GitHub OAuth And Teams

- Create a GitHub OAuth application owned by `sgfdevs` with callback `https://sso.sgf.dev/callback`.
- Store its client ID and secret in SSM at `/vm-workloads/sgfdevs/infra-vm-workloads/dex-github-oauth-client-id` and `/vm-workloads/sgfdevs/infra-vm-workloads/dex-github-oauth-client-secret`.
- Create the `platform-admins` team in the `sgfdevs` organization and grant intended operators membership.
- Authorize the OAuth application for organization access. Private organization membership must be visible to the application for Dex group resolution.
- Populate `/vm-workloads/sgfdevs/infra-vm-workloads/dex-client-secrets` as a JSON object containing `argocdClientSecret`, `grafanaClientSecret`, `oauth2ProxyClientSecret`, and `openbaoClientSecret`.
- Store a valid oauth2-proxy cookie secret at `/vm-workloads/sgfdevs/infra-vm-workloads/oauth2-proxy-cookie-secret`.

### AWS SSM And IAM

- Provide read access only to `/vm-workloads/sgfdevs/infra-vm-workloads/*` in the configured AWS region.
- Store the 44-byte base64 OpenBao static seal key at `/vm-workloads/sgfdevs/infra-vm-workloads/openbao-unseal-key`.
- Store B2 credentials at `/vm-workloads/sgfdevs/infra-vm-workloads/backups/b2-account-id` and `/vm-workloads/sgfdevs/infra-vm-workloads/backups/b2-account-key`.
- Store the OpenBao restic repository password at `/vm-workloads/sgfdevs/infra-vm-workloads/backups/openbao/restic-password`.
- Supply every additional key referenced by the SeaweedFS and Thanos ExternalSecrets before sync.

### Backblaze B2

- Create the independent bucket `sgfdevs-vm-workloads-backups`.
- Restrict the supplied B2 application key to that bucket with list, read, write, and delete capabilities required by restic/K8up retention.
- The shared application repository uses path `app`; OpenBao always uses path `openbao`.

### DNS And Edge

- Publish all platform names listed above and route them through the existing edge to the three SGF Traefik nodes.
- Preserve HTTP reachability for ACME HTTP-01 and SNI passthrough for HTTPS.
- Ensure edge health checks and firewall rules do not depend on LZ Tailscale or edge-DNS configuration.

## Backups And Recovery

K8up labels backup metrics with cluster `sgfdevs` and pushes them to Prometheus Pushgateway. Shared application backups use the base schedule and retention policy. OpenBao streams logical Raft snapshots to `b2:sgfdevs-vm-workloads-backups:openbao`, sets `RESTIC_CACHE_DIR` to a writable path, and restores the newest snapshot only when the local Raft state is uninitialized. Existing state is never overwritten automatically.

After Dex is available, configure OpenBao's OIDC auth method with issuer `https://sso.sgf.dev`, client `openbao`, a `groups` claim, and a role bound to `sgfdevs:platform-admins`. This application-level policy is intentionally not embedded in cluster bootstrap manifests.

## Validation

Render every local Kustomize root before merge. The repository must contain no Flux resources, LZ domains or repository references, private-CA dependencies, example workloads, or Proxmox telemetry. Validation is render-only and must not apply resources to a cluster.
