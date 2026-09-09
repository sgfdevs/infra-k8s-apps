#!/usr/bin/env python3
"""Check a staging Kustomize render offline. Requires PyYAML, no cluster access."""

import argparse
import re
from pathlib import PurePosixPath

import yaml

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("render", type=argparse.FileType("r"))
parser.add_argument("--require-digest", action="store_true")
args = parser.parse_args()
objects = list(yaml.safe_load_all(args.render))
app = "gooddads-enrollment-bot"
namespace = f"{app}-staging"
host = f"{namespace}.opensgf.org"
image_repo = f"ghcr.io/open-sgf/{app}"
resources = {(o["kind"], o["metadata"]["name"]): o for o in objects}
assert len(resources) == len(objects), "Duplicate resources"
assert len(objects) == 18, "Unexpected staging resource inventory"
for obj in objects:
    if obj["kind"] in {"Namespace", "DbInstance"}:
        assert "namespace" not in obj["metadata"], "Cluster-scoped resource has namespace"
    else:
        assert obj["metadata"]["namespace"] == namespace
    assert obj["kind"] != "Secret", "Secrets must come from operators, not Git"


def resource(kind, name=app):
    return resources[kind, name]


def wave(obj):
    return int(obj["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"])


resource("Namespace", namespace)
config = resource("ConfigMap")
assert "APP_TIMEZONE" not in config["data"]
assert config["data"]["APP_URL"] == f"https://{host}"
assert config["data"]["DROPBOX_REDIRECT_URI"] == f"https://{host}/dropbox/callback"
assert config["data"]["APP_DEBUG"] == "false"
assert config["data"]["MAIL_HOST"] == "email-smtp.us-east-2.amazonaws.com"
assert config["data"]["MAIL_FROM_ADDRESS"] == f"staging-{app}@sgf.dev"
for key in ("QUEUE_CONNECTION", "CACHE_STORE", "SESSION_DRIVER"):
    assert config["data"][key] == "database"

mappings = {
    "application": {
        "appKey": ("laravel", "APP_KEY"),
        "neonBaseUrl": ("neon", "NEON_BASE_URL"),
        "neonApiKey": ("neon", "NEON_API_KEY"),
        "dropboxAppKey": ("dropbox", "DROPBOX_APP_KEY"),
        "dropboxAppSecret": ("dropbox", "DROPBOX_APP_SECRET"),
        "dropboxOauthBasicUser": ("oauth", "DROPBOX_OAUTH_BASIC_USER"),
        "dropboxOauthBasicPassword": ("oauth", "DROPBOX_OAUTH_BASIC_PASSWORD"),
        "sentryDsn": ("sentry", "SENTRY_LARAVEL_DSN"),
        "mailIntakeFormRecipient": ("notifications", "MAIL_INTAKE_FORM_RECIPIENT"),
    },
    "ses": {"username": ("ses", "MAIL_USERNAME"), "password": ("ses", "MAIL_PASSWORD")},
}
store = resource("SecretStore", "openbao")
vault = store["spec"]["provider"]["vault"]
assert (vault["path"], vault["version"]) == ("applications", "v2")
auth = vault["auth"]["kubernetes"]
assert (auth["mountPath"], auth["role"]) == ("kubernetes", namespace)
assert auth["serviceAccountRef"]["audiences"] == ["vault"]
sa = resource("ServiceAccount", auth["serviceAccountRef"]["name"])
assert sa["metadata"]["name"] == f"{app}-secrets"
assert wave(sa) < wave(store)
for suffix, expected in mappings.items():
    secret = resource("ExternalSecret", f"{app}-{suffix}")
    spec = secret["spec"]
    assert spec["secretStoreRef"] == {"kind": "SecretStore", "name": "openbao"}
    assert spec["target"]["name"] == f"{app}-{suffix}"
    assert len(spec["data"]) == len(expected)
    assert {
        d["remoteRef"]["property"]: (d["remoteRef"]["key"], d["secretKey"])
        for d in spec["data"]
    } == {
        prop: (f"{app}/staging/{path}", env)
        for prop, (path, env) in expected.items()
    }, f"Incorrect remote paths or environment mappings for {suffix}"
    assert not {env for _, env in expected.values()} & config["data"].keys()
    assert wave(store) < wave(secret)

database = resource("Database")
instance = resource("DbInstance", database["spec"]["instance"])
cluster = resource("Cluster", f"{app}-mysql")
assert instance["metadata"]["name"] == f"{namespace}-mysql"
assert instance["spec"]["adminSecretRef"] == {
    "Name": f"{app}-mysql-mysql-account-root", "Namespace": namespace,
}
assert instance["spec"]["generic"]["host"] == f"{app}-mysql-mysql.{namespace}.svc.cluster.local"
assert config["data"]["DB_HOST"] == f"{cluster['metadata']['name']}-mysql"
assert database["spec"]["secretName"] == f"{app}-database"
job = resource("Job", f"{app}-migrate")
deployment = resource("Deployment")
assert job["metadata"]["annotations"]["argocd.argoproj.io/hook"] == "Sync"
assert wave(cluster) < wave(instance) < wave(database) < wave(job) < wave(deployment)
assert wave(config) < wave(job)
for suffix in mappings:
    assert wave(resource("ExternalSecret", f"{app}-{suffix}")) < wave(job)
