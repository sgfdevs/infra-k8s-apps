#!/bin/sh
set -eu
umask 077

mkdir -p "$OCIS_CONFIG_DIR"
if [ -e "$OCIS_CONFIG_DIR/ocis.yaml" ]; then
  if [ ! -s "$OCIS_CONFIG_DIR/ocis.yaml" ]; then
    echo 'Refusing to replace an empty oCIS configuration.' >&2
    exit 1
  fi
else
  if find "$OCIS_BASE_DATA_PATH" -mindepth 1 -maxdepth 1 \
      ! -name config ! -name lost+found -print -quit | grep -q .; then
    echo 'Existing oCIS state has no configuration. Restore it instead of reinitializing.' >&2
    exit 1
  fi
  ocis init --insecure=false
fi

# Service overrides are versioned; generated identities and secrets stay on PVC.
for file in proxy.yaml csp.yaml app-registry.yaml; do
  cp "/bootstrap/$file" "$OCIS_CONFIG_DIR/$file"
done
