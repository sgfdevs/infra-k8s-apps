"""Check or update the input-bound public issuer hook. No cluster access."""
import argparse
import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = Path("src/k8s/platform/k8s-oidc.yaml")
ISSUER = Path("src/k8s/platform/services/k8s-oidc")
DEPLOYMENT = ISSUER / "deployment.yaml"
HOOK = ISSUER / "public-readiness.yaml"
HOOK_PREFIX = "oidc-public-readiness-"


def annotation(root):
    app = yaml.safe_load((root / APP).read_text())
    gate = next(k for k in app["metadata"]["annotations"] if k.endswith("/issuer-operation-gate"))
    return gate.removesuffix("issuer-operation-gate") + "issuer-input-fingerprint"


def inputs(root):
    """All issuer files plus its Application, ordered by repository-relative path."""
    return sorted([APP] + [p.relative_to(root) for p in (root / ISSUER).rglob("*")
                          if p.is_file() and "__pycache__" not in p.parts])


def fingerprint(root=ROOT):
    key = annotation(root)
    records = []
    app = yaml.safe_load((root / APP).read_text())
    if app["spec"]["source"]["path"] != ISSUER.as_posix():
        raise ValueError("Issuer Application source must use the fingerprinted directory")
    for path in inputs(root):
        content = (root / path).read_bytes().decode("utf-8")
        if path.suffix in {".yaml", ".yml"} or path.name == "Kustomization":
            content = list(yaml.safe_load_all(content))
            for doc in content:
                if doc and doc.get("kind") == "Kustomization":
                    # Fail closed if a future Kustomize input bypasses this directory.
                    allowed = {"apiVersion", "kind", "namespace", "resources", "configMapGenerator"}
                    if set(doc) - allowed:
                        raise ValueError("Extend issuer fingerprint coverage before adding Kustomize fields")
                    refs = doc.get("resources", [])
                    for generator in doc.get("configMapGenerator", []):
                        if set(generator) - {"name", "files"}:
                            raise ValueError("Uncovered issuer generator input")
                        refs = refs + [ref.split("=", 1)[-1] for ref in generator.get("files", [])]
                    for ref in refs:
                        source = (root / path.parent / ref).resolve()
                        if not source.exists() or not source.is_relative_to((root / ISSUER).resolve()):
                            raise ValueError("Issuer sources must stay inside the fingerprinted directory")
                if path in {APP, DEPLOYMENT}:
                    meta = doc["metadata"]
                    meta.get("annotations", {}).pop(key, None)
                    if meta.get("annotations") == {}:
                        meta.pop("annotations")
                if path == HOOK:
                    doc["metadata"]["name"] = "oidc-public-readiness"
        records.append([path.as_posix(), content])
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    # 160 bits keep the named Job at 62 characters, within the 63-character limit.
    return hashlib.sha256(encoded).hexdigest()[:40]


def bindings(root=ROOT):
    key = annotation(root)
    value = fingerprint(root)
    return [(APP, key, value), (DEPLOYMENT, key, value), (HOOK, "name", HOOK_PREFIX + value)]


def verify(root=ROOT):
    for path, field, expected in bindings(root):
        meta = yaml.safe_load((root / path).read_text())["metadata"]
        actual = meta["name"] if field == "name" else meta.get("annotations", {}).get(field)
        if actual != expected:
            raise ValueError(f"Stale issuer input binding in {path}; run scripts/issuer-fingerprint.py --update")
    return fingerprint(root)


def update(root=ROOT):
    # Replace only the three generated fields. Preserve surrounding manifests and comments.
    for path, field, expected in bindings(root):
        target = root / path
        text = target.read_text()
        meta = yaml.safe_load(text)["metadata"]
        if field == "name":
            old = "  name: " + meta["name"] + "\n"
            new = "  name: " + expected + "\n"
        else:
            old = f'    {field}: "{meta["annotations"][field]}"\n'
            new = f'    {field}: "{expected}"\n'
        if text.count(old) != 1:
            raise ValueError(f"Expected one generated field in {path}")
        target.write_text(text.replace(old, new))
    return verify(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    print(update() if args.update else verify())
