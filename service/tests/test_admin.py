import base64
from dataclasses import replace
from datetime import timedelta
from io import BytesIO
import json
import sys
import tarfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from control_plane.app import create_app
from control_plane.config import Settings
from control_plane.gateway_bootstrap import GatewayBootstrap
from control_plane.models import GatewayNode
from control_plane.security import issue_access_token
from control_plane.time_utils import utcnow

SERVER_KEY = base64.b64encode(bytes([1]) * 32).decode()
CLIENT_KEY = base64.b64encode(bytes([2]) * 32).decode()


@pytest.fixture()
def console(tmp_path):
    token = "vpn_admin_" + issue_access_token()
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'admin.db'}", environment="production",
                        seed_demo_data=False, admin_token=token)
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        yield client, {"Authorization": f"Bearer {token}"}


def create_region(client, admin, code, name):
    response = client.post("/admin/api/regions", headers=admin, json={
        "code": code, "name": name, "province_code": "CN-SH",
    })
    assert response.status_code == 201


def open_account(client, admin, regions):
    response = client.put("/admin/api/accounts/grant", headers=admin, json={
        "email": "tester@example.com", "password": "integration-password", "regions": regions, "days": 30,
    })
    assert response.status_code == 200
    login = client.post("/v1/auth/login", json={"email": "tester@example.com", "password": "integration-password"})
    assert login.status_code == 200
    return {"Authorization": "Bearer " + login.json()["access_token"]}


def test_admin_disabled_by_default(client):
    assert client.get("/admin").status_code == 404
    assert client.get("/admin/api/nodes").status_code == 404


def test_gateway_bundle_requires_admin_and_contains_only_installer_files(console):
    client, admin = console
    assert client.get("/admin/api/gateway-bundle").status_code == 401
    response = client.get("/admin/api/gateway-bundle", headers=admin)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert 'filename="regional-vpn-gateway.tar.gz"' in response.headers["Content-Disposition"]
    with tarfile.open(fileobj=BytesIO(response.content), mode="r:gz") as bundle:
        assert all(member.isfile() for member in bundle)
        assert set(bundle.getnames()) == {
            "scripts/setup-wireguard-gateway.sh",
            "scripts/install-wireguard-agent.sh",
            "service/control_plane/__init__.py",
            "service/control_plane/security.py",
            "service/gateway_agent/__init__.py",
            "service/gateway_agent/agent.py",
            "service/gateway_agent/regional-gateway.service",
        }


