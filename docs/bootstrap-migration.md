# Bootstrap ownership migration

Existing clusters must use three separately reviewed phases. A branch is not evidence that its checkpoint has happened. Do not collapse this series into one automated rollout.

## Preparation

The current bootstrap-config owner keeps every AWS-backed resource. Each moving resource has temporary `argocd.argoproj.io/sync-options: Prune=false`. The future bootstrap-aws-config child points to an empty, stable configuration-aws directory and deliberately allows an empty sync. Existing platform waves and issuer behavior stay unchanged.

Before transfer, an operator must observe a successful preparation reconcile, inspect every moving identity in `tests/bootstrap-inventory.json` for live Prune=false, and confirm the empty child exists and has reconciled. Record resource UIDs, target Secret UIDs and Argo tracking annotations without reading Secret data. Stop if a resource is missing or annotations have not reached it.

## Transfer

Transfer retains protection while changing desired ownership to bootstrap-aws-config. Foundation keeps admission, ingress, certificates, middleware. It contains no ESO resources. New waves are foundation -3, issuer -2, AWS configuration -1, followed by existing services. Reader ServiceAccounts and RBAC precede stores, direct SSM ExternalSecrets and cache splits.

Before cleanup, compare all recorded resource and target Secret UIDs. Confirm new Argo tracking, actual store and ExternalSecret Ready conditions, issuer PostSync success for the expected input fingerprint, and unchanged ingress availability. A Synced parent alone is insufficient. Do not delete or recreate an ExternalSecret or target Secret, force replacement, or enable shared-resource rejection. Keep transfer and cleanup draft until their own preceding checkpoint has been observed.

## Cleanup and recovery

Remove protection only from the reviewed transferred identities after adoption. Require both configuration Applications Synced and Healthy. Never use automated merge across these phases.

If adoption fails, keep Prune=false and stop. Repair auth, conditions or tracking without deletion. To restore the old owner, first protect the new owner's moving resources, confirm protection is live, then restore their original desired paths and remove them from the new desired tree. Confirm unchanged UIDs and old tracking before removing protection. Do not blindly revert cleanup or prune resources to force adoption.

## Public issuer gate maintenance

The issuer gate uses input identity, not the repository-wide Git SHA. A newer main commit with unchanged issuer inputs can keep the last successful public hook. A changed input must produce a new named hook and a normal Deployment annotation change, so Argo sees OutOfSync and performs a full sync.

After editing issuer inputs, run `python scripts/issuer-fingerprint.py --update` from the repository root with the existing test PyYAML environment, and commit all three updated bindings. CI's fingerprint tests recompute the digest and reject stale bindings. The fingerprint is the first 40 lowercase hexadecimal characters of SHA-256 over UTF-8 compact JSON, with sorted object keys and ASCII escaping. The JSON is a path-sorted list of repository-relative path and content pairs. It includes `src/k8s/platform/k8s-oidc.yaml` and every file under `services/k8s-oidc` except generated `__pycache__` files. YAML content is the parsed document list; other files, including the public checker, use their exact text. This covers proxy deployment/image/arguments, ServiceAccount/RBAC, kubeconfig, Service, namespace, public ingress/certificate/middleware, Kustomize generators, checker, Job image/DNS/timeouts and the Application source/destination.

Only the Application and Deployment's generated `issuer-input-fingerprint` annotations are removed before hashing, with empty annotation maps removed. The public Job's generated name is normalized to `oidc-public-readiness`. No other manifest field is excluded. Kustomize inputs must stay inside this directory; unsupported Kustomize input fields fail closed until coverage is extended.

The checked-in identifier binds the Application annotation, Deployment annotation and `oidc-public-readiness-<fingerprint>` Job name. The Deployment stamp is ordinary managed metadata, not a hook or a change to the proxy Pod spec. It forces a desired-resource diff even if only hook inputs changed.

Both Lua and Ansible require Application Synced and Healthy, no pending operation, operationState.phase Succeeded, and a matching entry in operationState.syncResult.resources. The entry must have group batch, kind Job, namespace k8s-oidc, the exact input-bound name, hookType PostSync and hookPhase Succeeded. Hook resource status is not checked because Argo leaves that field empty for hooks. These fields follow [Argo v3.5.3 ResourceResult](https://github.com/argoproj/argo-cd/blob/v3.5.3/pkg/apis/application/v1alpha1/types.go). A successful selective sync without that hook result cannot satisfy the bootstrap gate. Admin selective sync remains available, but a full issuer sync is needed afterward. The gate does not treat an old Job object or any historical successful operation as evidence for changed inputs.

## Cold bootstrap limits

The VM bootstrap seeds missing ingress credentials before operators and installs admission expansion before ESO creates its ServiceAccount. Seeds have no Argo tracking or controller ownerReference. ESO v2.11.0 with creationPolicy Owner updates and adopts a Secret without a conflicting controller owner; it rejects conflicting ownership and may replace extra keys. Do not change Owner to Merge.

The issuer needs working networking, Headscale keys, tunnel credentials and TLS. Its public unauthenticated check is not an AWS authentication probe. Store and ExternalSecret readiness follow it. A healthy-cluster rerun does not prove empty-cluster recovery. A later isolated synthetic ESO controller adoption/conflicting-owner test and a genuinely empty-cluster bootstrap remain required.

Offline tests render each phase with `kubectl kustomize` and compare identities and runtime specs against the original inventory. They cannot prove live UID preservation or controller adoption.
