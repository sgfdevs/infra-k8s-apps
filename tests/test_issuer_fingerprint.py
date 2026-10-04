"""Exercise actual digest/update code and rendered hook identity offline."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

import test_health
from issuer_gate_cases import application

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("issuer_fingerprint", ROOT / "scripts/issuer-fingerprint.py")
fingerprint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fingerprint)


class Fingerprint(unittest.TestCase):
    def copy_inputs(self, target):
        for path in fingerprint.inputs(ROOT):
            (target / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, target / path)

    def test_checked_in_digest_and_rendered_bindings(self):
        expected = fingerprint.verify()
        self.assertRegex(expected, r"^[0-9a-f]{40}$")
        docs = list(yaml.safe_load_all(subprocess.check_output(
            ["kubectl", "kustomize", str(ROOT / fingerprint.ISSUER)], text=True)))
        hook = next(d for d in docs if d["kind"] == "Job")
        deployment = next(d for d in docs if d["kind"] == "Deployment")
        self.assertEqual(hook["metadata"]["name"], fingerprint.HOOK_PREFIX + expected)
        self.assertLessEqual(len(hook["metadata"]["name"]), 63)
        self.assertEqual(hook["metadata"]["namespace"], "k8s-oidc")
        self.assertEqual(hook["metadata"]["annotations"]["argocd.argoproj.io/hook"], "PostSync")
        self.assertEqual(deployment["metadata"]["annotations"][fingerprint.annotation(ROOT)], expected)
        self.assertNotIn("argocd.argoproj.io/hook", deployment["metadata"]["annotations"])

    def test_every_source_file_affects_digest_and_ci_rejects_stale_bindings(self):
        # New files are discovered too. Do not rely on a hand-maintained filename list.
        for path in fingerprint.inputs(ROOT):
            with self.subTest(path=path), tempfile.TemporaryDirectory(dir=ROOT) as tmp:
                target = Path(tmp)
                self.copy_inputs(target)
                before = fingerprint.verify(target)
                file = target / path
                if path.suffix in {".yaml", ".yml"}:
                    # Semantic input change, not a comment or formatting-only edit.
                    docs = list(yaml.safe_load_all(file.read_text()))
                    if docs[0].get("kind") == "Kustomization":
                        docs[0]["namespace"] = "changed-namespace"
                    else:
                        docs[0]["digest-test-input"] = "changed"
                    file.write_text(yaml.safe_dump_all(docs))
                else:
                    file.write_text(file.read_text() + "\n# changed checker input\n")
                self.assertNotEqual(fingerprint.fingerprint(target), before)
                with self.assertRaises(ValueError):
                    fingerprint.verify(target)
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            target = Path(tmp)
            self.copy_inputs(target)
            (target / fingerprint.ISSUER / "new-input.txt").write_text("new issuer input")
            self.assertNotEqual(fingerprint.fingerprint(target), fingerprint.fingerprint(ROOT))

    def test_generated_fields_are_excluded_and_update_is_idempotent(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            target = Path(tmp)
            self.copy_inputs(target)
            expected = fingerprint.verify(target)
            for path, _, binding in fingerprint.bindings(target):
                file = target / path
                file.write_text(file.read_text().replace(binding, binding.replace(expected, "b" * 40)))
            self.assertEqual(fingerprint.fingerprint(target), expected)
            with self.assertRaises(ValueError):
                fingerprint.verify(target)
            self.assertEqual(fingerprint.update(target), expected)
            before = {p: (target / p).read_bytes() for p in fingerprint.inputs(target)}
            fingerprint.update(target)
            self.assertEqual(before, {p: (target / p).read_bytes() for p in fingerprint.inputs(target)})

    def test_uncovered_kustomize_input_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            target = Path(tmp)
            self.copy_inputs(target)
            path = target / fingerprint.ISSUER / "kustomization.yaml"
            doc = yaml.safe_load(path.read_text())
            doc["resources"].append("../../outside.yaml")
            path.write_text(yaml.safe_dump(doc))
            with self.assertRaises(ValueError):
                fingerprint.fingerprint(target)

    def test_real_config_and_checker_changes_invalidate_actual_lua_gate(self):
        test_health.Health.setUpClass()
        health = test_health.Health()
        for path in [fingerprint.ISSUER / "kubeconfig.yaml", fingerprint.ISSUER / "check-public.py"]:
            with self.subTest(path=path), tempfile.TemporaryDirectory(dir=ROOT) as tmp:
                target = Path(tmp)
                self.copy_inputs(target)
                old = fingerprint.verify(target)
                file = target / path
                file.write_text(file.read_text().replace("kubernetes.default.svc", "changed.invalid")
                                if path.suffix == ".yaml" else file.read_text() + "\n# new checker\n")
                new = fingerprint.update(target)
                self.assertNotEqual(old, new)
                app = application(health.domain)
                app["metadata"]["annotations"][health.domain + "/issuer-input-fingerprint"] = new
                hook = app["status"]["operationState"]["syncResult"]["resources"][0]
                hook["name"] = fingerprint.HOOK_PREFIX + old
                self.assertEqual(health.assess(health.script, app), "Progressing")
                hook["name"] = fingerprint.HOOK_PREFIX + new
                app["status"]["sync"]["revision"] = "new-unrelated-sha"
                self.assertEqual(health.assess(health.script, app), "Healthy")


if __name__ == "__main__":
    unittest.main()
