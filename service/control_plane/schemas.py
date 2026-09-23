from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    status: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


class RegionOut(BaseModel):
    code: str
    name: str
    province_code: str
    availability: str


class DeviceCreate(BaseModel):
    client_device_id: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    platform: str = Field(pattern="^(macos|ios|android|windows|linux)$")
    tunnel_public_key: str = Field(min_length=8, max_length=256)


class DeviceOut(BaseModel):
    id: str
    client_device_id: str
    name: str
    platform: str
    tunnel_public_key: str
    active_region_code: str | None
    config_version: int


class SwitchPrepareRequest(BaseModel):
    target_region_code: str = Field(min_length=2, max_length=64)


class TunnelProfileOut(BaseModel):
    profile_id: str
    config_version: int
    region_code: str
    gateway_id: str
    endpoint: str
    server_public_key: str
    client_address: str
    dns_servers: list[str]
    allowed_ips: list[str]


class SwitchOperationOut(BaseModel):
    operation_id: str
    status: str
    device_id: str
    target_region_code: str
    profile: TunnelProfileOut | None


class SwitchConfirmRequest(BaseModel):
    success: bool


class HealthOut(BaseModel):
    status: str

