#!/usr/bin/env bash
set -Eeuo pipefail

DRY_RUN=0
TAILSCALE_HOSTNAME=""
SYSCTL_FILE="/etc/sysctl.d/99-tailscale-exit-node.conf"
installer_dir=""
installer_file=""
sysctl_tmp=""

cleanup() {
  if [[ -n "$installer_file" ]]; then
    rm -f -- "$installer_file"
  fi
  if [[ -n "$installer_dir" ]]; then
    rmdir -- "$installer_dir" 2>/dev/null || true
  fi
  if [[ -n "$sysctl_tmp" ]]; then
    rm -f -- "$sysctl_tmp"
  fi
}

trap cleanup EXIT

usage() {
  cat <<'EOF'
Configure a Linux machine as a Tailscale exit node.

Usage:
  bash setup-tailscale-exit-node.sh [--hostname NAME] [--dry-run]

Options:
  --hostname NAME  Set the Tailscale machine name.
  --dry-run        Print the intended actions without changing the machine.
  -h, --help       Show this help.

Run this script from a normal sudo-capable account. During the first run,
Tailscale prints a login URL; open it and sign in with your Tailscale account.
EOF
}

log() {
  printf '\n==> %s\n' "$*"
}

quote_command() {
  printf '  '
  printf '%q ' "$@"
  printf '\n'
}

run() {
  quote_command "$@"
  if (( DRY_RUN == 0 )); then
    "$@"
  fi
}

as_root() {
  if (( EUID == 0 )); then
    run "$@"
  else
    run sudo "$@"
  fi
}

while (( $# > 0 )); do
  case "$1" in
    --hostname)
      if (( $# < 2 )); then
        printf 'Missing value for --hostname.\n\n' >&2
        usage >&2
        exit 2
      fi
      TAILSCALE_HOSTNAME="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$(uname -s)" != "Linux" ]]; then
  printf 'This script is intended for a Linux server, not %s.\n' "$(uname -s)" >&2
  exit 1
fi

if (( EUID != 0 )) && ! command -v sudo >/dev/null 2>&1; then
  printf 'sudo is required when the script is not run as root.\n' >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  printf 'curl is required. Install it first, for example: sudo apt-get install curl\n' >&2
  exit 1
fi

log "Installing Tailscale when it is not already installed"
if command -v tailscale >/dev/null 2>&1; then
  printf '  Tailscale is already installed: %s\n' "$(tailscale version | head -n 1)"
elif (( DRY_RUN == 1 )); then
  printf '  curl -fsSL https://tailscale.com/install.sh -o <temporary-file>\n'
  printf '  sh <temporary-file>\n'
else
  installer_dir="$(mktemp -d)"
  installer_file="$installer_dir/install.sh"
  run curl -fsSL https://tailscale.com/install.sh -o "$installer_file"
  as_root sh "$installer_file"
fi

log "Enabling IPv4 and IPv6 forwarding"
if (( DRY_RUN == 1 )); then
  printf '  write %s with IPv4 and IPv6 forwarding enabled\n' "$SYSCTL_FILE"
else
  sysctl_tmp="$(mktemp)"
  printf '%s\n' \
    'net.ipv4.ip_forward = 1' \
    'net.ipv6.conf.all.forwarding = 1' >"$sysctl_tmp"

  if as_root test -f "$SYSCTL_FILE"; then
    if ! as_root cmp -s "$sysctl_tmp" "$SYSCTL_FILE"; then
      backup="${SYSCTL_FILE}.bak.$(date +%Y%m%d%H%M%S)"
      log "Backing up the existing forwarding configuration to $backup"
      as_root cp "$SYSCTL_FILE" "$backup"
    fi
  fi

  as_root install -m 0644 "$sysctl_tmp" "$SYSCTL_FILE"
fi
as_root sysctl -p "$SYSCTL_FILE"

if command -v systemctl >/dev/null 2>&1; then
  log "Enabling the Tailscale service at boot"
  as_root systemctl enable --now tailscaled
fi

log "Connecting this server to your Tailscale network"
tailscale_up_args=(tailscale up)
if [[ -n "$TAILSCALE_HOSTNAME" ]]; then
  tailscale_up_args+=(--hostname="$TAILSCALE_HOSTNAME")
fi

if (( DRY_RUN == 1 )); then
  printf '  sudo '
  printf '%q ' "${tailscale_up_args[@]}"
  printf '    # opens the first-login URL\n'
  printf '  sudo tailscale set --advertise-exit-node\n'
else
  if as_root tailscale status >/dev/null 2>&1; then
    printf '  This server is already connected to Tailscale.\n'
  else
    as_root "${tailscale_up_args[@]}"
  fi
  if [[ -n "$TAILSCALE_HOSTNAME" ]]; then
    as_root tailscale set --hostname="$TAILSCALE_HOSTNAME"
  fi
  as_root tailscale set --advertise-exit-node
fi

cat <<'EOF'

Server configuration is complete.

One required web-console step remains:
  1. Open https://console.tailscale.com/admin/machines
  2. Find this server.
  3. Open "Edit route settings".
  4. Enable "Use as exit node".

Then install Tailscale on the publishing computer, sign in with the same
account, and select this server under "Exit Nodes".
EOF
