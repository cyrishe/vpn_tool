from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import (
    GatewayNode,
    LogicalRegion,
    Plan,
    PlanRegion,
    Subscription,
    User,
)
from .security import hash_password
from .time_utils import utcnow


def seed_development_data(session: Session, settings: Settings) -> None:
    existing = session.scalar(select(User).where(User.email == settings.demo_email))
    if existing is not None:
        return

    user = User(
        email=settings.demo_email.strip().lower(),
        password_hash=hash_password(settings.demo_password),
    )
    plan = Plan(code="all-regions-dev", name="开发全地区套餐", max_devices=3)
    session.add_all([user, plan])
    session.flush()

    regions = [
        LogicalRegion(
            code="shanghai",
            name="上海",
            province_code="CN-SH",
            sort_order=10,
        ),
        LogicalRegion(
            code="beijing",
            name="北京",
            province_code="CN-BJ",
            sort_order=20,
        ),
        LogicalRegion(
            code="guangdong",
            name="广东",
            province_code="CN-GD",
            sort_order=30,
        ),
        LogicalRegion(
            code="zhejiang",
            name="浙江",
            province_code="CN-ZJ",
            sort_order=40,
            is_enabled=False,
        ),
    ]
    session.add_all(regions)
    session.flush()

    session.add_all(
        PlanRegion(plan_id=plan.id, region_id=region.id) for region in regions[:3]
    )
    now = utcnow()
    session.add(
        Subscription(
            user_id=user.id,
            plan_id=plan.id,
            status="active",
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=30),
        )
    )

    for index, region in enumerate(regions[:3], start=1):
        session.add(
            GatewayNode(
                region_id=region.id,
                name=f"mock-{region.code}-01",
                provider="mock",
                cloud_region=f"mock-{region.code}",
                endpoint=f"127.0.0.1:{52000 + index}",
                server_public_key=f"mock-server-public-key-{region.code}",
                status="ready",
                capacity=100,
            )
        )

    session.commit()

