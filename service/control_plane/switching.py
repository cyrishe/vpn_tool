from __future__ import annotations

from sqlalchemy import select
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
)
from .query_service import active_subscription_query
from .schemas import SwitchOperationOut, TunnelProfileOut
from .time_utils import utcnow


def _client_address(region: LogicalRegion, device: Device) -> str:
    region_octet = max(1, min(region.sort_order // 10, 254))
    device_octet = (int(device.id.replace("-", "")[:8], 16) % 250) + 2
    return f"10.77.{region_octet}.{device_octet}/32"


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
    existing = session.scalar(
        select(SwitchOperation).where(
            SwitchOperation.user_id == user.id,
            SwitchOperation.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.device_id != device_id:
            raise APIError(
                409,
                "idempotency_conflict",
                "This idempotency key was used for another device.",
            )
        return _serialize_operation(session, existing)

    device = session.get(Device, device_id)
    if device is None or device.user_id != user.id:
        raise APIError(404, "device_not_found", "The device was not found.")

    region = session.scalar(
        select(LogicalRegion).where(LogicalRegion.code == target_region_code)
    )
    if region is None or not region.is_enabled:
        raise APIError(404, "region_not_found", "The target region is unavailable.")

    subscription = session.scalar(
        active_subscription_query(user.id).order_by(Subscription.ends_at.desc())
    )
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

    gateway = session.scalar(
        select(GatewayNode)
        .where(
            GatewayNode.region_id == region.id,
            GatewayNode.status == "ready",
            GatewayNode.current_peers < GatewayNode.capacity,
        )
        .order_by(GatewayNode.current_peers, GatewayNode.name)
    )
    if gateway is None:
        raise APIError(
            503, "region_capacity_unavailable", "No healthy gateway is available."
        )

    next_version = device.config_version + 1
    assignment = PeerAssignment(
        device_id=device.id,
        gateway_id=gateway.id,
        state="ready",
        config_version=next_version,
        client_address=_client_address(region, device),
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
    gateway.current_peers += 1
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

