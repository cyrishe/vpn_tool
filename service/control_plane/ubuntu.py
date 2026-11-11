"""Fixed entry point for the Ubuntu control server."""
import os

from .app import create_app
from .config import Settings

app = create_app(Settings(
    database_url="sqlite:////var/lib/regional-vpn/control.db",
    environment="production",
    seed_demo_data=False,
    admin_token=os.getenv("VPN_ADMIN_TOKEN"),
))
