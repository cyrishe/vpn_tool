#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
server=${VPN_SERVER_IP:-101.34.21.167}
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PYTHONPATH="$root/service${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m vpn_client.cli "${1:-regions}" \
  --control-url "https://$server" \
  --ca-cert "$root/.runtime/poc/control-$server.crt" \
  --credentials "$root/.runtime/poc/client.json" \
  --state-dir "$root/.runtime/poc/client" \
  --region shanghai
