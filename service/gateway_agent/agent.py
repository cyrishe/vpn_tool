"""Reconcile peers on a dedicated, preconfigured Linux WireGuard interface."""
import argparse
import ipaddress
import json
import logging
import os
import socket
import ssl
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from control_plane.gateways import valid_public_key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WireGuard:
    def __init__(self, interface, run=subprocess.run):
        self.interface = interface
        self.run = run

    def command(self, *args):
        return self.run(["wg", *args], check=True, capture_output=True, text=True, timeout=4).stdout.strip()

    def public_key(self):
        key = self.command("show", self.interface, "public-key")
        if not valid_public_key(key):
            raise ValueError("Interface has no valid public key")
        return key

    def reconcile(self, peers):
        desired = {}
        addresses = set()
        # Validate the entire snapshot before changing the interface.
        for peer in peers:
            address = ipaddress.ip_interface(peer["address"])
            if (not valid_public_key(peer["public_key"]) or address.version != 4
                    or address.network.prefixlen != 32
                    or address.ip not in ipaddress.ip_network("10.77.0.0/16")
                    or peer["public_key"] in desired or str(address) in addresses):
                raise ValueError("Invalid peer snapshot")
            desired[peer["public_key"]] = str(address)
            addresses.add(str(address))
        current = set(self.command("show", self.interface, "peers").split())
        for key in current - desired.keys():
            self.command("set", self.interface, "peer", key, "remove")
        for key, address in desired.items():
            self.command("set", self.interface, "peer", key, "allowed-ips", address)


class Agent:
    def __init__(self, wg, synchronize, clock=time.monotonic):
        self.wg, self.synchronize, self.clock = wg, synchronize, clock
        self.applied = []
        self.leases = []

    def tick(self):
        started = self.clock()
        try:
            response = self.synchronize(self.wg.public_key(), self.applied)
            peers = response["peers"]
            # Start lease at request start, so slow requests never extend access.
            leases = [(p, started + min(30, max(0, int(p["lease_seconds"])))) for p in peers]
            live = [p for p, expiry in leases if expiry > self.clock()]
            self.wg.reconcile(live)
            self.leases = leases
            self.applied = [p["assignment_id"] for p in live]
        except Exception:
            # Avoid logging credential-bearing URLs or HTTP bodies.
            logging.warning("Synchronization failed; retaining only unexpired leases")
            live = [p for p, expiry in self.leases if expiry > self.clock()]
            self.wg.reconcile(live)
            self.applied = [p["assignment_id"] for p in live]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-url", required=True)
    parser.add_argument("--credentials", required=True)
    parser.add_argument("--ca-cert")
    parser.add_argument("--interface", default="wg-regional")
    args = parser.parse_args()
    url = urllib.parse.urlsplit(args.control_url)
    if (url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost"))) or url.username or url.password or url.query or url.fragment:
        parser.error("Use an HTTPS control URL (loopback HTTP allowed for local tests).")
    credential_file = Path(args.credentials)
    if credential_file.stat().st_mode & 0o077:
        parser.error("Credential file must be readable only by its owner (chmod 600).")
    credentials = json.loads(credential_file.read_text())
    context = ssl.create_default_context(cafile=args.ca_cert)
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context), urllib.request.ProxyHandler({}))

    def synchronize(key, applied):
        req = urllib.request.Request(args.control_url.rstrip("/") + "/v1/gateway/sync",
            data=json.dumps({"public_key": key, "applied_assignment_ids": applied}).encode(),
            headers={"Authorization": "Bearer " + credentials["token"], "Content-Type": "application/json"})
        with opener.open(req, timeout=5) as response:
            result = json.load(response)
            if result["gateway_id"] != credentials["gateway_id"]:
                raise ValueError("Gateway identity mismatch")
            return result

    wg = WireGuard(args.interface)
    wg.reconcile([])
    agent = Agent(wg, synchronize)
    def notify(message):
        address = os.environ.get("NOTIFY_SOCKET")
        if address:
            if address.startswith("@"):
                address = "\0" + address[1:]
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
                channel.sendto(message.encode(), address)
    notify("READY=1")
    try:
        while True:
            agent.tick()
            notify("WATCHDOG=1")
            time.sleep(3)
    finally:
        wg.reconcile([])


if __name__ == "__main__":
    main()
