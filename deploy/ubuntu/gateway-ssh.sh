#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${REGIONAL_VPN_ASKPASS:-} == 1 ]]; then
  [[ $# == 1 && -z ${SSH_ASKPASS_PROMPT:-} && -n ${VPN_GATEWAY_SSH_PASSWORD:-} ]] || exit 2
  printf '%s\n' "$VPN_GATEWAY_SSH_PASSWORD"
  exit
fi

[[ $# == 2 ]] || exit 2
if [[ -n ${VPN_GATEWAY_SSH_PASSWORD:-} ]]; then
  export SSH_ASKPASS="$0" SSH_ASKPASS_REQUIRE=force REGIONAL_VPN_ASKPASS=1
  auth=(-o BatchMode=no -o PreferredAuthentications=password -o NumberOfPasswordPrompts=1)
else
  auth=(-o BatchMode=yes -o IdentitiesOnly=yes -i /etc/regional-vpn/gateway-ssh-key)
fi

exec /usr/bin/ssh -F /dev/null -T "${auth[@]}" -o ConnectTimeout=8 \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/regional-vpn/gateway-known-hosts \
  -o GlobalKnownHostsFile=/dev/null -o ClearAllForwardings=yes \
  -l ubuntu -- "$1" "$2"
