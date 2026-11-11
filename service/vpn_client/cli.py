import argparse
import base64
import ipaddress
import json
import os
import re
import shutil
import ssl
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

def valid_public_key(value):
    try:
        raw = base64.b64decode(value, validate=True)
        return len(raw) == 32 and any(raw) and base64.b64encode(raw).decode() == value
    except (TypeError, ValueError):
        return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def save(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(value)


def public_ip():
    for url in ("https://ifconfig.co/ip", "https://api.ipify.org"):
        result = subprocess.run(["curl", "--noproxy", "*", "-4", "-fsS", "--max-time", "8", url],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return str(ipaddress.ip_address(result.stdout.strip()))
    raise RuntimeError("Public IP lookup failed")


def tunnel_command(action, config, check=True, gui=False):
    quick = shutil.which("wg-quick")
    bash = shutil.which("bash")
    if not quick or not bash:
        raise ValueError("wg-quick and bash 4+ required")
    if gui:
        script = '''on run argv
do shell script ((quoted form of item 1 of argv) & " " & (quoted form of item 2 of argv) & " " & (quoted form of item 3 of argv) & " " & (quoted form of item 4 of argv)) with administrator privileges
end run'''
        return subprocess.run(["/usr/bin/osascript", "-e", script, bash, quick, action, str(config)],
                              check=check, capture_output=True, text=True)
    return subprocess.run(["sudo", bash, quick, action, str(config)], check=check)


class Client:
    def __init__(self, args):
        self.args = args
        self.state = Path(args.state_dir).resolve()
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.state.stat().st_mode & 0o077:
            raise ValueError("Client state directory requires chmod 700")
        self.token = None
        context = ssl.create_default_context(cafile=getattr(args, "ca_cert", None))
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}),
                                                urllib.request.HTTPSHandler(context=context))

    def request(self, path, body=None, headers=None):
        req = urllib.request.Request(self.args.control_url.rstrip("/") + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     **({"Authorization": "Bearer " + self.token} if self.token else {}),
                     **(headers or {})})
        with self.opener.open(req, timeout=15) as response:
            return json.load(response)

    def login(self):
        path = Path(self.args.credentials)
        if path.stat().st_mode & 0o077:
            raise ValueError("Credentials require chmod 600")
        login = json.loads(path.read_text())
        self.token = self.request("/v1/auth/login", login)["access_token"]

    def device(self):
        keyfile = self.state / "private.key"
        if not keyfile.exists():
            key = subprocess.run(["wg", "genkey"], check=True, capture_output=True, text=True).stdout.strip()
            save(keyfile, key + "\n")
        key = keyfile.read_text().strip()
        public = subprocess.run(["wg", "pubkey"], input=key + "\n", check=True,
                                capture_output=True, text=True).stdout.strip()
        identity = self.state / "device-id"
        if not identity.exists(): save(identity, str(uuid.uuid4()))
        return self.request("/v1/devices", {"client_device_id": identity.read_text(),
            "name": "Mac command-line PoC", "platform": "macos", "tunnel_public_key": public})

    def connect(self):
        wg_quick = shutil.which("wg-quick")
        if not wg_quick or not shutil.which("wg"):
            raise ValueError("Install wireguard-tools and wireguard-go first")
        previous = self.state / "connection.json"
        if previous.exists() and json.loads(previous.read_text()).get("connected"):
            raise ValueError("Disconnect the existing system tunnel first")
        gui = getattr(self.args, "gui", False)
        if not gui:
            subprocess.run(["sudo", "-v"], check=True)
        if not self.token:
            self.login()
        available = self.request("/v1/regions")
        if not any(r["code"] == self.args.region and r["availability"] == "available" for r in available):
            raise ValueError("Region is not authorized or has no healthy gateway")
        device = self.device()
        baseline = public_ip()
        operation = self.request(f"/v1/devices/{device['id']}/switches",
            {"target_region_code": self.args.region}, {"Idempotency-Key": str(uuid.uuid4())})
        config = self.state / "regionvpn.conf"
        up = False
        try:
            for _ in range(60):
                if operation["profile"] or operation["status"] != "prepared": break
                time.sleep(.5)
                operation = self.request(f"/v1/switches/{operation['operation_id']}")
            profile = operation["profile"]
            if not profile: raise ValueError("Gateway did not acknowledge configuration")
            if not valid_public_key(profile["server_public_key"]): raise ValueError("Invalid server key")
            if not re.fullmatch(r"[a-zA-Z0-9.-]+:[0-9]{1,5}", profile["endpoint"]):
                raise ValueError("Invalid endpoint")
            address = ipaddress.ip_interface(profile["client_address"])
            dns = ", ".join(str(ipaddress.ip_address(value)) for value in profile["dns_servers"])
            private = (self.state / "private.key").read_text().strip()
            if not valid_public_key(private): raise ValueError("Invalid local tunnel key")
            save(config, f"[Interface]\nPrivateKey = {private}\n"
                f"Address = {address}\nDNS = {dns}\n\n[Peer]\nPublicKey = {profile['server_public_key']}\n"
                f"Endpoint = {profile['endpoint']}\nAllowedIPs = 0.0.0.0/0, ::/0\nPersistentKeepalive = 25\n")
            save(self.state / "connection.json", json.dumps({"device_id": device["id"], "before_ip": baseline}))
            # wg-quick owns route/DNS restoration; never implement that logic here.
            tunnel_command("up", config, gui=gui)
            up = True
            observed = public_ip()
            expected = profile["endpoint"].rsplit(":", 1)[0]
            if observed != expected:
                raise ValueError(f"Egress mismatch: expected {expected}, observed {observed}")
            result = self.request(f"/v1/switches/{operation['operation_id']}/confirm", {"success": True})
            if result["status"] != "committed": raise ValueError("Switch was not committed")
            save(self.state / "connection.json", json.dumps({"device_id": device["id"],
                "before_ip": baseline, "after_ip": observed, "region": self.args.region, "connected": True}))
            return {"region": self.args.region, "before_ip": baseline, "after_ip": observed, "egress_verified": True}
        except BaseException:
            if up: tunnel_command("down", config, check=False, gui=gui)
            try: self.request(f"/v1/devices/{device['id']}/disconnect", {})
            except Exception: pass
            raise

    def disconnect(self):
        path = self.state / "regionvpn.conf"
        tunnel_command("down", path, gui=getattr(self.args, "gui", False))
        connection = json.loads((self.state / "connection.json").read_text())
        connection["connected"] = False
        save(self.state / "connection.json", json.dumps(connection))
        try:
            if not self.token:
                self.login()
            self.request(f"/v1/devices/{connection['device_id']}/disconnect", {})
        except (OSError, urllib.error.URLError):
            return {"connected": False, "warning": "Tunnel stopped; server release not confirmed."}
        return {"connected": False, "before_ip": connection["before_ip"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["connect", "disconnect", "regions"])
    parser.add_argument("--control-url", default="http://127.0.0.1:8018")
    parser.add_argument("--credentials", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--region", default="shanghai")
    parser.add_argument("--ca-cert")
    args = parser.parse_args()
    from urllib.parse import urlsplit
    url = urlsplit(args.control_url)
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1")):
        parser.error("HTTPS required except loopback")
    client = Client(args)
    if args.action == "connect": print(json.dumps(client.connect(), ensure_ascii=False))
    elif args.action == "disconnect": print(json.dumps(client.disconnect(), ensure_ascii=False))
    else:
        client.login()
        print(json.dumps(client.request("/v1/regions"), ensure_ascii=False))


if __name__ == "__main__":
    main()
