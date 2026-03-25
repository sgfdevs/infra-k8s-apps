# infra-k8s-apps

Flux-managed Kubernetes manifests for sgfdevs workloads.

## Layout

```text
src/k8s/
├── apps/
│   └── hello-nginx/
├── bootstrap/
│   ├── config/
│   │   └── cert-manager-issuers/
│   └── controllers/
│       └── cert-manager/
├── flux/
└── kustomization.yaml
```

## Quickstart

```bash
kustomize build src/k8s/flux
kustomize build src/k8s/apps
```

## Notes

- `src/k8s/flux/kustomizations.yaml` defines Flux reconciliation order.
- `src/k8s/bootstrap/config/cert-manager-issuers/clusterissuer.yaml` uses a placeholder email. Update it before production certificate issuance.
