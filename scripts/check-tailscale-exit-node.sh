#!/usr/bin/env bash
set -u

failed=0

check_equal() {
  label="$1"
  actual="$2"
  expected="$3"

  if [[ "$actual" == "$expected" ]]; then
    printf '[OK]   %-28s %s\n' "$label" "$actual"
  else
    printf '[FAIL] %-28s expected %s, got %s\n' "$label" "$expected" "$actual"
    failed=1
  fi
}

if [[ "$(uname -s)" != "Linux" ]]; then
  printf 'This check is intended for the Linux exit-node server.\n' >&2
  exit 1
fi

if ! command -v tailscale >/dev/null 2>&1; then
  printf '[FAIL] Tailscale is not installed.\n'
  exit 1
fi

check_equal "IPv4 forwarding" "$(sysctl -n net.ipv4.ip_forward 2>/dev/null)" "1"
check_equal "IPv6 forwarding" "$(sysctl -n net.ipv6.conf.all.forwarding 2>/dev/null)" "1"

if command -v systemctl >/dev/null 2>&1; then
  service_state="$(systemctl is-active tailscaled 2>/dev/null || true)"
  check_equal "tailscaled service" "$service_state" "active"
fi

printf '\nTailscale addresses:\n'
tailscale ip 2>/dev/null || {
  printf '[FAIL] This machine is not connected to Tailscale.\n'
  failed=1
}

printf '\nTailscale status:\n'
tailscale status || failed=1

printf '\nReminder: the script cannot verify the web-console approval.\n'
printf 'The machine must show an "Exit Node" badge at:\n'
printf 'https://console.tailscale.com/admin/machines\n'

exit "$failed"
