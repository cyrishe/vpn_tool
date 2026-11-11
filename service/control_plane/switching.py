from __future__ import annotations

from datetime import timedelta
from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .errors import APIError
from .models import (
    Device,
    GatewayNode,
    LogicalRegion,
    PeerAssignment,
    PlanRegion,
    Subscription,
    SwitchOperation,
    User,
    DeviceAddress,
)
from .schemas import SwitchOperationOut, TunnelProfileOut
from .time_utils import utcnow
from .gateways import sweep, entitled, valid_public_key


def _client_address(session: Session, device: Device) -> str:
    existing = session.get(DeviceAddress, device.id)
    if existing:
        return existing.address
    start = int(device.id.replace("-", "")[:8], 16) % 65000
    for offset in range(65000):
        number = (start + offset) % 65000 + 2
        address = f"10.77.{number // 256}.{number % 256}/32"
        try:
            with session.begin_nested():
                session.add(DeviceAddress(device_id=device.id, address=address))
                session.flush()
            return address
        except IntegrityError:
            existing = session.get(DeviceAddress, device.id)
            if existing:
                return existing.address
            continue
    raise APIError(503, "address_pool_full", "Address pool is full.")


def _serialize_operation(
    session: Session, operation: SwitchOperation
) -> SwitchOperationOut:
    region = session.get(LogicalRegion, operation.target_region_id)
    assignment = session.get(PeerAssignment, operation.candidate_assignment_id)
    gateway = session.get(GatewayNode, assignment.gateway_id) if assignment else None

    profile = None
    if (
        operation.status == "prepared"
        and region is not None
        and assignment is not None
        and gateway is not None
        and assignment.state == "ready"
    ):
        profile = TunnelProfileOut(
            profile_id=assignment.id,
            config_version=assignment.config_version,
            region_code=region.code,
            gateway_id=gateway.id,
            endpoint=gateway.endpoint,
            server_public_key=gateway.server_public_key,
            client_address=assignment.client_address,
            dns_servers=["223.5.5.5", "119.29.29.29"],
            allowed_ips=["0.0.0.0/0", "::/0"],
        )
    return SwitchOperationOut(
        operation_id=operation.id,
        status=operation.status,
        device_id=operation.device_id,
        target_region_code=region.code if region else "unknown",
        profile=profile,
    )