assert deployment["spec"]["replicas"] == 1
assert deployment["spec"]["strategy"] == {"type": "Recreate"}

images = set()
for workload in (deployment, job):
    pod = workload["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    security = pod["securityContext"]
    assert security["runAsUser"] == security["runAsGroup"] == security["fsGroup"] == 33
    assert security["runAsNonRoot"] is True
    volumes = {v["name"]: v for v in pod["volumes"]}
    container = pod["containers"][0]
    assert container["envFrom"] == [
        {"configMapRef": {"name": app}},
        {"secretRef": {"name": f"{app}-application"}},
        {"secretRef": {"name": f"{app}-ses"}},
    ]
    assert {e["name"]: e["valueFrom"]["secretKeyRef"] for e in container["env"]} == {
        env: {"name": f"{app}-database", "key": key}
        for env, key in (("DB_DATABASE", "DB"), ("DB_USERNAME", "USER"), ("DB_PASSWORD", "PASSWORD"))
    }
    mounts = {m["mountPath"]: m for m in container["volumeMounts"]}
    for path in ("/tmp", "/var/www/html/bootstrap/cache", "/var/www/html/storage/framework",
                 "/var/www/html/storage/logs", "/var/www/html/storage/app/private"):
        assert path in mounts and not mounts[path].get("readOnly", False)
    private = volumes[mounts["/var/www/html/storage/app/private"]["name"]]
    if workload is deployment:
        resource("PersistentVolumeClaim", private["persistentVolumeClaim"]["claimName"])
    else:
        assert "emptyDir" in private, "Migration must not contend for the document PVC"
        assert "artisan migrate --force --no-interaction" in container["command"][-1]
    template = PurePosixPath("/var/www/html/storage/intake-form/Enrollment_Form_Fillable_2026-01-27.pdf")
    for c in pod["containers"] + pod.get("initContainers", []):
        images.add(c["image"])
        security = c["securityContext"]
        assert security["readOnlyRootFilesystem"] is True
        assert security["allowPrivilegeEscalation"] is False
        assert security["capabilities"]["drop"] == ["ALL"]
        for mount in c.get("volumeMounts", []):
            assert mount["name"] in volumes
            assert not template.is_relative_to(mount["mountPath"]), "Mount hides the PDF template"
        for volume in volumes.values():
            if "configMap" in volume:
                resource("ConfigMap", volume["configMap"]["name"])
assert len(images) == 1, "Migration, init and app images must match"
image = images.pop()
if args.require_digest:
    assert re.fullmatch(re.escape(image_repo) + r"@sha256:[0-9a-f]{64}", image), "Pin a published digest BEFORE MERGE"
else:
    assert image == f"{image_repo}:v0.3.0" or re.fullmatch(re.escape(image_repo) + r"@sha256:[0-9a-f]{64}", image)

service = resource("Service")
labels = deployment["spec"]["template"]["metadata"]["labels"]
assert service["spec"]["selector"] == deployment["spec"]["selector"]["matchLabels"]
assert all(labels[k] == v for k, v in service["spec"]["selector"].items())
assert service["spec"]["ports"][0]["targetPort"] == "http"
assert deployment["spec"]["template"]["spec"]["containers"][0]["ports"][0] == {
    "name": "http", "containerPort": 8080, "protocol": "TCP",
}
ingress = resource("Ingress")
certificate = resource("Certificate", f"{app}-tls")
assert ingress["spec"]["tls"] == [{"hosts": [host], "secretName": certificate["spec"]["secretName"]}]
assert certificate["spec"]["dnsNames"] == [host]
assert ingress["spec"]["rules"][0]["host"] == host
assert ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"] == {
    "name": app, "port": {"number": service["spec"]["ports"][0]["port"]},
}
annotation = ingress["metadata"]["annotations"]["traefik.ingress.kubernetes.io/router.middlewares"]
assert annotation == ",".join(f"{namespace}-{app}-{suffix}@kubernetescrd" for suffix in ("https-redirect", "noindex"))
for suffix in ("https-redirect", "noindex"):
    resource("Middleware", f"{app}-{suffix}")
assert "noindex" in resource("Middleware", f"{app}-noindex")["spec"]["headers"]["customResponseHeaders"]["X-Robots-Tag"]
assert "Disallow: /" in resource("ConfigMap", f"{app}-robots")["data"]["robots.txt"]
print(f"PASS: {len(objects)} staging resources; references, env mappings, ordering, runtime and ingress contracts")
if not args.require_digest and "@sha256:" not in image:
    print("BLOCKED FOR MERGE: v0.3.0 is pending publication; rerun with --require-digest after pinning")
