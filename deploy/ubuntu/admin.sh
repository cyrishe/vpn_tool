#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/regional-vpn/service
export VPN_ENVIRONMENT=production
export VPN_DATABASE_URL=sqlite:////var/lib/regional-vpn/control.db
exec /opt/regional-vpn/.venv/bin/python -m control_plane.manage "$@"
