"""Copy the local pilot snapshot and re-enroll its single Shanghai gateway."""
import argparse
import json
import os
import secrets
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
from control_plane.database import Database
from control_plane.gateways import release, valid_public_key
from control_plane.models import GatewayCredential, GatewayNode, LogicalRegion, PeerAssignment
from control_plane.security import hash_access_token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--public-key", required=True)
    args = parser.parse_args()
    if not valid_public_key(args.public_key):
        parser.error("Invalid gateway public key")
    os.umask(0o077)
    args.output.mkdir(mode=0o700)
    target = args.output / "control.db"
    with sqlite3.connect(args.snapshot.resolve().as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(target) as dst:
            src.backup(dst)
    db = Database("sqlite:///" + str(target.resolve()))
    token = secrets.token_urlsafe(32)
    with db.session_factory() as session:
        region = session.scalar(select(LogicalRegion).where(LogicalRegion.code == "shanghai"))
        nodes = session.scalars(select(GatewayNode)).all()
        gateway = next(node for node in nodes if node.region_id == region.id)
        for assignment in session.scalars(select(PeerAssignment).where(PeerAssignment.state != "released")):
            release(session, assignment)
        for node in nodes:
            node.status = "terminated"
            node.current_peers = 0
        gateway.endpoint = args.endpoint
        gateway.name = "shanghai-" + args.endpoint.split(":", 1)[0].replace(".", "-")
        gateway.server_public_key = args.public_key
        gateway.status = "provisioning"
        credential = session.get(GatewayCredential, gateway.id)
        credential.token_hash = hash_access_token(token)
        session.commit()
        with (args.output / "gateway.json").open("x") as handle:
            json.dump({"gateway_id": gateway.id, "token": token}, handle)
    print("Prepared migrated pilot snapshot")


if __name__ == "__main__":
    main()
