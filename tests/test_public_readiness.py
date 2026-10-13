"""Only mock responses are used. No request reaches a network."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import urllib.error

import yaml

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "src/k8s/platform/services/k8s-oidc"
spec = importlib.util.spec_from_file_location("public_check", SERVICE / "check-public.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
ISSUER = "https://k8s-oidc-lz.levizitting.com"
DISCOVERY = {"issuer": ISSUER, "jwks_uri": ISSUER + "/openid/v1/jwks"}
JWKS = {"keys": [{"kty": "RSA", "n": "synthetic-modulus", "e": "AQAB"}]}


def response(url, body):
    result = Mock(status=200)
    result.geturl.return_value = url
    result.read.return_value = json.dumps(body).encode() if not isinstance(body, bytes) else body
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


def opener(discovery=DISCOVERY, jwks=JWKS):
    result = Mock()
    result.open.side_effect = [response(ISSUER + "/.well-known/openid-configuration", discovery),
                               response(ISSUER + "/openid/v1/jwks", jwks)]
    return result


class PublicCheck(unittest.TestCase):
    def test_expected_endpoints(self):
        client = opener()
        probe.check(ISSUER, client)
        self.assertEqual([call.args[0] for call in client.open.call_args_list],
                         [ISSUER + "/.well-known/openid-configuration", ISSUER + "/openid/v1/jwks"])
        self.assertTrue(all(call.kwargs["timeout"] == 8 for call in client.open.call_args_list))

    def test_malformed_wrong_issuer_uri_and_empty_keys(self):
        for discovery, jwks, category in [
            (b"not-json", JWKS, "json"), ([], JWKS, "json"),
            (dict(DISCOVERY, issuer="https://wrong.example"), JWKS, "issuer"),
            (dict(DISCOVERY, jwks_uri="http://wrong.example/keys"), JWKS, "jwks-uri"),
            (dict(DISCOVERY, jwks_uri=ISSUER + "/other"), JWKS, "jwks-uri"),
            (DISCOVERY, {"keys": []}, "keys"),
            (DISCOVERY, {"keys": [{"kty": "RSA", "n": "x", "e": "x", "d": "private"}]}, "private-key"),
            (DISCOVERY, {"keys": [{"kty": "RSA"}]}, "keys")]:
            with self.subTest(category=category):
                with self.assertRaisesRegex(probe.CheckFailed, "^" + category + "$"):
                    probe.check(ISSUER, opener(discovery, jwks))

    def test_redirect_timeout_http_and_tls_failure(self):
        with self.assertRaisesRegex(probe.CheckFailed, "^redirect$"):
            probe.NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://other.example")
        for error, category in [(TimeoutError("do not log"), "timeout"),
                                (urllib.error.URLError("do not log"), "transport"),
                                (probe.ssl.SSLError("do not log"), "transport")]:
            client = Mock()
            client.open.side_effect = error
            with self.assertRaisesRegex(probe.CheckFailed, "^" + category + "$"):
                probe.check(ISSUER, client)

    def test_bounded_retries_and_sanitized_logs(self):
        output = io.StringIO()
        with patch.object(probe, "check", side_effect=probe.CheckFailed("timeout")) as check, \
             patch.object(probe.time, "sleep") as sleep, contextlib.redirect_stdout(output):
            self.assertEqual(probe.main(ISSUER), 1)
        self.assertEqual(check.call_count, 12)
        self.assertEqual(sleep.call_count, 11)
        self.assertEqual(set(output.getvalue().splitlines()), {"oidc-public-not-ready:timeout"})

    def test_job_has_no_credentials_or_rbac(self):
        job = yaml.safe_load((SERVICE / "public-readiness.yaml").read_text())
        self.assertEqual(job["metadata"]["annotations"]["argocd.argoproj.io/hook"], "PostSync")
        self.assertEqual(job["spec"]["activeDeadlineSeconds"], 300)
        pod = job["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(pod["dnsPolicy"], "None")
        self.assertEqual(pod["dnsConfig"]["nameservers"], ["1.1.1.1", "1.0.0.1"])
        self.assertNotIn("serviceAccountName", pod)
        self.assertNotIn("env", pod["containers"][0])
        self.assertNotIn("envFrom", pod["containers"][0])
        self.assertEqual(len(pod["volumes"]), 1)
        self.assertIn("configMap", pod["volumes"][0])


if __name__ == "__main__":
    unittest.main()
