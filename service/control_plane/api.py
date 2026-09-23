from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header
from sqlalchemy import select

from .auth import CurrentUser, DBSession, authenticate
from .config import Settings
from .errors import APIError
from .models import Device, Plan, Subscription
from .query_service import (
    active_subscription_query,
    get_authorized_regions,
    serialize_device,
)
from .schemas import (
    DeviceCreate,
    DeviceOut,
    HealthOut,
    LoginRequest,
    LoginResponse,
    RegionOut,
    SwitchConfirmRequest,
    SwitchOperationOut,
    SwitchPrepareRequest,
    UserOut,
)
from .switching import confirm_switch, prepare_switch
from .time_utils import utcnow


def build_api_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz", response_model=HealthOut, tags=["system"])
    def healthz() -> HealthOut:
        return HealthOut(status="ok")

    @router.post(
        "/v1/auth/login", response_model=LoginResponse, tags=["authentication"]
    )
    def login(payload: LoginRequest, session: DBSession) -> LoginResponse:
        raw_token, token, user = authenticate(
            session, payload.email, payload.password, settings
        )
        return LoginResponse(
            access_token=raw_token,
            expires_at=token.expires_at,
            user=UserOut.model_validate(user),
        )

    @router.get("/v1/me", response_model=UserOut, tags=["account"])
    def me(user: CurrentUser) -> UserOut:
        return UserOut.model_validate(user)

    @router.get("/v1/regions", response_model=list[RegionOut], tags=["regions"])
    def regions(user: CurrentUser, session: DBSession) -> list[RegionOut]:
        return get_authorized_regions(session, user.id)

    @router.get("/v1/devices", response_model=list[DeviceOut], tags=["devices"])
    def devices(user: CurrentUser, session: DBSession) -> list[DeviceOut]:
        rows = session.scalars(
            select(Device).where(Device.user_id == user.id).order_by(Device.created_at)
        ).all()
        return [serialize_device(session, device) for device in rows]

    @router.post("/v1/devices", response_model=DeviceOut, tags=["devices"])
    def register_device(
        payload: DeviceCreate, user: CurrentUser, session: DBSession
    ) -> DeviceOut:
        existing = session.scalar(
            select(Device).where(
                Device.user_id == user.id,
                Device.client_device_id == payload.client_device_id,
            )
        )
        if existing is not None:
            if existing.tunnel_public_key != payload.tunnel_public_key:
                raise APIError(
                    409,
                    "device_key_mismatch",
                    "The device exists with a different tunnel public key.",
                )
            existing.name = payload.name
            existing.last_seen_at = utcnow()
            session.commit()
            return serialize_device(session, existing)

        subscription = session.scalar(
            active_subscription_query(user.id).order_by(Subscription.ends_at.desc())
        )
        if subscription is None:
            raise APIError(
                403, "subscription_required", "An active subscription is required."
            )
        plan = session.get(Plan, subscription.plan_id)
        if plan is None or not plan.is_active:
            raise APIError(
                403, "plan_unavailable", "The subscription plan is unavailable."
            )
        device_count = session.query(Device).filter(Device.user_id == user.id).count()
        if device_count >= plan.max_devices:
            raise APIError(
                403, "device_limit_reached", "The subscription device limit is reached."
            )
        device = Device(
            user_id=user.id,
            client_device_id=payload.client_device_id,
            name=payload.name,
            platform=payload.platform,
            tunnel_public_key=payload.tunnel_public_key,
        )
        session.add(device)
        session.commit()
        return serialize_device(session, device)

    @router.post(
        "/v1/devices/{device_id}/switches",
        response_model=SwitchOperationOut,
        tags=["switching"],
    )
    def start_switch(
        device_id: str,
        payload: SwitchPrepareRequest,
        user: CurrentUser,
        session: DBSession,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
        ],
    ) -> SwitchOperationOut:
        return prepare_switch(
            session,
            user,
            device_id,
            payload.target_region_code,
            idempotency_key,
        )

    @router.post(
        "/v1/switches/{operation_id}/confirm",
        response_model=SwitchOperationOut,
        tags=["switching"],
    )
    def finish_switch(
        operation_id: str,
        payload: SwitchConfirmRequest,
        user: CurrentUser,
        session: DBSession,
    ) -> SwitchOperationOut:
        return confirm_switch(session, user, operation_id, payload.success)

    return router
