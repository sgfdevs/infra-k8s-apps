#!/bin/sh
set -eu
umask 077

# Generated credentials are alphanumeric so neither ACL nor Sentinel config
# quoting can be changed by a secret value. Fail closed on malformed input.
discovery_password="$(cat /etc/sentinel-auth/discovery-password)"
admin_password="$(cat /etc/sentinel-auth/admin-password)"
for password in "$discovery_password" "$admin_password"; do
  case "$password" in
    ''|*[!a-zA-Z0-9]*) echo 'Invalid Sentinel credential format' >&2; exit 1 ;;
  esac
  [ "${#password}" -ge 32 ] || { echo 'Sentinel credential is too short' >&2; exit 1; }
done
[ "$discovery_password" != "$admin_password" ] || {
  echo 'Sentinel discovery and administrative credentials must differ' >&2
  exit 1
}

# Stable DNS survives pod-IP changes. The override supports non-Kubernetes
# smoke checks; Kubernetes derives this from the StatefulSet pod identity.
announce_host="${SENTINEL_ANNOUNCE_HOST:-${POD_NAME}.valkey-sentinel-headless.${POD_NAMESPACE}.svc.cluster.local}"
case "$announce_host" in
  ''|*[!a-zA-Z0-9.-]*) echo 'Invalid Sentinel announce hostname' >&2; exit 1 ;;
esac

discovery_hash="$(printf %s "$discovery_password" | sha256sum | awk '{print $1}')"
admin_hash="$(printf %s "$admin_password" | sha256sum | awk '{print $1}')"

# Kaneo accepts a Sentinel password but no Sentinel username, so the default
# user is discovery-only. Keep the administrative/peer password out of apps.
# ioredis uses SENTINEL SENTINELS, GET-MASTER-ADDR-BY-NAME, and may subscribe
# to +switch-master. Do not grant discovery clients MONITOR, SET, RESET,
# FAILOVER, CONFIG, ACL, PUBLISH, or SHUTDOWN.
printf '%s\n' \
  "user default reset on #${discovery_hash} &+switch-master +ping +info +role +auth +hello +client|setname +client|setinfo +subscribe +unsubscribe +psubscribe +punsubscribe +sentinel|get-master-addr-by-name +sentinel|sentinels +sentinel|replicas +sentinel|slaves +sentinel|master +sentinel|masters" \
  "user sentinel-admin reset on #${admin_hash} ~* &* +@all" \
  > /run/sentinel/users.acl

# Refresh platform settings without resetting Sentinel's elected topology.
# Only Sentinel state is retained, never stale ACL paths or global settings.
# Keep each voter's myid and epoch on its own PVC, including when no masters
# have been enrolled. Never copy one voter's state directory to another.
next=/data/sentinel.conf.next
cat /etc/sentinel-config/sentinel.conf > "$next"
if [ -f /data/sentinel.conf ]; then
  awk '
    $1 == "sentinel" &&
    $2 !~ /^(resolve-hostnames|announce-hostnames|announce-ip|announce-port|deny-scripts-reconfig|sentinel-user|sentinel-pass)$/
  ' /data/sentinel.conf >> "$next"
fi
printf '\nsentinel announce-ip %s\nsentinel sentinel-user sentinel-admin\nsentinel sentinel-pass %s\n' \
  "$announce_host" "$admin_password" >> "$next"
mv "$next" /data/sentinel.conf
unset discovery_password admin_password password discovery_hash admin_hash

exec valkey-server /data/sentinel.conf --sentinel
