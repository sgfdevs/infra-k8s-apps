"""Execute the installed Lua assessments with synthetic Application/ESO objects."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def lua_value(value):
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, dict):
        return "{" + ",".join("[" + lua_value(k) + "]=" + lua_value(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "{" + ",".join(lua_value(v) for v in value) + "}"
    return str(value)


class Health(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = shutil.which("luajit") or shutil.which("lua")
        if not cls.runner:
            raise RuntimeError("Lua interpreter required for health tests")
        paths = list(ROOT.glob("src/k8s/platform/argocd/install/patches/argocd-cm.yaml"))
        paths += list(ROOT.glob("src/ansible/roles/bootstrap_argocd/files/argocd-application-health.yaml"))
        cls.data = yaml.safe_load(paths[0].read_text())["data"]
        cls.script = cls.data["resource.customizations.health.argoproj.io_Application"]
        cls.domain = "infra.levizitting.com" if "infra.levizitting.com/health-gate" in cls.script else "infra.sgf.dev"

    def assess(self, script, obj):
        source = "obj=" + lua_value(obj) + "\nlocal function assess()\n" + script + "\nend\nprint(assess().status)"
        return subprocess.check_output([self.runner, "-"], input=source, text=True).strip()

    def application(self):
        return {"metadata": {"annotations": {
            self.domain + "/health-gate": "true", self.domain + "/issuer-operation-gate": "true"}},
            "status": {"sync": {"status": "Synced", "revision": "current"},
                       "health": {"status": "Healthy"},
                       "operationState": {"phase": "Succeeded", "syncResult": {"revision": "current"}}}}

    def test_current_hook_success(self):
        self.assertEqual(self.assess(self.script, self.application()), "Healthy")

    def test_pending_failed_stale_missing_operations(self):
        for phase, expected in [("Running", "Progressing"), ("Failed", "Degraded"), ("Error", "Degraded")]:
            obj = self.application()
            obj["status"]["operationState"]["phase"] = phase
            self.assertEqual(self.assess(self.script, obj), expected)
        obj = self.application()
        obj["status"]["operationState"]["syncResult"]["revision"] = "stale"
        self.assertEqual(self.assess(self.script, obj), "Progressing")
        obj = self.application()
        del obj["status"]["operationState"]
        self.assertEqual(self.assess(self.script, obj), "Progressing")
        obj = self.application()
        obj["operation"] = {"sync": {}}
        self.assertEqual(self.assess(self.script, obj), "Progressing")

    def test_ordinary_gates_unchanged(self):
        obj = self.application()
        del obj["metadata"]["annotations"][self.domain + "/issuer-operation-gate"]
        del obj["status"]["operationState"]
        self.assertEqual(self.assess(self.script, obj), "Healthy")
        obj["status"]["sync"]["status"] = "OutOfSync"
        self.assertEqual(self.assess(self.script, obj), "Progressing")
        obj["metadata"]["annotations"] = {}
        self.assertEqual(self.assess(self.script, obj), "Healthy")

    def test_eso_requires_actual_ready(self):
        for kind in ["ExternalSecret", "SecretStore", "ClusterSecretStore"]:
            script = self.data["resource.customizations.health.external-secrets.io_" + kind]
            obj = {"metadata": {"generation": 2}}
            self.assertEqual(self.assess(script, obj), "Progressing")
            for status, expected in [("True", "Healthy"), ("False", "Degraded"), ("Unknown", "Progressing")]:
                obj["status"] = {"conditions": [{"type": "Ready", "status": status}]}
                self.assertEqual(self.assess(script, obj), expected)
            obj["status"] = {"conditions": [{"type": "Ready", "status": "True", "observedGeneration": 1}]}
            self.assertEqual(self.assess(script, obj), "Progressing")


if __name__ == "__main__":
    unittest.main()
