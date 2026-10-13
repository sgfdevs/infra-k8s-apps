"""Offline rendered ownership contract. Never contacts a Kubernetes server."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "src/k8s/platform"
BASELINE = json.loads((ROOT / "tests/bootstrap-inventory.json").read_text())
PHASE = int((ROOT / "tests/bootstrap-phase").read_text())


def identity(doc):
    meta = doc["metadata"]
    return "/".join([doc["apiVersion"], doc["kind"], meta.get("namespace", ""), meta["name"]])


def digest(doc):
    doc = copy.deepcopy(doc)
    meta = doc["metadata"]
    annotations = meta.get("annotations", {})
    for key in ["argocd.argoproj.io/sync-wave", "argocd.argoproj.io/sync-options"]:
        annotations.pop(key, None)
    if not annotations:
        meta.pop("annotations", None)
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def render(path):
    return [d for d in yaml.safe_load_all(subprocess.check_output(
        ["kubectl", "kustomize", str(path)], text=True)) if d]


class Ownership(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.foundation = {identity(d): d for d in render(PLATFORM / "configuration")}
        cls.aws = {identity(d): d for d in render(PLATFORM / "configuration-aws")}
        cls.apps = {d["metadata"]["name"]: d for d in render(PLATFORM)}

    def test_identities_and_runtime_specs(self):
        all_docs = self.foundation | self.aws
        self.assertEqual(len(all_docs), len(self.foundation) + len(self.aws), "Shared desired owner")
        self.assertEqual(set(BASELINE), set(all_docs))
        for key, old in BASELINE.items():
            self.assertEqual(old["sha256"], digest(all_docs[key]), key)
            expected_owner = self.aws if old["moving"] and PHASE > 1 else self.foundation
            self.assertIn(key, expected_owner)

    def test_prune_protection(self):
        for key, old in BASELINE.items():
            doc = (self.foundation | self.aws)[key]
            options = doc["metadata"].get("annotations", {}).get("argocd.argoproj.io/sync-options", "")
            self.assertEqual("Prune=false" in options, old["moving"] and PHASE < 3, key)

    def test_child_preexists_and_tracks_stable_path(self):
        app = self.apps["bootstrap-aws-config"]
        self.assertEqual(app["spec"]["source"]["path"], "src/k8s/platform/configuration-aws")
        self.assertEqual(app["spec"]["source"]["targetRevision"], "main")
        self.assertNotIn("FailOnSharedResource=true", app["spec"]["syncPolicy"].get("syncOptions", []))
        if PHASE == 1:
            self.assertFalse(self.aws)
            self.assertEqual(self.apps["bootstrap-config"]["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "1")
            self.assertEqual(self.apps["k8s-oidc"]["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "2")
        else:
            self.assertFalse(any(d["kind"] in {"ExternalSecret", "SecretStore", "ClusterSecretStore"} for d in self.foundation.values()))
            for name, wave in [("bootstrap-config", "-3"), ("k8s-oidc", "-2"), ("bootstrap-aws-config", "-1")]:
                self.assertEqual(self.apps[name]["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], wave)

    def test_store_graph(self):
        if PHASE == 1:
            return
        stores = {(d["kind"], d["metadata"].get("namespace", ""), d["metadata"]["name"]): d
                  for d in self.aws.values() if d["kind"] in {"SecretStore", "ClusterSecretStore"}}
        for doc in self.aws.values():
            wave = int(doc["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"])
            if doc["kind"] in {"ServiceAccount", "Role", "RoleBinding"}:
                self.assertEqual(wave, -2)
            elif doc["kind"] in {"SecretStore", "ClusterSecretStore"}:
                self.assertEqual(wave, 0)
            elif doc["kind"] == "ExternalSecret":
                ref = doc["spec"]["secretStoreRef"]
                namespace = doc["metadata"]["namespace"] if ref["kind"] == "SecretStore" else ""
                store = stores[ref["kind"], namespace, ref["name"]]
                self.assertLess(int(store["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]), wave)
                self.assertEqual(wave, 2 if ref["name"] == "cache-k8s" else 1)
                self.assertEqual(doc["spec"]["target"].get("creationPolicy", "Owner"), "Owner")


if __name__ == "__main__":
    unittest.main()
