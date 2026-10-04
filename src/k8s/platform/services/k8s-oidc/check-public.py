"""Bounded unauthenticated OIDC discovery check. Shared unchanged by both clusters."""
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

TIMEOUT = 8
ATTEMPTS = 12
DELAY = 5
MAX_BYTES = 1024 * 1024
ISSUERS = {"https://k8s-oidc-lz.levizitting.com", "https://k8s-oidc.sgf.dev"}


class CheckFailed(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CheckFailed("redirect")


def fetch(opener, url):
    try:
        with opener.open(url, timeout=TIMEOUT) as response:
            if response.status != 200 or response.geturl() != url:
                raise CheckFailed("endpoint")
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise CheckFailed("size")
            result = json.loads(body)
            if not isinstance(result, dict):
                raise CheckFailed("json")
            return result
    except CheckFailed:
        raise
    except (ValueError, UnicodeError):
        raise CheckFailed("json") from None
    except (TimeoutError, socket.timeout):
        raise CheckFailed("timeout") from None
    except (urllib.error.URLError, ssl.SSLError, OSError):
        raise CheckFailed("transport") from None


def check(issuer, opener):
    if issuer not in ISSUERS:
        raise CheckFailed("issuer-config")
    discovery = fetch(opener, issuer + "/.well-known/openid-configuration")
    if discovery.get("issuer") != issuer:
        raise CheckFailed("issuer")
    jwks_uri = issuer + "/openid/v1/jwks"
    if discovery.get("jwks_uri") != jwks_uri:
        raise CheckFailed("jwks-uri")
    keys = fetch(opener, jwks_uri).get("keys")
    if not isinstance(keys, list) or not keys:
        raise CheckFailed("keys")
    required = {"RSA": ("n", "e"), "EC": ("crv", "x", "y"), "OKP": ("crv", "x")}
    for key in keys:
        if not isinstance(key, dict) or key.get("kty") not in required:
            raise CheckFailed("keys")
        if any(part in key for part in ("d", "p", "q", "dp", "dq", "qi", "oth", "k")):
            raise CheckFailed("private-key")
        if any(not isinstance(key.get(part), str) or not key[part] for part in required[key["kty"]]):
            raise CheckFailed("keys")


def main(issuer):
    # Never inherit HTTP proxy credentials or send Kubernetes/AWS credentials.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    for attempt in range(ATTEMPTS):
        try:
            check(issuer, opener)
            print("oidc-public-ready")
            return 0
        except CheckFailed as error:
            print("oidc-public-not-ready:" + str(error), flush=True)
        if attempt + 1 < ATTEMPTS:
            time.sleep(DELAY)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
