# Bootstrap ownership migration

Existing clusters must use three separately reviewed phases. Do not collapse this series into one automated rollout. A local branch or a healthy-cluster rerun is not evidence that a checkpoint has happened.

## Preparation

The current bootstrap-config owner keeps every AWS-backed resource. Each moving resource has temporary `argocd.argoproj.io/sync-options: Prune=false`. The future bootstrap-ingress-config and bootstrap-aws-config children point to empty, stable configuration-ingress and configuration-aws directories and allow empty syncs. The ingress child has wave -4 and a health gate. Existing foundation and issuer waves stay unchanged in this phase.

Before transfer, observe a successful preparation reconcile, inspect every moving identity in `tests/bootstrap-inventory.json` for live Prune=false, and confirm both empty children have reconciled. Record resource UIDs, target Secret UIDs and Argo tracking annotations without reading Secret data. Stop if a resource is missing or protection has not reached it.

## Credential prerequisite and merge order

1. Merge and apply AWS-core's dedicated sgfdevs-k3s-bootstrap-reader user and exact-path GetParameter policy. Do not change runtime roles, trust or cross-account inputs. An operator provisions the key outside Terraform and stores it as SecureString at /vm-workloads/sgfdevs/infra-vm-workloads/bootstrap-aws/access-key-id and /vm-workloads/sgfdevs/infra-vm-workloads/bootstrap-aws/secret-access-key in us-east-2. Never put keys in Terraform state, Git, outputs or terminal logs.
2. Merge the VM bootstrap change that retrieves those parameters with decryption and creates only kube-system/bootstrap-aws-credentials, with keys access-key-id and secret-access-key. Its create-only helper leaves a complete Secret untouched and fails on an incomplete Secret. Keep SGF SeaweedFS missing-only seeds separate.
3. Merge Kubernetes preparation and observe its checkpoint before merging transfer. Keep transfer and cleanup draft until their preceding live checkpoints have passed.
4. Merge transfer, reconcile, and observe the adoption checkpoint below. Only then merge cleanup.

This sequence supports healthy legacy reruns during preparation. Old main's JWT ingress stores do not support cold recovery merely because the new VM credential Secret exists.

## Transfer

Transfer retains protection while changing ownership. bootstrap-ingress-config at wave -4 owns the permanent namespace-local bootstrap-aws-ssm SecretStore and the existing cloudflared-sgfdevs-token, cloudflared-opensgf-token and crowdsec-bouncer-key ExternalSecrets. These are two Cloudflare tokens plus the bouncer, three existing identities and three unchanged targets. Store wave 0 precedes ExternalSecret wave 1. Hourly reconciliation and target creationPolicy Owner remain enabled.

The static store uses ParameterStore in us-east-2 and direct secretRef references to bootstrap-aws-credentials. It has no JWT or assume-role path. The credential Secret is not an ESO target, not in the normal cache and not Argo-owned. Static access remains restricted to the two tunnel paths and crowdsec-traefik-bouncer-key under /vm-workloads/sgfdevs/infra-vm-workloads.

Foundation at wave -3 keeps admission, ingress, certificates and middleware, but no ESO resources. Issuer is wave -2, JWT AWS configuration -1, then apps. Reader ServiceAccounts and RBAC precede JWT stores, direct ExternalSecrets and cache splits. lz-headscale and traefik-tailnet-auth remain cross-account JWT-authenticated in the later AWS configuration.

Foundation owns HelmChartConfig, not the Traefik Deployment. Do not wait for whole Traefik pod readiness or tailnet connectivity before issuer. A missing tailnet auth Secret leaves the Tailscale container and pod NotReady while Traefik and both Cloudflared containers can start; preserve Tailscale probes and do not claim tailnet health. Tunnel origins use localhost. Public OIDC checking uses public DNS and no credentials. cert-manager HTTP01 self-checks also use public resolvers rather than private split DNS.

Before cleanup, compare every recorded resource and target Secret UID. Confirm new Argo tracking and real Ready conditions for the early static store, all three ingress ExternalSecrets and later JWT stores/ExternalSecrets. Confirm issuer PostSync success for the current rendered input fingerprint, matching live Deployment and Job, and unchanged public ingress availability. A Synced parent alone is insufficient. Do not delete or recreate an ExternalSecret or target Secret, force replacement, or enable shared-resource rejection.

## Cold bootstrap checkpoints

VM bootstrap must prepare AWS runtime and admission expansion, seed only AWS credentials for ingress, install Argo and operators, then apply platform. Wait for the early static store and all three ingress ExternalSecrets before foundation CA/certificate prerequisites. Do not wait for foundation before early credentials reconcile. Do not add a Traefik pod or tailnet gate.

After foundation prerequisites, require the matching public issuer hook, then actual JWT AWS store and ExternalSecret Ready conditions before apps. Admission expansion must precede ESO ServiceAccount creation. Healthy legacy reruns are supported; old main is not a cold-recovery implementation. Offline checks cannot prove live UID preservation, controller adoption or empty-cluster recovery.

ESO creationPolicy Owner remains unchanged. Do not replace it with Merge. Existing target Secrets with conflicting controller ownership need operator investigation, not deletion.

## Cleanup, rotation and recovery

Remove Prune=false only after adoption. Require all three configuration Applications Synced and Healthy and repeat the UID and Ready-condition checks. Never use automated merge across these phases.

If adoption fails, keep Prune=false and stop. Repair credentials, conditions or tracking without deletion. To restore the old owner, first protect the new owner's moving resources and confirm protection is live, then restore their original desired paths and remove them from the new desired tree. Confirm unchanged UIDs and old tracking before removing protection. Do not blindly revert cleanup or prune to force adoption.

For rotation, provision a replacement operator-managed key with the same restricted policy, update both SecureString credential parameters through a secure process, then deliberately update the complete Kubernetes credential Secret through a secure operator procedure. Ansible's create-only helper does not rotate it. Observe store and all three ExternalSecret Ready conditions and continuing public ingress before disabling the old key. Do not expose secret values in commands or output. On partial failure, retain the working key and stop; do not delete the credential or target Secrets.
