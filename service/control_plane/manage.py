"""Local operator commands; run on the control server, never on user devices."""
import argparse
import json
import os
import uuid
from datetime import timedelta

from sqlalchemy import select

from .config import Settings
from .database import Database, begin_write
from .gateways import change_gateway_status, valid_public_key
from .models import (GatewayCredential, GatewayNode, LogicalRegion, Plan, PlanRegion,
                     Subscription, User)
from .security import hash_access_token, hash_password, issue_access_token
from .time_utils import utcnow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    region = commands.add_parser("region")
    region.add_argument("code")
    region.add_argument("name")
    region.add_argument("--province", required=True)
    gateway = commands.add_parser("gateway")
    gateway.add_argument("name")
    gateway.add_argument("--region", required=True)
    gateway.add_argument("--endpoint", required=True)
    gateway.add_argument("--public-key", required=True)
    gateway.add_argument("--credential-out", required=True)
    gateway.add_argument("--capacity", type=int, default=100)
    user = commands.add_parser("user")
    user.add_argument("email")
    user.add_argument("--regions", nargs="+", required=True)
    user.add_argument("--days", type=int, default=30)
    commands.add_parser("nodes")
    lifecycle = commands.add_parser("node-state")
    lifecycle.add_argument("name")
    lifecycle.add_argument("action", choices=["online", "drain", "retire"])
    args = parser.parse_args()
    db = Database(Settings.from_env().database_url)
    db.create_schema()
    with db.session_factory() as session:
        if args.command == "nodes":
            nodes = session.execute(select(GatewayNode, LogicalRegion.code).join(LogicalRegion)
                .order_by(LogicalRegion.code, GatewayNode.name)).all()
            print(json.dumps([{"name": node.name, "region": code, "endpoint": node.endpoint,
                "status": node.status, "peers": node.current_peers, "capacity": node.capacity,
                "heartbeat_age_seconds": max(0, int((utcnow() - node.last_heartbeat_at).total_seconds()))}
                for node, code in nodes], indent=2))
            return
        if args.command == "node-state":
            begin_write(session)
            node = session.scalar(select(GatewayNode).where(GatewayNode.name == args.name))
            if node is None:
                parser.error("Unknown node.")
            try:
                change_gateway_status(session, node, args.action)
            except ValueError as error:
                parser.error(str(error))
        elif args.command == "region":
            if session.scalar(select(LogicalRegion).where(LogicalRegion.code == args.code)):
                parser.error("Region already exists.")
            session.add(LogicalRegion(code=args.code, name=args.name, province_code=args.province))
        elif args.command == "gateway":
            region = session.scalar(select(LogicalRegion).where(LogicalRegion.code == args.region))
            if region is None or not valid_public_key(args.public_key) or args.capacity < 1:
                parser.error("Valid region, public key and capacity required.")
            if not args.endpoint or ":" not in args.endpoint:
                parser.error("Endpoint must contain host:port.")
            node = GatewayNode(name=args.name, region_id=region.id, provider="wireguard",
                cloud_region=args.region, endpoint=args.endpoint,
                server_public_key=args.public_key, status="provisioning", capacity=args.capacity)
            session.add(node)
            session.flush()
            token = issue_access_token()
            session.add(GatewayCredential(gateway_id=node.id, token_hash=hash_access_token(token)))
            # Exclusive creation avoids overwriting existing credentials.
            fd = os.open(args.credential_out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump({"gateway_id": node.id, "token": token}, handle)
                handle.write("\n")
        else:
            password = os.environ.get("VPN_NEW_USER_PASSWORD")
            if not password or len(password) < 12 or args.days < 1:
                parser.error("Set VPN_NEW_USER_PASSWORD (12+ characters), days must be positive.")
            regions = session.scalars(select(LogicalRegion).where(LogicalRegion.code.in_(args.regions))).all()
            if len(regions) != len(set(args.regions)):
                parser.error("Unknown region.")
            account = User(email=args.email.strip().lower(), password_hash=hash_password(password))
            plan = Plan(code=f"personal-{uuid.uuid4().hex}", name="Personal", max_devices=3)
            session.add_all([account, plan])
            session.flush()
            session.add_all(PlanRegion(plan_id=plan.id, region_id=r.id) for r in regions)
            session.add(Subscription(user_id=account.id, plan_id=plan.id, status="active",
                starts_at=utcnow(), ends_at=utcnow() + timedelta(days=args.days)))
        session.commit()
    db.dispose()
    print("Created.")


if __name__ == "__main__":
    main()