def prepare_switch(
    session: Session,
    user: User,
    device_id: str,
    target_region_code: str,
    idempotency_key: str,
) -> SwitchOperationOut:
    sweep(session)
    existing = session.scalar(
        select(SwitchOperation).where(
            SwitchOperation.user_id == user.id,
            SwitchOperation.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        region = session.get(LogicalRegion, existing.target_region_id)
        if existing.device_id != device_id or region.code != target_region_code:
            raise APIError(
                409,
                "idempotency_conflict",
                "This idempotency key was used for another device.",
            )
        return _serialize_operation(session, existing)

    device = session.scalar(select(Device).where(Device.id == device_id).with_for_update())
    if device is None or device.user_id != user.id:
        raise APIError(404, "device_not_found", "The device was not found.")

    region = session.scalar(
        select(LogicalRegion).where(LogicalRegion.code == target_region_code)
    )
    if region is None or not region.is_enabled:
        raise APIError(404, "region_not_found", "The target region is unavailable.")

    subscription = entitled(session, device, region.id)
    if subscription is None:
        raise APIError(
            403, "subscription_required", "An active subscription is required."
        )
    allowed = session.get(PlanRegion, (subscription.plan_id, region.id))
    if allowed is None:
        raise APIError(
            403,
            "region_not_in_plan",
            "The active subscription does not include this region.",
        )

    if session.scalar(select(SwitchOperation.id).where(
        SwitchOperation.device_id == device.id, SwitchOperation.status == "prepared"
    )):
        raise APIError(409, "switch_in_progress", "Finish the current switch first.")

    gateway = session.scalar(
        select(GatewayNode)
        .where(
            GatewayNode.region_id == region.id,
            GatewayNode.status == "ready",
            GatewayNode.current_peers < GatewayNode.capacity,
            ((GatewayNode.provider == "mock") | (GatewayNode.last_heartbeat_at > utcnow() - timedelta(seconds=30))),
        )
        .order_by(GatewayNode.current_peers, GatewayNode.name)
    )
    if gateway is None:
        raise APIError(
            503, "region_capacity_unavailable", "No healthy gateway is available."
        )

    if gateway.provider != "mock" and not valid_public_key(device.tunnel_public_key):
        raise APIError(422, "invalid_tunnel_key", "A real WireGuard public key is required.")
    next_version = (session.scalar(select(func.max(PeerAssignment.config_version)).where(
        PeerAssignment.device_id == device.id
    )) or 0) + 1
    reserved = session.execute(update(GatewayNode).where(
        GatewayNode.id == gateway.id, GatewayNode.status == "ready",
        GatewayNode.current_peers < GatewayNode.capacity,
    ).values(current_peers=GatewayNode.current_peers + 1))
    if reserved.rowcount != 1:
        raise APIError(503, "region_capacity_unavailable", "Gateway capacity changed; retry.")
    assignment = PeerAssignment(
        device_id=device.id,
        gateway_id=gateway.id,
        state="ready" if gateway.provider == "mock" else "pending",
        config_version=next_version,
        client_address=_client_address(session, device),
    )
    session.add(assignment)
    session.flush()

    operation = SwitchOperation(
        user_id=user.id,
        device_id=device.id,
        target_region_id=region.id,
        previous_assignment_id=device.active_assignment_id,
        candidate_assignment_id=assignment.id,
        idempotency_key=idempotency_key,
        status="prepared",
    )
    session.add(operation)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(SwitchOperation).where(
                SwitchOperation.user_id == user.id,
                SwitchOperation.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise
        return _serialize_operation(session, existing)
    return _serialize_operation(session, operation)


def confirm_switch(
    session: Session, user: User, operation_id: str, success: bool
) -> SwitchOperationOut:
    sweep(session)
    operation = session.get(SwitchOperation, operation_id)
    if operation is None or operation.user_id != user.id:
        raise APIError(
            404, "switch_operation_not_found", "The switch operation was not found."
        )
    if operation.status != "prepared":
        return _serialize_operation(session, operation)

    device = session.get(Device, operation.device_id)
    candidate = session.get(PeerAssignment, operation.candidate_assignment_id)
    if device is None or candidate is None:
        raise APIError(
            409, "switch_state_invalid", "The switch operation is incomplete."
        )
    candidate_gateway = session.get(GatewayNode, candidate.gateway_id)

    now = utcnow()
    if success and candidate.state != "ready":
        raise APIError(409, "gateway_not_ready", "Wait for the gateway to apply the peer.")
    if success:
        previous = (
            session.get(PeerAssignment, operation.previous_assignment_id)
            if operation.previous_assignment_id
            else None
        )
        if previous is not None and previous.state == "active":
            previous.state = "released"
            previous.released_at = now
            previous_gateway = session.get(GatewayNode, previous.gateway_id)
            if previous_gateway is not None:
                previous_gateway.current_peers = max(
                    0, previous_gateway.current_peers - 1
                )

        candidate.state = "active"
        candidate.activated_at = now
        device.active_assignment_id = candidate.id
        device.config_version = candidate.config_version
        device.last_seen_at = now
        operation.status = "committed"
    else:
        candidate.state = "released"
        candidate.released_at = now
        if candidate_gateway is not None:
            candidate_gateway.current_peers = max(
                0, candidate_gateway.current_peers - 1
            )
        operation.status = "rolled_back"

    operation.completed_at = now
    session.commit()
    return _serialize_operation(session, operation)

