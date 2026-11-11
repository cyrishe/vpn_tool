"""Operator-only API and console for the control server."""
from __future__ import annotations

import hmac
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, StringConstraints, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import DBSession, bearer_scheme
from .database import begin_write
from .gateway_bootstrap import GatewayBootstrap
from .errors import APIError
from .gateway_bundle import BUNDLE_NAME, build_gateway_bundle
from .gateways import LEASE_SECONDS, change_gateway_status, sweep
from .models import GatewayCredential, GatewayNode, LogicalRegion, Plan, PlanRegion, Subscription, User
from .query_service import active_subscription_query
from .security import hash_access_token, hash_password, issue_access_token, valid_public_key
from .time_utils import utcnow

ASSETS = Path(__file__).with_name("admin_ui")
LOG = logging.getLogger("uvicorn.error")
PAGE_SIZE = 50
Code = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Province = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9-]{0,31}$")]
Email = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254,
                                         pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]
Offset = Annotated[int, Query(ge=0)]


def public_ipv4(host: str) -> IPv4Address:
    ip = IPv4Address(host)
    if not ip.is_global or ip.is_multicast or ip.is_reserved:
        raise ValueError("Use a public IPv4 address.")
    return ip


class RegionSettings(BaseModel):
    name: Label
    province_code: Province
    is_enabled: bool = True


class RegionCreate(RegionSettings):
    code: Code


class RegionOut(RegionCreate):
    pass


class GatewayCreate(BaseModel):
    name: Code
    region: Code
    endpoint: str = Field(max_length=21)
    public_key: str = Field(min_length=44, max_length=44)
    capacity: int = Field(default=100, ge=1, le=65534)

    @field_validator("endpoint")
    @classmethod
    def endpoint_is_ipv4(cls, value: str) -> str:
        host, _, port = value.rpartition(":")
        try:
            ip = public_ipv4(host)
            if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
                raise ValueError
        except ValueError:
            raise ValueError("Use a public IPv4 address and UDP port.") from None
        return f"{ip}:{int(port)}"

    @field_validator("public_key")
    @classmethod
    def key_is_valid(cls, value: str) -> str:
        if not valid_public_key(value):
            raise ValueError("Use a WireGuard public key.")
        return value


class GatewayOut(BaseModel):
    id: str
    name: str
    region: str
    endpoint: str
    status: str
    heartbeat_age_seconds: int | None
    accepting_connections: bool
    current_peers: int
    capacity: int


class GatewayEnrollment(BaseModel):
    node: GatewayOut
    credential: dict[Literal["gateway_id", "token"], str]


class BootstrapRequest(BaseModel):
    ip: str = Field(max_length=15)
    region: Code

    @field_validator("ip")
    @classmethod
    def validate_ip(cls, value: str) -> str:
        return str(public_ipv4(value))


class BootstrapResult(BaseModel):
    node: GatewayOut
    public_key: str


class BootstrapAvailability(BaseModel):
    enabled: bool


class GatewayAction(BaseModel):
    action: Literal["online", "drain", "retire"]


class ManualGrant(BaseModel):
    email: Email
    password: str | None = Field(default=None, min_length=12, max_length=128)
    regions: list[Code] = Field(min_length=1, max_length=50)
    days: int = Field(ge=1, le=366)


class AccountLookup(BaseModel):
    email: Email


class AccountOut(BaseModel):
    email: str
    status: str
    regions: list[str]
    expires_at: datetime | None


def region_out(region: LogicalRegion) -> RegionOut:
    return RegionOut(code=region.code, name=region.name, province_code=region.province_code,
                     is_enabled=region.is_enabled)


def gateway_out(node: GatewayNode, region: LogicalRegion, now: datetime) -> GatewayOut:
    age = (now - node.last_heartbeat_at).total_seconds()
    return GatewayOut(id=node.id, name=node.name, region=region.code, endpoint=node.endpoint,
                      status=node.status, heartbeat_age_seconds=None if node.status == "provisioning" else max(0, int(age)),
                      accepting_connections=region.is_enabled and node.status == "ready"
                      and node.current_peers < node.capacity and (node.provider == "mock" or age < LEASE_SECONDS),
                      current_peers=node.current_peers, capacity=node.capacity)


