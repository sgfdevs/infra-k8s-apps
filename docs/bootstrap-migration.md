# Bootstrap ownership migration

Existing clusters must use three separately reviewed phases. A branch is not evidence that its checkpoint has happened. Do not collapse this series into one automated rollout.

## Preparation

The current bootstrap-config owner keeps every AWS-backed resource. Each moving resource has temporary `argocd.argoproj.io/sync-options: Prune=false`. The future bootstrap-aws-config child points to an empty, stable configuration-aws directory and deliberately allows an empty sync. Existing platform waves and issuer behavior stay unchanged.

Before transfer, an operator must observe a successful preparation reconcile, inspect every moving identity in `tests/bootstrap-inventory.json` for live Prune=false, and confirm the empty child exists and has reconciled. Record resource UIDs, target Secret UIDs and Argo tracking annotations without reading Secret data. Stop if a resource is missing or annotations have not reached it.

## Transfer

Transfer retains protection while changing desired ownership to bootstrap-aws-config. Foundation keeps admission, ingress, certificates, middleware. It contains no ESO resources. New waves are foundation -3, issuer -2, AWS configuration -1, followed by existing services. Reader ServiceAccounts and RBAC precede stores, direct SSM ExternalSecrets and cache splits.

Before cleanup, compare all recorded resource and target Secret UIDs. Confirm new Argo tracking, actual store and ExternalSecret Ready conditions, issuer PostSync success for the current revision, and unchanged ingress availability. A Synced parent alone is insufficient. Do not delete or recreate an ExternalSecret or target Secret, force replacement, or enable shared-resource rejection. Keep transfer and cleanup draft until their own preceding checkpoint has been observed.

## Cleanup and recovery

Remove protection only from the reviewed transferred identities after adoption. Require both configuration Applications Synced and Healthy. Never use automated merge across these phases.

If adoption fails, keep Prune=false and stop. Repair auth, conditions or tracking without deletion. To restore the old owner, first protect the new owner's moving resources, confirm protection is live, then restore their original desired paths and remove them from the new desired tree. Confirm unchanged UIDs and old tracking before removing protection. Do not blindly revert cleanup or prune resources to force adoption.

## Cold bootstrap limits

The VM bootstrap seeds missing ingress credentials before operators and installs admission expansion before ESO creates its ServiceAccount. Seeds have no Argo tracking or controller ownerReference. ESO v2.11.0 with creationPolicy Owner updates and adopts a Secret without a conflicting controller owner; it rejects conflicting ownership and may replace extra keys. Do not change Owner to Merge.

The issuer needs working networking, Headscale keys, tunnel credentials and TLS. Its public unauthenticated check is not an AWS authentication probe. Store and ExternalSecret readiness follow it. A healthy-cluster rerun does not prove empty-cluster recovery. A later isolated synthetic ESO controller adoption/conflicting-owner test and a genuinely empty-cluster bootstrap remain required.

Offline tests render each phase with `kubectl kustomize` and compare identities and runtime specs against the original inventory. They cannot prove live UID preservation or controller adoption.