def test_ssh_bootstrap_reuses_identity_after_install_failure(console, tmp_path):
    _, admin = console
    helper = tmp_path / "ssh-helper"
    recorded = tmp_path / "first-enrollment.json"
    password = "test password $!"
    helper.write_text(
        f"#!{sys.executable}\n"
        "import io, json, os, shlex, subprocess, sys, tarfile\n"
        "from pathlib import Path\n"
        "assert 'VPN_GATEWAY_BOOTSTRAP_KEY' not in os.environ\n"
        f"assert os.environ['VPN_GATEWAY_SSH_PASSWORD'] == {password!r}\n"
        f"assert all({password!r} not in argument for argument in sys.argv)\n"
        "assert sys.argv[1] == '8.8.4.4'\n"
        "shell, option, command = shlex.split(sys.argv[2])\n"
        "assert (shell, option) == ('bash', '-c')\n"
        "subprocess.run(['/bin/bash', '-n', '-c', command], check=True)\n"
        "with tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()), mode='r:gz') as bundle:\n"
        "    if 'gateway.json' not in bundle.getnames():\n"
        f"        print({SERVER_KEY!r})\n"
        "        sys.exit(0)\n"
        "    assert bundle.getmember('gateway.json').mode == 0o600\n"
        "    enrollment = bundle.extractfile('gateway.json').read()\n"
        f"recorded = Path({str(recorded)!r})\n"
        "if not recorded.exists():\n"
        "    recorded.write_bytes(enrollment)\n"
        "    sys.exit(1)\n"
        "assert json.loads(recorded.read_bytes()) == json.loads(enrollment)\n"
    )
    helper.chmod(0o700)
    bootstrap = GatewayBootstrap(helper, "https://center.example.com", issue_access_token(), ssh_password=password)
    settings = replace(console[0].app.state.settings, database_url=f"sqlite:///{tmp_path / 'automatic.db'}",
                       gateway_bootstrap=bootstrap)
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        path = "/admin/api/gateway-bootstrap"
        assert client.get(path).status_code == 401
        assert client.get(path, headers=admin).json() == {"enabled": True}
        create_region(client, admin, "shanghai", "上海")
        create_region(client, admin, "beijing", "北京")
        request = {"ip": "8.8.4.4", "region": "shanghai"}
        assert client.post(path, headers=admin, json={**request, "ip": "127.0.0.1"}).status_code == 422
        assert client.post(path, headers=admin, json=request).status_code == 502
        credential = json.loads(recorded.read_text())
        first = client.get("/admin/api/nodes", headers=admin).json()
        assert len(first) == 1 and first[0]["id"] == credential["gateway_id"]
        assert client.post(path, headers=admin, json={**request, "region": "beijing"}).status_code == 409
        response = client.post(path, headers=admin, json=request)
        assert response.status_code == 200
        assert response.json() == {"node": first[0], "public_key": SERVER_KEY}
        assert credential["token"] not in response.text
        heartbeat = client.post("/v1/gateway/sync", headers={"Authorization": f"Bearer {credential['token']}"},
                                json={"public_key": SERVER_KEY})
        assert heartbeat.status_code == 200
        response = client.post(path, headers=admin, json=request)
        assert response.json()["node"]["status"] == "verifying"
        assert not response.json()["node"]["accepting_connections"]


def test_admin_api_rejects_user_and_cannot_echo_credentials(console):
    client, admin = console
    assert client.get("/admin").status_code == 200
    assert "frame-ancestors 'none'" in client.get("/admin").headers["Content-Security-Policy"]
    assert client.get("/admin/console.js").status_code == 200
    create_region(client, admin, "shanghai", "上海")
    user = open_account(client, admin, ["shanghai"])
    assert client.get("/admin/api/regions").status_code == 401
    assert client.get("/admin/api/regions", headers=user).status_code == 401
    assert client.get("/v1/me", headers=admin).status_code == 401
    response = client.put("/admin/api/accounts/grant", headers=admin, json={
        "email": "tester@example.com", "password": "secret-short", "regions": ["shanghai"], "days": 30,
    })
    assert response.status_code == 409
    response = client.put("/admin/api/accounts/grant", headers=admin, json={
        "email": "tester@example.com", "password": "secret", "regions": ["shanghai"], "days": 30,
    })
    assert response.status_code == 422
    assert "secret" not in response.text
    assert response.headers["Cache-Control"] == "no-store"


