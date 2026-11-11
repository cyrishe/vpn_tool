from __future__ import annotations

import base64
from datetime import timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from .auth import DBSession, bearer_scheme
from .errors import APIError
from .models import (Device, GatewayCredential, GatewayNode, LogicalRegion,
                     PeerAssignment, Plan, PlanRegion, Subscription, SwitchOperation, User)
from .security import hash_access_token
from .time_utils import utcnow

LEASE_SECONDS = 30
PENDING_SECONDS = 120


def valid_public_key(value: str) -> bool:
    try:
        raw = base64.b64decode(value, validate=True)
        return len(raw) == 32 and any(raw) and base64.b64encode(raw).decode() == value
    except ValueError:
        return False


def entitled(session, device, region_id):
    user = session.get(User, device.user_id)
    region = session.get(LogicalRegion, region_id)
    if not user or user.status != "active" or not region or not region.is_enabled:
        return None
    now = utcnow()
    return session.scalar(select(Subscription).join(Plan).join(
        PlanRegion, PlanRegion.plan_id == Plan.id
    ).where(
        Subscription.user_id == device.user_id, Subscription.status == "active",
        Subscription.starts_at <= now, Subscription.ends_at > now,
        Plan.is_active.is_(True), PlanRegion.region_id == region_id,
    ).order_by(Subscription.ends_at.desc()))


def release(session, assignment):
    if assignment.state == "released":
        return
    assignment.state = "released"
    assignment.released_at = utcnow()
    gateway = session.get(GatewayNode, assignment.gateway_id)
    gateway.current_peers = max(0, gateway.current_peers - 1)
    device = session.get(Device, assignment.device_id)
    if device.active_assignment_id == assignment.id:
        device.active_assignment_id = None
    for operation in session.scalars(select(SwitchOperation).where(
        SwitchOperation.candidate_assignment_id == assignment.id,
        SwitchOperation.status == "prepared",
    )).all():
        operation.status = "rolled_back"
        operation.completed_at = utcnow()


def sweep(session):
    now = utcnow()
    for assignment in session.scalars(select(PeerAssignment).where(
        PeerAssignment.state != "released"
    )).all():
        gateway = session.get(GatewayNode, assignment.gateway_id)
        device = session.get(Device, assignment.device_id)
        pending_expired = (assignment.state in ("pending", "ready") and
                           assignment.created_at < now - timedelta(seconds=PENDING_SECONDS))
        if gateway.status == "terminated" or pending_expired or not entitled(session, device, gateway.region_id):
            release(session, assignment)
    session.flush()


def change_gateway_status(session, gateway, action):
    if gateway.status == "terminated":
        raise ValueError("Retired nodes must be enrolled again with a new identity.")
    if action == "online":
        if gateway.status not in ("verifying", "draining", "ready") or (
            gateway.last_heartbeat_at < utcnow() - timedelta(seconds=LEASE_SECONDS)
        ):
            raise ValueError("Wait for a fresh heartbeat and verify the gateway first.")
        gateway.status = "ready"
    elif action == "drain":
        gateway.status = "draining"
    elif action == "retire":
        gateway.status = "terminated"
        sweep(session)
    else:
        raise ValueError("Unknown gateway action.")


class SyncIn(BaseModel):
    public_key: str = Field(max_length=64)
    applied_assignment_ids: list[str] = Field(default_factory=list, max_length=65534)


class PeerOut(BaseModel):
    assignment_id: str
    public_key: str
    address: str
    lease_seconds: int


class SyncOut(BaseModel):
    gateway_id: str
    region_code: str
    peers: list[PeerOut]


router = APIRouter(prefix="/v1/gateway", tags=["gateway-agent"])


@router.post("/sync", response_model=SyncOut)
def sync(payload: SyncIn, session: DBSession, credentials=Depends(bearer_scheme)):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise APIError(401, "gateway_auth_required", "Gateway credential required.")
    credential = session.scalar(select(GatewayCredential).where(
        GatewayCredential.token_hash == hash_access_token(credentials.credentials)
    ))
    if credential is None:
        raise APIError(401, "invalid_gateway_token", "Invalid gateway credential.")
    gateway = session.get(GatewayNode, credential.gateway_id)
    if gateway.status == "terminated":
        raise APIError(403, "gateway_disabled", "Gateway disabled.")
    if not valid_public_key(payload.public_key) or payload.public_key != gateway.server_public_key:
        raise APIError(409, "gateway_key_mismatch", "Gateway key does not match enrollment.")
    sweep(session)
    gateway.last_heartbeat_at = utcnow()
    if gateway.status in ("provisioning", "unhealthy"):
        gateway.status = "verifying"
    region = session.get(LogicalRegion, gateway.region_id)
    peers = []
    for assignment in session.scalars(select(PeerAssignment).where(
        PeerAssignment.gateway_id == gateway.id,
        PeerAssignment.state.in_(["pending", "ready", "active"]),
    )).all():
        if assignment.id in payload.applied_assignment_ids and assignment.state == "pending":
            assignment.state = "ready"
        device = session.get(Device, assignment.device_id)
        subscription = entitled(session, device, gateway.region_id)
        remaining = (subscription.ends_at - utcnow()).total_seconds() if subscription else 0
        if assignment.state in ("pending", "ready"):
            remaining = min(remaining, (assignment.created_at + timedelta(seconds=PENDING_SECONDS) - utcnow()).total_seconds())
        ttl = min(LEASE_SECONDS, int(remaining))
        if ttl > 0:
            peers.append(PeerOut(assignment_id=assignment.id,
                public_key=device.tunnel_public_key, address=assignment.client_address,
                lease_seconds=ttl))
    session.commit()
    return SyncOut(gateway_id=gateway.id, region_code=region.code, peers=peers)
