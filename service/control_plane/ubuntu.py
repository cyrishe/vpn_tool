"""Fixed entry point for the Ubuntu control server."""
import logging
import os
from pathlib import Path

from .app import create_app
from .config import Settings
from .gateway_bootstrap import GatewayBootstrap

ssh_helper = os.getenv("VPN_GATEWAY_SSH_HELPER")
bootstrap = None
if ssh_helper:
    try:
        bootstrap = GatewayBootstrap(
            ssh_helper=Path(ssh_helper),
            center_url=os.getenv("VPN_GATEWAY_CONTROL_URL", ""),
            enrollment_key=os.getenv("VPN_GATEWAY_BOOTSTRAP_KEY", ""),
        )
    except ValueError:
        logging.getLogger("uvicorn.error").error("SSH gateway bootstrap disabled: invalid center configuration.")

app = create_app(Settings(
    database_url="sqlite:////var/lib/regional-vpn/control.db",
    environment="production",
    seed_demo_data=False,
    admin_token=os.getenv("VPN_ADMIN_TOKEN"),
    gateway_ca_certificate=Path("/etc/regional-vpn/control.crt"),
    gateway_bootstrap=bootstrap,
))
