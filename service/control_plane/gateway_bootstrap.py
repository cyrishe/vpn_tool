"""Run the existing gateway installer through an operator-configured SSH transport."""
from dataclasses import dataclass, field
from pathlib import Path
import base64
import hmac
import logging
import re
import shlex
import subprocess
from urllib.parse import urlsplit

from .errors import APIError
from .gateway_bundle import build_gateway_bundle
from .security import valid_public_key

LOG = logging.getLogger("uvicorn.error")

# The transport takes a single remote command, and forwards stdin without a TTY.
UNPACK = """
set -eu
umask 077
sudo -n true
if sudo -n systemctl cat regional-control.service >/dev/null 2>&1; then
    exit 20
fi
exec 9>"$HOME/.regional-vpn-bootstrap.lock"
flock -n 9 || exit 21
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
tar -xzf - -C "$work"
"""
PREPARE = UNPACK + """
if sudo -n test -f /etc/wireguard/wg-regional.conf; then
    sudo -n test -f /usr/local/libexec/regional-vpn-firewall
    if sudo -n systemctl cat regional-firewall.service >/dev/null 2>&1; then
        sudo -n systemctl start regional-firewall.service wg-quick@wg-regional.service >&2
    else
        sudo -n bash "$work/scripts/setup-wireguard-gateway.sh" --resume >&2
    fi
else
    sudo -n bash "$work/scripts/setup-wireguard-gateway.sh" >&2
fi
test "$(sudo -n wg show wg-regional listen-port)" = 51820
sudo -n wg show wg-regional public-key
"""


@dataclass(frozen=True)
class GatewayBootstrap:
    ssh_helper: Path
    center_url: str
    enrollment_key: str = field(repr=False)

    def __post_init__(self):
        if not self.ssh_helper.is_absolute():
            raise ValueError("VPN_GATEWAY_SSH_HELPER must be an absolute executable path.")
        if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?", self.center_url):
            raise ValueError("VPN_GATEWAY_CONTROL_URL must be a public HTTPS origin without a trailing slash.")
        url = urlsplit(self.center_url)
        if url.hostname == "localhost" or url.hostname.startswith("127.") or url.port == 0:
            raise ValueError("VPN_GATEWAY_CONTROL_URL must be reachable from the gateway.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43,}", self.enrollment_key):
            raise ValueError("Generate VPN_GATEWAY_BOOTSTRAP_KEY with secrets.token_urlsafe(32).")

    def token(self, gateway_id: str) -> str:
        digest = hmac.digest(self.enrollment_key.encode("ascii"), gateway_id.encode("ascii"), "sha256")
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def run(self, ip: str, command: str, archive: bytes, timeout: int, stage: str) -> str:
        try:
            result = subprocess.run(
                [str(self.ssh_helper), ip, "bash -c " + shlex.quote(command)],
                input=archive, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, timeout=timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            LOG.warning("Gateway bootstrap %s failed ip=%s reason=%s", stage, ip, type(error).__name__)
            raise APIError(502, "gateway_ssh_failed", "无法完成 SSH 安装。请检查 SSH 授权或安装超时，再重试。") from None
        if result.returncode != 0:
            LOG.warning("Gateway bootstrap %s failed ip=%s exit=%s", stage, ip, result.returncode)
            message = {
                20: "目标是中心服务器，请填写独立的 Ubuntu 节点。",
                21: "目标机器还有安装任务在运行，请稍后重试。",
                255: "SSH 未连通或认证失败。请检查节点授权、主机指纹和 SSH 安全组。",
            }.get(result.returncode, "节点安装命令失败。请检查免交互 sudo、Ubuntu 环境和网络后重试。")
            raise APIError(502, "gateway_install_failed", message)
        return result.stdout.decode("utf-8", errors="replace").strip()

    def prepare(self, ip: str, certificate: Path | None) -> str:
        key = self.run(ip, PREPARE, build_gateway_bundle(certificate), 300, "prepare")
        if not valid_public_key(key):
            raise APIError(502, "gateway_public_key_missing", "新机器未返回有效的 WireGuard 公钥。")
        return key

    def install(self, ip: str, certificate: Path | None, key: str, enrollment: dict[str, str]) -> None:
        command = UNPACK + 'test "$(sudo -n wg show wg-regional public-key)" = ' + shlex.quote(key) + '\n'
        command += 'sudo -n bash "$work/scripts/install-wireguard-agent.sh" ' + shlex.quote(
            self.center_url
        ) + ' "$work/gateway.json"'
        self.run(ip, command, build_gateway_bundle(certificate, enrollment=enrollment), 60, "install")
