#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# != 2 || "${1:-}" == --help ]]; then
  echo 'Usage: sudo bash scripts/install-wireguard-agent.sh HTTPS_CONTROL_URL DOWNLOADED_GATEWAY_JSON'
  [[ "${1:-}" == --help ]] && exit 0
  exit 2
fi
[[ $(uname -s) == Linux && $EUID == 0 ]] || { echo 'Run as root on the Ubuntu gateway.' >&2; exit 1; }
bundle=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
center=${1%/}
credential=$2
destination=/etc/regional-vpn/gateway.json
app=/opt/regional-vpn-gateway

if systemctl cat regional-control.service >/dev/null 2>&1; then
  echo 'This host already has the control-server unit. Use a dedicated Ubuntu gateway.' >&2
  exit 1
fi
if systemctl is-active --quiet regional-gateway.service; then
  echo 'The gateway Agent is already running. Check its heartbeat in the admin console.'
  exit 0
fi
if [[ -e "$destination" ]] && ! cmp -s -- "$credential" "$destination"; then
  echo 'A different gateway credential is installed. Check the machine and downloaded file.' >&2
  exit 1
fi
if [[ $(wg show wg-regional listen-port) != 51820 ]]; then
  echo 'Prepare the wg-regional interface before installing the Agent.' >&2
  exit 1
fi

/usr/bin/python3 - "$center" "$credential" "$bundle/control.crt" <<'PY'
import json
import re
import ssl
import sys
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

center, credential, certificate = sys.argv[1:]
try:
    url = urllib.parse.urlsplit(center)
    if (url.scheme != "https" or not url.hostname or url.path
            or not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", url.netloc)
            or url.hostname.lower() == "localhost" or url.hostname.startswith("127.")
            or url.port == 0 or url.query or url.fragment or any(char.isspace() for char in center)):
        raise ValueError
except ValueError:
    sys.exit("Enter the public HTTPS origin of the control server.")
try:
    data = json.loads(Path(credential).read_text())
    if str(uuid.UUID(data["gateway_id"])) != data["gateway_id"] or not re.fullmatch(r"[A-Za-z0-9_-]{43}", data["token"]):
        raise ValueError
except (OSError, ValueError, KeyError, TypeError, AttributeError):
    sys.exit("Use the gateway credential JSON downloaded from the admin console.")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


try:
    context = ssl.create_default_context(cafile=certificate if Path(certificate).is_file() else None)
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context)
    )
    with opener.open(center + "/healthz", timeout=8) as response:
        if json.load(response).get("status") != "ok":
            raise ValueError
except (OSError, ValueError, AttributeError):
    sys.exit("Control server HTTPS check failed. Check the address, outbound TCP 443, and the bundle's public certificate.")
PY

umask 077
install -d -m 0700 /etc/regional-vpn
install -d -m 0755 "$app/service/control_plane" "$app/service/gateway_agent"
install -m 0644 "$bundle/service/control_plane/"{__init__,security}.py "$app/service/control_plane/"
install -m 0644 "$bundle/service/gateway_agent/"{__init__,agent}.py "$app/service/gateway_agent/"
install -m 0600 -- "$credential" "$destination"
printf 'VPN_CONTROL_URL=%s\n' "$center" > /etc/regional-vpn/agent.env
chmod 0600 /etc/regional-vpn/agent.env
if [[ -f "$bundle/control.crt" ]]; then
  install -m 0644 "$bundle/control.crt" /etc/regional-vpn/control.crt
  printf 'VPN_CONTROL_CA_CERT=/etc/regional-vpn/control.crt\n' >> /etc/regional-vpn/agent.env
fi
install -m 0644 "$bundle/service/gateway_agent/regional-gateway.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now regional-gateway.service
echo 'Agent started. Refresh the node in the admin console to check its first heartbeat.'