def account_out(session: Session, account: User) -> AccountOut:
    subscription = session.scalar(active_subscription_query(account.id).order_by(Subscription.ends_at.desc()))
    regions = list(session.scalars(select(LogicalRegion.code).join(PlanRegion).where(
        PlanRegion.plan_id == subscription.plan_id).order_by(LogicalRegion.code))) if subscription else []
    return AccountOut(email=account.email, status=account.status, regions=regions,
                      expires_at=subscription.ends_at.replace(tzinfo=UTC) if subscription else None)


def commit_admin(session: Session, action: str, target: str) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise APIError(409, "admin_conflict", "记录已存在或状态已变化，请刷新后重试。") from None
    LOG.info("VPN admin action=%s target=%s", action, target)


def add_gateway(session: Session, payload: GatewayCreate, region: LogicalRegion,
                gateway_id: str, gateway_token: str) -> GatewayNode:
    node = GatewayNode(id=gateway_id, name=payload.name, region_id=region.id, provider="wireguard",
                       cloud_region=region.code, endpoint=payload.endpoint, server_public_key=payload.public_key,
                       status="provisioning", capacity=payload.capacity)
    session.add(node)
    try:
        session.flush()
    except IntegrityError:
        raise APIError(409, "admin_node_exists", "节点名称已存在，请为新机器使用新名称。") from None
    session.add(GatewayCredential(gateway_id=node.id, token_hash=hash_access_token(gateway_token)))
    return node


def bootstrap_target(session: Session, payload: BootstrapRequest, endpoint: str,
                     bootstrap: GatewayBootstrap) -> tuple[LogicalRegion, GatewayNode | None]:
    region = session.scalar(select(LogicalRegion).where(LogicalRegion.code == payload.region))
    if region is None or not region.is_enabled:
        raise APIError(404, "admin_region_not_found", "请选择已启用的地域。")
    matches = session.scalars(select(GatewayNode).where(
        GatewayNode.endpoint == endpoint, GatewayNode.status != "terminated"
    )).all()
    if not matches:
        return region, None
    node = matches[0]
    credential = session.get(GatewayCredential, node.id)
    if (len(matches) != 1 or node.region_id != region.id or credential is None
            or not hmac.compare_digest(credential.token_hash, hash_access_token(bootstrap.token(node.id)))):
        raise APIError(409, "gateway_endpoint_in_use", "这个 IP 已有节点登记。请在节点列表处理现有记录。")
    return region, node


