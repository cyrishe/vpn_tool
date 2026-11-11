#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${1:-}" == "--help" ]]; then
  printf 'Usage: sudo bash setup-wireguard-gateway.sh\nCreates the dedicated wg-regional interface (UDP 51820).\n'
  exit 0
fi
[[ $(uname -s) == Linux && $EUID == 0 ]] || { echo 'Run as root on Ubuntu/Debian.' >&2; exit 1; }
[[ ! -e /etc/wireguard/wg-regional.conf || "${1:-}" == --resume ]] || { echo 'wg-regional already configured; refusing to overwrite.' >&2; exit 1; }
apt-get update
apt-get install -y wireguard-tools iptables python3
install -d -m 0700 /etc/wireguard /etc/regional-vpn
umask 077
if [[ ! -e /etc/wireguard/regional.key ]]; then
  wg genkey > /etc/wireguard/regional.key
fi
wan=$(ip -j -4 route get 1.1.1.1 | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["dev"])')
[[ "$wan" =~ ^[a-zA-Z0-9_.-]+$ ]] || exit 1
install -d -m 0755 /usr/local/libexec
cat > /usr/local/libexec/regional-vpn-firewall <<'FIREWALL'
#!/usr/bin/env bash
set -Eeuo pipefail
wan=$(ip -j -4 route get 1.1.1.1 | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["dev"])')
iptables -w -N REGIONAL-EGRESS 2>/dev/null || true
iptables -w -F REGIONAL-EGRESS
# Prevent access to peers, cloud metadata, private networks and reserved ranges.
for net in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4; do
  iptables -w -A REGIONAL-EGRESS -d "$net" -j DROP
done
iptables -w -A REGIONAL-EGRESS -o "$wan" -j ACCEPT
iptables -w -A REGIONAL-EGRESS -j DROP
iptables -w -C FORWARD -i wg-regional -j REGIONAL-EGRESS 2>/dev/null || iptables -w -I FORWARD 1 -i wg-regional -j REGIONAL-EGRESS
iptables -w -C FORWARD -o wg-regional -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || iptables -w -I FORWARD 1 -o wg-regional -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -w -C INPUT -i wg-regional -j DROP 2>/dev/null || iptables -w -I INPUT 1 -i wg-regional -j DROP
iptables -w -C INPUT -p udp --dport 51820 -j ACCEPT 2>/dev/null || iptables -w -I INPUT 1 -p udp --dport 51820 -j ACCEPT
iptables -w -t nat -C POSTROUTING -s 10.77.0.0/16 -o "$wan" -j MASQUERADE 2>/dev/null || iptables -w -t nat -A POSTROUTING -s 10.77.0.0/16 -o "$wan" -j MASQUERADE
# IPv6 is intentionally blocked for the first IPv4-only gateway implementation.
ip6tables -w -C INPUT -i wg-regional -j DROP 2>/dev/null || ip6tables -w -I INPUT 1 -i wg-regional -j DROP
ip6tables -w -C FORWARD -i wg-regional -j DROP 2>/dev/null || ip6tables -w -I FORWARD 1 -i wg-regional -j DROP
FIREWALL
chmod 0700 /usr/local/libexec/regional-vpn-firewall
{
  printf '[Interface]\nAddress = 10.77.0.1/16\nListenPort = 51820\nPrivateKey = '
  cat /etc/wireguard/regional.key
} > /etc/wireguard/wg-regional.conf
cat > /etc/systemd/system/regional-firewall.service <<'UNIT'
[Unit]
Description=Regional VPN gateway firewall
Before=wg-quick@wg-regional.service
[Service]
Type=oneshot
ExecStart=/usr/local/libexec/regional-vpn-firewall
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
install -d -m 0755 /etc/systemd/system/wg-quick@wg-regional.service.d
printf '[Unit]\nRequires=regional-firewall.service\nAfter=regional-firewall.service\n' > /etc/systemd/system/wg-quick@wg-regional.service.d/firewall.conf
printf 'net.ipv4.ip_forward = 1\n' > /etc/sysctl.d/98-regional-vpn.conf
sysctl -p /etc/sysctl.d/98-regional-vpn.conf
systemctl daemon-reload
systemctl enable --now regional-firewall
systemctl enable --now wg-quick@wg-regional
printf 'Gateway public key: '
wg show wg-regional public-key
printf 'Next: enroll this key and endpoint with the control server, then install the gateway agent.\n'
