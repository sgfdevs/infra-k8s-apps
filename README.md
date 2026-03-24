# infra-k8s-apps

Flux-managed Kubernetes manifests for sgfdevs workloads.

## Layout

```text
src/k8s/
├── apps/
│   └── hello-nginx/
├── flux/
└── infrastructure/
    ├── cert-manager/
    └── cert-manager-issuers/
```

## Quickstart

```bash
kustomize build src/k8s/flux
kustomize build src/k8s/apps
```

## Notes

- `src/k8s/flux/kustomizations.yaml` defines Flux reconciliation order.
- `src/k8s/infrastructure/cert-manager-issuers/clusterissuer.yaml` uses a placeholder email. Update it before production certificate issuance.
