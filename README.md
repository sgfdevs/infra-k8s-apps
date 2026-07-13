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

Dex uses the SGF GitHub organization and limits loaded teams to `sgfdevs:platform-admins`. Argo CD and Grafana consume group claims for native authorization. Headlamp, Longhorn, SeaweedFS, and Traefik use one oauth2-proxy deployment with distinct, per-application Traefik ForwardAuth middlewares currently restricted to `sgfdevs:platform-admins`. Traefik does not trust client-supplied forwarded headers, and oauth2-proxy trusts forwarded headers only from the SGF k3s pod CIDR.

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
- The client ID is configured in `src/k8s/platform/dex.yaml`; store its secret in SSM at `/vm-workloads/sgfdevs/infra-vm-workloads/dex-github-oauth-client-secret`.
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

- Create the independent bucket `sgfdevs-on-prem-k3s-backups`.
- On the first OpenBao deployment, recovery initializes `b2:sgfdevs-on-prem-k3s-backups:openbao` when it does not exist. Initialization must succeed with the configured credentials before fresh-cluster mode is selected. Existing repositories with invalid passwords and inaccessible B2 endpoints fail closed.
- Restrict the supplied B2 application key to that bucket with list, read, write, and delete capabilities required by restic/K8up retention.
- The shared application repository uses path `app`; OpenBao always uses path `openbao`.

### DNS And Edge

- Publish all platform names listed above and route them through the existing edge to the three SGF Traefik nodes.
- Preserve HTTP reachability for ACME HTTP-01 and SNI passthrough for HTTPS.
- Ensure edge health checks and firewall rules do not depend on LZ Tailscale or edge-DNS configuration.

## Backups And Recovery

K8up labels backup metrics with cluster `sgfdevs` and pushes them to Prometheus Pushgateway. Shared application backups use the base schedule and retention policy. OpenBao streams logical Raft snapshots to `b2:sgfdevs-on-prem-k3s-backups:openbao`, sets `RESTIC_CACHE_DIR` to a writable path, and restores the newest snapshot only when all three current Longhorn-backed PVCs are empty. A newly initialized or successfully queried repository with no snapshots permits first-time initialization; missing credentials, invalid credentials, existing-repository password errors, and network errors fail closed. Existing state is never overwritten automatically.

On the first deployment only, wait for `openbao-0` to run and initialize the otherwise intentionally uninitialized cluster exactly once with `kubectl -n openbao exec openbao-0 -- env BAO_ADDR=http://127.0.0.1:8200 bao operator init -recovery-shares=1 -recovery-threshold=1`. Securely retain the returned initial root token and recovery key; never rerun initialization or commit either value. The followers can join after pod 0 is initialized.

OpenBao OIDC does not work automatically after cluster bootstrap. After Dex and OpenBao initialization are complete, use the initial root token to create an administrator policy, enable the `oidc` auth method, configure issuer `https://sso.sgf.dev` with client ID `openbao` and its external client secret, and create an OIDC role whose `groups_claim` is `groups`, whose bound `groups` claim is `sgfdevs:platform-admins`, and whose token policy is the administrator policy. Include `https://secrets.sgf.dev/ui/vault/auth/oidc/oidc/callback` as an allowed redirect URI, test an administrator login, then revoke the initial root token. These post-init policy and auth resources are intentionally not managed by the Kubernetes manifests.

## Validation

Render every local Kustomize root before merge. The repository must contain no Flux resources, LZ domains or repository references, private-CA dependencies, example workloads, or Proxmox telemetry. Validation is render-only and must not apply resources to a cluster.
