#!/usr/bin/env bash
set -Eeuo pipefail
[[ $# == 2 ]] || exit 2
exec /usr/bin/ssh -F /dev/null -T \
  -o BatchMode=yes -o ConnectTimeout=8 -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/regional-vpn/gateway-known-hosts \
  -o GlobalKnownHostsFile=/dev/null -o ClearAllForwardings=yes \
  -i /etc/regional-vpn/gateway-ssh-key -l ubuntu -- "$1" "$2"
