"""Verify control API against the deployed gateway; does not enable a local tunnel."""
import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
from vpn_client.cli import Client, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("server", nargs="?", default="101.34.21.167")
    server = parser.parse_args().server
    args = argparse.Namespace(control_url=f"https://{server}",
        ca_cert=str(ROOT / f".runtime/poc/control-{server}.crt"),
        credentials=str(ROOT / ".runtime/poc/client.json"),
        state_dir=str(ROOT / ".runtime/poc/client"))
    client = Client(args)
    client.login()
    device = client.device()
    public = device["tunnel_public_key"]
    operation = client.request(f"/v1/devices/{device['id']}/switches", {"target_region_code": "shanghai"},
        {"Idempotency-Key": str(uuid.uuid4())})
    installed = False
    try:
        for _ in range(30):
            operation = client.request(f"/v1/switches/{operation['operation_id']}")
            if operation["profile"]: break
            time.sleep(1)
        if not operation["profile"]: raise RuntimeError("No gateway acknowledgement")
        def peers():
            return subprocess.run(["ssh", "-o", "BatchMode=yes", f"ubuntu@{server}",
                "sudo wg show wg-regional allowed-ips"], check=True, capture_output=True, text=True).stdout
        installed = public in peers()
        if not installed: raise RuntimeError("Peer missing on real gateway")
    finally:
        client.request(f"/v1/devices/{device['id']}/disconnect", {})
    removed = False
    for _ in range(10):
        if public not in peers():
            removed = True
            break
        time.sleep(1)
    if not removed: raise RuntimeError("Peer not removed")
    report = {"gateway": server, "region": "shanghai", "real_peer_installed": installed,
        "peer_removed_on_disconnect": removed, "local_egress_verified": False}
    save(ROOT / ".runtime/poc/control-check.json", json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
