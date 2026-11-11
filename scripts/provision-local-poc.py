"""Create isolated local control data and owner-only PoC credentials."""
import argparse
import json
import os
import secrets
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
from control_plane.database import Database
from control_plane.models import GatewayCredential, GatewayNode, LogicalRegion, Plan, PlanRegion, Subscription, User
from control_plane.security import hash_access_token, hash_password
from control_plane.time_utils import utcnow
from control_plane.gateways import valid_public_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-key", required=True)
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    if not valid_public_key(args.public_key):
        parser.error("Invalid gateway key")
    state = ROOT / ".runtime" / "poc"
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (state / "control.db").exists():
        parser.error("PoC already initialized; reuse existing data")
    db = Database("sqlite:///" + str(state / "control.db"))
    db.create_schema()
    password, token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with db.session_factory() as session:
        region = LogicalRegion(code="shanghai", name="上海", province_code="CN-SH")
        user = User(email="poc@example.invalid", password_hash=hash_password(password))
        plan = Plan(code="poc", name="PoC", max_devices=3)
        session.add_all([region, user, plan])
        session.flush()
        node = GatewayNode(region_id=region.id, name="shanghai-1-15-138-37",
            provider="wireguard", cloud_region="shanghai", endpoint=args.endpoint,
            server_public_key=args.public_key, status="provisioning", capacity=10)
        session.add(node)
        session.flush()
        session.add_all([
            GatewayCredential(gateway_id=node.id, token_hash=hash_access_token(token)),
            PlanRegion(plan_id=plan.id, region_id=region.id),
            Subscription(user_id=user.id, plan_id=plan.id, status="active",
                starts_at=utcnow(), ends_at=utcnow() + timedelta(days=7)),
        ])
        session.commit()
        values = {"gateway.json": {"gateway_id": node.id, "token": token},
                  "client.json": {"email": user.email, "password": password}}
    for name, value in values.items():
        fd = os.open(state / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle)
    db.dispose()
    print("PoC created at", state)


if __name__ == "__main__":
    main()
