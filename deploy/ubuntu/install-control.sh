#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID == 0 && $(uname -s) == Linux ]] || { echo 'Run as root on Ubuntu.' >&2; exit 1; }
server_ip=${1:?Usage: install-control.sh SERVER_IP}
[[ "$server_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 2
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
id regionalvpn >/dev/null 2>&1 || useradd --system --home-dir /var/lib/regional-vpn --shell /usr/sbin/nologin regionalvpn
install -d -o regionalvpn -g regionalvpn -m 0700 /var/lib/regional-vpn /var/backups/regional-vpn
install -d -o root -g regionalvpn -m 0750 /etc/regional-vpn
if [[ ! -f /etc/regional-vpn/control.key && ! -f /etc/regional-vpn/control.crt ]]; then
  umask 077
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 \
    -subj "/CN=$server_ip" -addext "subjectAltName=IP:$server_ip,IP:127.0.0.1" \
    -keyout /etc/regional-vpn/control.key -out /etc/regional-vpn/control.crt 2>/dev/null
fi
test -s /etc/regional-vpn/control.key
test -s /etc/regional-vpn/control.crt
chown root:regionalvpn /etc/regional-vpn/control.key /etc/regional-vpn/control.crt
chmod 0640 /etc/regional-vpn/control.key
chmod 0644 /etc/regional-vpn/control.crt
install -m 0644 "$source_dir/regional-control.service" /etc/systemd/system/
install -m 0644 "$source_dir/regional-gateway.service" /etc/systemd/system/
install -m 0644 "$source_dir/regional-backup.service" /etc/systemd/system/
install -m 0644 "$source_dir/regional-backup.timer" /etc/systemd/system/
install -m 0755 "$source_dir/admin.sh" /usr/local/bin/regional-vpn-admin
systemctl daemon-reload
echo 'Control installation prepared. Install/migrate database before starting services.'
