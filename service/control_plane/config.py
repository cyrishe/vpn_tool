from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .gateway_bootstrap import GatewayBootstrap


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./regional_vpn.db"
    environment: str = "development"
    demo_email: str = "demo@example.com"
    demo_password: str = "demo-password"
    token_ttl_hours: int = 12
    seed_demo_data: bool = True
    admin_token: str | None = field(default=None, repr=False)
    gateway_ca_certificate: Path | None = None
    gateway_bootstrap: GatewayBootstrap | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        environment = os.getenv("VPN_ENVIRONMENT", "development")
        return cls(
            database_url=os.getenv(
                "VPN_DATABASE_URL", "sqlite:///./regional_vpn.db"
            ),
            environment=environment,
            demo_email=os.getenv("VPN_DEMO_EMAIL", "demo@example.com"),
            demo_password=os.getenv("VPN_DEMO_PASSWORD", "demo-password"),
            token_ttl_hours=int(os.getenv("VPN_TOKEN_TTL_HOURS", "12")),
            seed_demo_data=environment == "development",
            admin_token=os.getenv("VPN_ADMIN_TOKEN"),
        )

