from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .time_utils import utcnow


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended')", name="ck_users_status"),
    )


class AccessToken(Base):
    __tablename__ = "access_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )

    __table_args__ = (Index("ix_access_tokens_user_id", "user_id"),)


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    max_devices: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("max_devices > 0", name="ck_plans_max_devices_positive"),
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'cancelled', 'expired')",
            name="ck_subscriptions_status",
        ),
        CheckConstraint("ends_at > starts_at", name="ck_subscriptions_date_order"),
        Index("ix_subscriptions_user_status_ends", "user_id", "status", "ends_at"),
    )


class LogicalRegion(Base):
    __tablename__ = "logical_regions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    province_code: Mapped[str] = mapped_column(String(32), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PlanRegion(Base):
    __tablename__ = "plan_regions"

    plan_id: Mapped[str] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True
    )
    region_id: Mapped[str] = mapped_column(
        ForeignKey("logical_regions.id", ondelete="CASCADE"), primary_key=True
    )


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    tunnel_public_key: Mapped[str] = mapped_column(
        String(256), unique=True, nullable=False
    )
    active_assignment_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "peer_assignments.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_devices_active_assignment",
        ),
        nullable=True,
    )
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "client_device_id", name="uq_devices_user_client_id"
        ),
        CheckConstraint("config_version >= 0", name="ck_devices_config_version"),
        Index("ix_devices_user_id", "user_id"),
    )


class GatewayNode(Base):
    __tablename__ = "gateway_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    region_id: Mapped[str] = mapped_column(
        ForeignKey("logical_regions.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    cloud_region: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(256), nullable=False)
    server_public_key: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    current_peers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('provisioning', 'verifying', 'ready', 'draining', "
            "'unhealthy', 'terminated')",
            name="ck_gateway_nodes_status",
        ),
        CheckConstraint("capacity > 0", name="ck_gateway_nodes_capacity"),
        CheckConstraint(
            "current_peers >= 0 AND current_peers <= capacity",
            name="ck_gateway_nodes_current_peers",
        ),
        Index("ix_gateway_nodes_region_status", "region_id", "status"),
    )


class PeerAssignment(Base):
    __tablename__ = "peer_assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    gateway_id: Mapped[str] = mapped_column(
        ForeignKey("gateway_nodes.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    client_address: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'ready', 'active', 'draining', 'released')",
            name="ck_peer_assignments_state",
        ),
        UniqueConstraint(
            "device_id",
            "config_version",
            name="uq_peer_assignments_device_version",
        ),
        Index("ix_peer_assignments_device_state", "device_id", "state"),
    )


class GatewayCredential(Base):
    __tablename__ = "gateway_credentials"

    gateway_id: Mapped[str] = mapped_column(ForeignKey("gateway_nodes.id"), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)


class DeviceAddress(Base):
    __tablename__ = "device_addresses"

    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    address: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)


class SwitchOperation(Base):
    __tablename__ = "switch_operations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    target_region_id: Mapped[str] = mapped_column(
        ForeignKey("logical_regions.id", ondelete="RESTRICT"), nullable=False
    )
    previous_assignment_id: Mapped[str | None] = mapped_column(
        ForeignKey("peer_assignments.id", ondelete="SET NULL"), nullable=True
    )
    candidate_assignment_id: Mapped[str] = mapped_column(
        ForeignKey("peer_assignments.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('prepared', 'committed', 'rolled_back')",
            name="ck_switch_operations_status",
        ),
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_switch_operations_user_idempotency",
        ),
        Index("ix_switch_operations_device_created", "device_id", "created_at"),
    )
