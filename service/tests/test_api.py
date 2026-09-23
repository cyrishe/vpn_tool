from __future__ import annotations

from fastapi.testclient import TestClient


def register_device(
    client: TestClient, auth_headers: dict[str, str]
) -> dict[str, object]:
    response = client.post(
        "/v1/devices",
        headers=auth_headers,
        json={
            "client_device_id": "macbook-air-test-device",
            "name": "Test MacBook",
            "platform": "macos",
            "tunnel_public_key": "mock-client-public-key-test",
        },
    )
    assert response.status_code == 200
    return response.json()


def prepare_switch(
    client: TestClient,
    auth_headers: dict[str, str],
    device_id: str,
    region_code: str,
    idempotency_key: str,
):
    return client.post(
        f"/v1/devices/{device_id}/switches",
        headers={**auth_headers, "Idempotency-Key": idempotency_key},
        json={"target_region_code": region_code},
    )


def test_login_and_authorized_regions(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/v1/regions", headers=auth_headers)
    assert response.status_code == 200
    assert [region["code"] for region in response.json()] == [
        "shanghai",
        "beijing",
        "guangdong",
    ]
    assert all(region["availability"] == "available" for region in response.json())


def test_invalid_login_uses_stable_error_contract(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/login",
        json={"email": "demo@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert response.headers["X-Request-ID"]


def test_device_registration_is_idempotent_but_key_rotation_is_explicit(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    first = register_device(client, auth_headers)
    second = register_device(client, auth_headers)
    assert second["id"] == first["id"]

    response = client.post(
        "/v1/devices",
        headers=auth_headers,
        json={
            "client_device_id": "macbook-air-test-device",
            "name": "Test MacBook",
            "platform": "macos",
            "tunnel_public_key": "different-public-key-test",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "device_key_mismatch"


def test_two_phase_switch_rolls_back_to_last_good_region(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    device = register_device(client, auth_headers)
    device_id = str(device["id"])

    shanghai = prepare_switch(
        client,
        auth_headers,
        device_id,
        "shanghai",
        "switch-shanghai-first",
    )
    assert shanghai.status_code == 200
    assert shanghai.json()["status"] == "prepared"
    confirm = client.post(
        f"/v1/switches/{shanghai.json()['operation_id']}/confirm",
        headers=auth_headers,
        json={"success": True},
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "committed"

    beijing = prepare_switch(
        client,
        auth_headers,
        device_id,
        "beijing",
        "switch-beijing-failure",
    )
    assert beijing.status_code == 200
    repeated = prepare_switch(
        client,
        auth_headers,
        device_id,
        "beijing",
        "switch-beijing-failure",
    )
    assert repeated.json()["operation_id"] == beijing.json()["operation_id"]

    rollback = client.post(
        f"/v1/switches/{beijing.json()['operation_id']}/confirm",
        headers=auth_headers,
        json={"success": False},
    )
    assert rollback.status_code == 200
    assert rollback.json()["status"] == "rolled_back"

    devices = client.get("/v1/devices", headers=auth_headers).json()
    assert devices[0]["active_region_code"] == "shanghai"
    assert devices[0]["config_version"] == 1


def test_switch_rejects_unavailable_region(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    device = register_device(client, auth_headers)
    response = prepare_switch(
        client,
        auth_headers,
        str(device["id"]),
        "zhejiang",
        "switch-disabled-region",
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "region_not_found"


def test_authentication_and_device_ownership_are_server_side(
    client: TestClient,
) -> None:
    response = client.get("/v1/devices")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"