def test_node_enrollment_drain_and_retirement_through_console(console):
    client, admin = console
    create_region(client, admin, "shanghai", "上海")
    payload = {"name": "shanghai-01", "region": "shanghai", "endpoint": "8.8.4.4:51820",
               "public_key": SERVER_KEY, "capacity": 10}
    invalid = client.post("/admin/api/nodes", headers=admin, json={**payload, "endpoint": "127.0.0.1:51820"})
    assert invalid.status_code == 422
    response = client.post("/admin/api/nodes", headers=admin, json=payload)
    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    enrolled = response.json()
    assert client.post("/admin/api/nodes", headers=admin, json=payload).status_code == 409
    node_id = enrolled["node"]["id"]
    gateway_token = enrolled["credential"]["token"]
    gateway_auth = {"Authorization": f"Bearer {gateway_token}"}
    listing = client.get("/admin/api/nodes?region=shanghai", headers=admin)
    assert gateway_token not in listing.text
    assert listing.json()[0]["heartbeat_age_seconds"] is None
    assert client.get(f"/admin/api/nodes/{node_id}", headers=admin).json() == listing.json()[0]
    assert client.get(f"/admin/api/nodes/{node_id}", headers=gateway_auth).status_code == 401
    assert client.get("/admin/api/nodes", headers=gateway_auth).status_code == 401

    def state(action):
        return client.post(f"/admin/api/nodes/{node_id}/state", headers=admin, json={"action": action})

    def sync(applied=None):
        return client.post("/v1/gateway/sync", headers=gateway_auth, json={
            "public_key": SERVER_KEY, "applied_assignment_ids": applied or [],
        })

    assert state("online").status_code == 409
    assert state("drain").status_code == 409
    assert sync().status_code == 200
    assert client.get(f"/admin/api/nodes/{node_id}", headers=admin).json()["status"] == "verifying"
    with client.app.state.database.session_factory() as session:
        session.scalar(select(GatewayNode).where(GatewayNode.id == node_id)).last_heartbeat_at = utcnow() - timedelta(seconds=31)
        session.commit()
    assert state("online").status_code == 409
    assert sync().status_code == 200
    assert state("online").json()["accepting_connections"]
    user = open_account(client, admin, ["shanghai"])
    device = client.post("/v1/devices", headers=user, json={
        "client_device_id": "test-admin-device", "name": "mac", "platform": "macos", "tunnel_public_key": CLIENT_KEY,
    }).json()

    def switch(key):
        return client.post(f"/v1/devices/{device['id']}/switches", headers={**user, "Idempotency-Key": key},
                           json={"target_region_code": "shanghai"})

    operation = switch("first-switch").json()
    peer = sync().json()["peers"][0]
    sync([peer["assignment_id"]])
    operation_url = f"/v1/switches/{operation['operation_id']}"
    assert client.post(operation_url + "/confirm", headers=user, json={"success": True}).json()["status"] == "committed"
    drained = state("drain").json()
    assert drained["status"] == "draining" and not drained["accepting_connections"]
    assert drained["current_peers"] == 1 and len(sync().json()["peers"]) == 1
    assert switch("second-switch").status_code == 503
    assert state("retire").json()["current_peers"] == 0
    assert state("retire").status_code == 200
    assert state("online").status_code == 409
    assert sync().status_code == 403
    assert client.get("/v1/devices", headers=user).json()[0]["active_region_code"] is None


def test_manual_grant_and_region_changes_reach_client(console):
    client, admin = console
    create_region(client, admin, "shanghai", "上海")
    create_region(client, admin, "beijing", "北京")
    user = open_account(client, admin, ["shanghai"])

    def user_regions():
        return client.get("/v1/regions", headers=user).json()

    assert [region["code"] for region in user_regions()] == ["shanghai"]
    response = client.put("/admin/api/regions/shanghai", headers=admin, json={
        "name": "上海出口", "province_code": "CN-SH", "is_enabled": True,
    })
    assert response.status_code == 200
    assert user_regions()[0]["name"] == "上海出口"
    response = client.put("/admin/api/accounts/grant", headers=admin, json={
        "email": "TESTER@example.com", "regions": ["beijing"], "days": 60,
    })
    assert response.status_code == 200
    assert response.json()["regions"] == ["beijing"]
    assert response.json()["expires_at"].endswith("Z")
    assert client.post("/admin/api/accounts/lookup", headers=admin,
                       json={"email": "tester@example.com"}).json() == response.json()
    assert [region["code"] for region in user_regions()] == ["beijing"]
    response = client.put("/admin/api/regions/beijing", headers=admin, json={
        "name": "北京", "province_code": "CN-BJ", "is_enabled": False,
    })
    assert response.status_code == 200
    assert user_regions() == []
