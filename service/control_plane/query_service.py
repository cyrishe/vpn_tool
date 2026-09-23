from __future__ import annotations

from sqlalchemy import Select, and_, exists, select
from sqlalchemy.orm import Session

from .models import (
    GatewayNode,
    LogicalRegion,
    PeerAssignment,
    PlanRegion,
    Subscription,
)
from .schemas import DeviceOut, RegionOut
from .time_utils import utcnow


def active_subscription_query(user_id: str) -> Select[tuple[Subscription]]:
    now = utcnow()
    return select(Subscription).where(
        Subscription.user_id == user_id,
        Subscription.status == "active",
        Subscription.starts_at <= now,
        Subscription.ends_at > now,
    )


def get_authorized_regions(session: Session, user_id: str) -> list[RegionOut]:
    subscription = session.scalar(
        active_subscription_query(user_id).order_by(Subscription.ends_at.desc())
    )
    if subscription is None:
        return []

    ready_gateway = exists().where(
        and_(
            GatewayNode.region_id == LogicalRegion.id,
            GatewayNode.status == "ready",
            GatewayNode.current_peers < GatewayNode.capacity,
        )
    )
    rows = session.execute(
        select(LogicalRegion, ready_gateway.label("has_ready_gateway"))
        .join(PlanRegion, PlanRegion.region_id == LogicalRegion.id)
        .where(
            PlanRegion.plan_id == subscription.plan_id,
            LogicalRegion.is_enabled.is_(True),
        )
        .order_by(LogicalRegion.sort_order, LogicalRegion.code)
    ).all()
    return [
        RegionOut(
            code=region.code,
            name=region.name,
            province_code=region.province_code,
            availability="available" if has_ready_gateway else "maintenance",
        )
        for region, has_ready_gateway in rows
    ]


def serialize_device(session: Session, device: object) -> DeviceOut:
    assignment = (
        session.get(PeerAssignment, device.active_assignment_id)
        if device.active_assignment_id
        else None
    )
    region_code = None
    if assignment is not None:
        gateway = session.get(GatewayNode, assignment.gateway_id)
        region = session.get(LogicalRegion, gateway.region_id) if gateway else None
        region_code = region.code if region else None
    return DeviceOut(
        id=device.id,
        client_device_id=device.client_device_id,
        name=device.name,
        platform=device.platform,
        tunnel_public_key=device.tunnel_public_key,
        active_region_code=region_code,
        config_version=device.config_version,
    )

