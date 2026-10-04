"""Shared synthetic Argo v3.5.3 Application fixtures for Lua and Ansible gates.

ResourceResult fields follow pkg/apis/application/v1alpha1/types.go. Hooks have
hookType/hookPhase, not a resource status of Synced. No live API calls.
"""
import copy

FINGERPRINT = "a" * 40


def application(domain):
    return {"metadata": {"annotations": {
        domain + "/health-gate": "true", domain + "/issuer-operation-gate": "true",
        domain + "/issuer-input-fingerprint": FINGERPRINT}},
        "status": {"sync": {"status": "Synced", "revision": "git-sha-old"},
                   "health": {"status": "Healthy"},
                   "operationState": {"phase": "Succeeded", "syncResult": {
                       "revision": "git-sha-old", "resources": [{
                           "group": "batch", "version": "v1", "kind": "Job",
                           "namespace": "k8s-oidc", "name": "oidc-public-readiness-" + FINGERPRINT,
                           "hookType": "PostSync", "hookPhase": "Succeeded", "syncPhase": "PostSync"}]}}}}


def cases(domain):
    base = application(domain)
    yield "matching full hook sync", base, "Healthy"
    obj = copy.deepcopy(base)
    obj["status"]["sync"]["revision"] = "git-sha-new-unrelated-commit"
    yield "unchanged inputs at newer compared Git SHA", obj, "Healthy"
    obj = copy.deepcopy(base)
    obj["metadata"]["annotations"][domain + "/issuer-input-fingerprint"] = "b" * 40
    yield "changed inputs with stale successful hook", obj, "Progressing"
    obj = copy.deepcopy(base)
    obj["status"]["operationState"]["syncResult"]["resources"] = [{
        "group": "apps", "version": "v1", "kind": "Deployment", "namespace": "k8s-oidc",
        "name": "oidc-discovery-proxy", "status": "Synced", "syncPhase": "Sync"}]
    yield "selective deployment-only successful sync after failed public check", obj, "Progressing"
    for field, wrong in [("group", "apps"), ("kind", "Deployment"), ("namespace", "argocd"),
                         ("name", "oidc-public-readiness-" + "b" * 40), ("name", "oidc-public-readiness"),
                         ("hookType", "PreSync"), ("hookPhase", "Running"), ("hookPhase", "Failed")]:
        obj = copy.deepcopy(base)
        obj["status"]["operationState"]["syncResult"]["resources"][0][field] = wrong
        yield "wrong hook " + field + " " + wrong, obj, "Progressing"
    for field in ["group", "kind", "namespace", "name", "hookType", "hookPhase"]:
        obj = copy.deepcopy(base)
        del obj["status"]["operationState"]["syncResult"]["resources"][0][field]
        yield "missing hook " + field, obj, "Progressing"
    for phase, expected in [("Running", "Progressing"), ("Failed", "Degraded"),
                            ("Error", "Degraded"), ("Terminating", "Progressing")]:
        obj = copy.deepcopy(base)
        obj["status"]["operationState"]["phase"] = phase
        yield phase + " operation with successful resource result", obj, expected
    for field in ["operationState", "sync", "health"]:
        obj = copy.deepcopy(base)
        del obj["status"][field]
        yield "missing " + field, obj, "Progressing"
    for field in ["syncResult", "resources"]:
        obj = copy.deepcopy(base)
        container = obj["status"]["operationState"]
        if field == "resources":
            container = container["syncResult"]
        del container[field]
        yield "missing " + field, obj, "Progressing"
    for pending in [{}, {"sync": {}}]:
        obj = copy.deepcopy(base)
        obj["operation"] = pending
        yield "pending operation " + str(pending), obj, "Progressing"
    for fingerprint in [None, "", "too-short", 123]:
        obj = copy.deepcopy(base)
        obj["metadata"]["annotations"][domain + "/issuer-input-fingerprint"] = fingerprint
        yield "invalid fingerprint " + str(fingerprint), obj, "Progressing"
    for field, wrong in [("sync", "OutOfSync"), ("health", "Progressing"), ("health", "Degraded")]:
        obj = copy.deepcopy(base)
        obj["status"][field]["status"] = wrong
        yield "issuer " + wrong, obj, "Progressing"
    obj = copy.deepcopy(base)
    obj["status"]["operationState"]["syncResult"]["resources"] = []
    yield "empty hook results", obj, "Progressing"
    obj = copy.deepcopy(base)
    del obj["metadata"]["annotations"][domain + "/issuer-operation-gate"]
    del obj["status"]["operationState"]
    yield "ordinary healthy gate without issuer opt-in", obj, "Healthy"