def build_admin_router(token: str, gateway_ca_certificate: Path | None = None,
                       bootstrap: GatewayBootstrap | None = None) -> APIRouter:
    if not re.fullmatch(r"vpn_admin_[A-Za-z0-9_-]{43,}", token):
        raise ValueError("Generate VPN_ADMIN_TOKEN using vpn_admin_ plus secrets.token_urlsafe(32).")
    token_hash = hash_access_token(token)
    bootstrap_lock = Lock()

    def require_admin(credentials=Depends(bearer_scheme)):
        if credentials is None or not hmac.compare_digest(hash_access_token(credentials.credentials), token_hash):
            raise APIError(401, "admin_auth_required", "请输入有效的管理员访问密钥。")

    router = APIRouter(prefix="/admin", include_in_schema=False)
    api = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])

    @router.get("")
    def index():
        return FileResponse(ASSETS / "index.html")

    @router.get("/console.css")
    def styles():
        return FileResponse(ASSETS / "console.css")

    @router.get("/console.js")
    def script():
        return FileResponse(ASSETS / "console.js", media_type="text/javascript")

    @api.get("/gateway-bundle", response_class=Response)
    def download_gateway_bundle() -> Response:
        try:
            payload = build_gateway_bundle(gateway_ca_certificate)
        except (OSError, ValueError):
            LOG.exception("Could not package gateway installer")
            raise APIError(503, "gateway_bundle_unavailable", "部署包暂不可用，请检查中心部署文件。") from None
        return Response(payload, media_type="application/gzip",
                        headers={"Content-Disposition": f'attachment; filename="{BUNDLE_NAME}"'})

    @api.get("/regions")
    def regions(session: DBSession, offset: Offset = 0) -> list[RegionOut]:
        rows = session.scalars(select(LogicalRegion).order_by(LogicalRegion.code).offset(offset).limit(PAGE_SIZE))
        return [region_out(row) for row in rows]

    @api.post("/regions", status_code=201)
    def create_region(payload: RegionCreate, session: DBSession) -> RegionOut:
        region = LogicalRegion(**payload.model_dump())
        session.add(region)
        commit_admin(session, "region.create", region.code)
        return region_out(region)

    @api.put("/regions/{code}")
    def edit_region(code: Code, payload: RegionSettings, session: DBSession) -> RegionOut:
        begin_write(session)
        region = session.scalar(select(LogicalRegion).where(LogicalRegion.code == code))
        if region is None:
            raise APIError(404, "admin_region_not_found", "未找到地域。")
        was_enabled = region.is_enabled
        for field, value in payload.model_dump().items():
            setattr(region, field, value)
        if was_enabled and not region.is_enabled:
            session.flush()
            sweep(session)
        commit_admin(session, "region.update", code)
        return region_out(region)

    @api.get("/nodes")
    def nodes(session: DBSession, region: Code | None = None, offset: Offset = 0) -> list[GatewayOut]:
        query = select(GatewayNode, LogicalRegion).join(LogicalRegion)
        if region:
            query = query.where(LogicalRegion.code == region)
        now = utcnow()
        return [gateway_out(node, location, now) for node, location in session.execute(
            query.order_by(LogicalRegion.code, GatewayNode.name).offset(offset).limit(PAGE_SIZE))]

    @api.post("/nodes", status_code=201)
    def enroll(payload: GatewayCreate, session: DBSession) -> GatewayEnrollment:
        begin_write(session)
        region = session.scalar(select(LogicalRegion).where(LogicalRegion.code == payload.region))
        if region is None:
            raise APIError(404, "admin_region_not_found", "请先创建对应地域。")
        gateway_token = issue_access_token()
        node = add_gateway(session, payload, region, str(uuid.uuid4()), gateway_token)
        commit_admin(session, "node.enroll", node.id)
        return GatewayEnrollment(node=gateway_out(node, region, utcnow()),
                                 credential={"gateway_id": node.id, "token": gateway_token})

    @api.get("/gateway-bootstrap")
    def bootstrap_availability() -> BootstrapAvailability:
        return BootstrapAvailability(enabled=bootstrap is not None)

    @api.post("/gateway-bootstrap")
    def bootstrap_node(payload: BootstrapRequest, session: DBSession) -> BootstrapResult:
        if bootstrap is None:
            raise APIError(503, "gateway_bootstrap_disabled", "中心尚未配置 SSH 自动接入。")
        if not bootstrap_lock.acquire(blocking=False):
            raise APIError(409, "gateway_bootstrap_busy", "中心正在接入另一个节点，请稍后重试。")
        endpoint = f"{payload.ip}:51820"
        try:
            region, node = bootstrap_target(session, payload, endpoint, bootstrap)
            if node is not None and node.status != "provisioning":
                return BootstrapResult(node=gateway_out(node, region, utcnow()), public_key=node.server_public_key)
            session.rollback()

            key = bootstrap.prepare(payload.ip, gateway_ca_certificate)
            begin_write(session)
            region, node = bootstrap_target(session, payload, endpoint, bootstrap)
            if node is not None and node.server_public_key != key:
                raise APIError(409, "gateway_bootstrap_key_changed", "该 IP 的 WireGuard 公钥已变化，请确认是否更换了机器。")
            if node is None:
                identity = uuid.uuid4()
                node = add_gateway(
                    session, GatewayCreate(name=f"{region.code[:40]}-{identity.hex[:12]}", region=region.code,
                                           endpoint=endpoint, public_key=key),
                    region, str(identity), bootstrap.token(str(identity)),
                )
            node_id = node.id
            commit_admin(session, "node.bootstrap", node_id)

            bootstrap.install(payload.ip, gateway_ca_certificate, key, {
                "gateway_id": node_id, "token": bootstrap.token(node_id),
            })
            session.refresh(node)
            session.refresh(region)
            return BootstrapResult(node=gateway_out(node, region, utcnow()), public_key=key)
        except (OSError, ValueError):
            LOG.exception("Could not package automatic gateway installer")
            raise APIError(503, "gateway_bundle_unavailable", "部署包暂不可用，请检查中心部署文件。") from None
        finally:
            bootstrap_lock.release()

    @api.get("/nodes/{node_id}")
    def get_node(node_id: uuid.UUID, session: DBSession) -> GatewayOut:
        node = session.get(GatewayNode, str(node_id))
        if node is None:
            raise APIError(404, "admin_node_not_found", "未找到节点。")
        region = session.get(LogicalRegion, node.region_id)
        return gateway_out(node, region, utcnow())

    @api.post("/nodes/{node_id}/state")
    def lifecycle(node_id: uuid.UUID, payload: GatewayAction, session: DBSession) -> GatewayOut:
        begin_write(session)
        node = session.get(GatewayNode, str(node_id))
        if node is None:
            raise APIError(404, "admin_node_not_found", "未找到节点。")
        try:
            if not (node.status == "terminated" and payload.action == "retire"):
                change_gateway_status(session, node, payload.action)
        except ValueError as error:
            raise APIError(409, "admin_invalid_node_transition", str(error)) from None
        region = session.get(LogicalRegion, node.region_id)
        commit_admin(session, f"node.{payload.action}", node.id)
        return gateway_out(node, region, utcnow())

    @api.post("/accounts/lookup")
    def lookup(payload: AccountLookup, session: DBSession) -> AccountOut:
        account = session.scalar(select(User).where(User.email == payload.email))
        if account is None:
            raise APIError(404, "admin_account_not_found", "未找到此账号，可以设置初始密码后开通。")
        return account_out(session, account)

    @api.put("/accounts/grant")
    def grant(payload: ManualGrant, session: DBSession) -> AccountOut:
        password_hash = hash_password(payload.password) if payload.password else None
        begin_write(session)
        codes = set(payload.regions)
        regions = list(session.scalars(select(LogicalRegion).where(
            LogicalRegion.code.in_(codes), LogicalRegion.is_enabled.is_(True))))
        if len(regions) != len(codes):
            raise APIError(422, "admin_region_unavailable", "请选择存在且已启用的地域。")
        account = session.scalar(select(User).where(User.email == payload.email))
        if account is None:
            if not password_hash:
                raise APIError(422, "admin_initial_password_required", "新账号需要设置初始密码。")
            account = User(email=payload.email, password_hash=password_hash)
            session.add(account)
            session.flush()
        elif password_hash or account.status != "active":
            raise APIError(409, "admin_account_conflict", "现有账号请留空密码，停用账号不能开通。")
        current = session.scalar(active_subscription_query(account.id).order_by(Subscription.ends_at.desc()))
        plan = Plan(code=f"personal-{uuid.uuid4().hex}", name="Personal",
                    max_devices=session.get(Plan, current.plan_id).max_devices if current else 3)
        session.add(plan)
        session.flush()
        session.add_all(PlanRegion(plan_id=plan.id, region_id=region.id) for region in regions)
        now = utcnow()
        session.execute(update(Subscription).where(
            Subscription.user_id == account.id, Subscription.status == "active"
        ).values(status="cancelled"))
        session.add(Subscription(user_id=account.id, plan_id=plan.id, status="active",
                                 starts_at=now, ends_at=now + timedelta(days=payload.days)))
        session.flush()
        sweep(session)
        commit_admin(session, "account.grant", account.id)
        return account_out(session, account)

    router.include_router(api)
    return router
