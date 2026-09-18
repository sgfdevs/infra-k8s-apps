#!/bin/sh
set -eu
export REDISCLI_AUTH="$(cat /etc/sentinel-auth/discovery-password)"
valkey-cli -h 127.0.0.1 -p 26379 ping | grep -qx PONG
