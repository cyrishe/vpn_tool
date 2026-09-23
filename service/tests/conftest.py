from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from control_plane.app import create_app  # noqa: E402
from control_plane.config import Settings  # noqa: E402


@pytest.fixture()
def client(tmp_path: Path):
    database_path = tmp_path / "test.db"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        environment="test",
        demo_email="demo@example.com",
        demo_password="demo-password",
        token_ttl_hours=1,
        seed_demo_data=True,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/v1/auth/login",
        json={"email": "demo@example.com", "password": "demo-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}

