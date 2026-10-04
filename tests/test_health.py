"""Execute the installed Lua assessments and VM wait expressions on shared cases."""
import importlib.util
import json
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml

from issuer_gate_cases import application, cases

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "src/ansible/roles/bootstrap_argocd"


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
        if ROLE.exists():
            from jinja2 import Environment, StrictUndefined
            cls.wait = yaml.safe_load((ROLE / "tasks/wait-application.yml").read_text())[0]
            cls.annotation = yaml.safe_load((ROLE / "defaults/main.yml").read_text())["bootstrap_argocd_issuer_operation_annotation"]
            spec = importlib.util.spec_from_file_location("bootstrap_issuer", ROLE / "filter_plugins/bootstrap_issuer.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            cls.env = Environment(undefined=StrictUndefined)
            cls.env.filters["from_json"] = json.loads
            cls.env.filters.update(module.FilterModule().filters())

    def assess(self, script, obj):
        # Argo's default sandbox lacks the string/math/io/package libraries.
        source = ("obj=" + lua_value(obj) + "\nlocal function assess()\n"
                  + "string=nil; math=nil; io=nil; package=nil; os=nil\n" + script
                  + "\nend\nprint(assess().status)")
        return subprocess.check_output([self.runner, "-"], input=source, text=True).strip()

    def wait_result(self, obj):
        context = {"_bootstrap_argocd_application_read": {"rc": 0, "stdout": json.dumps(obj)},
                   "bootstrap_argocd_issuer_operation_annotation": self.annotation}
        for key, value in self.wait["vars"].items():
            context[key] = self.env.compile_expression(value.strip()[2:-2].strip())(**context)
        return all(self.env.compile_expression(condition)(**context) for condition in self.wait["until"])

    def test_actual_issuer_gate_cases(self):
        for name, obj, expected in cases(self.domain):
            with self.subTest(name=name):
                result = self.assess(self.script, obj)
                self.assertEqual(result, expected)
                if ROLE.exists():
                    self.assertEqual(self.wait_result(obj), result == "Healthy", "Lua/Ansible disagreement")

    def test_ordinary_gates_unchanged(self):
        obj = application(self.domain)
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
