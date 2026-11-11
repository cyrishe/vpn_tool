import base64
from datetime import timedelta

from sqlalchemy import select

from control_plane.models import GatewayCredential, GatewayNode, LogicalRegion, Subscription
from control_plane.gateways import change_gateway_status
from control_plane.security import hash_access_token
from control_plane.time_utils import utcnow
from gateway_agent.agent import Agent, WireGuard


KEY = base64.b64encode(bytes([1]) * 32).decode()
CLIENT_KEY = base64.b64encode(bytes([2]) * 32).decode()


def enroll(client):
    with client.app.state.database.session_factory() as session:
        for node in session.scalars(select(GatewayNode)).all():
            node.status = "terminated"
        region = session.scalar(select(LogicalRegion).where(LogicalRegion.code == "shanghai"))
        for i in range(2):
            node = GatewayNode(region_id=region.id, name=f"sh-{i}", provider="wireguard",
                cloud_region="shanghai", endpoint=f"198.51.100.{i + 1}:51820",
                server_public_key=KEY, status="provisioning", capacity=10)
            session.add(node)
            session.flush()
            session.add(GatewayCredential(gateway_id=node.id, token_hash=hash_access_token(f"gateway-token-{i}")))
        session.commit()


def sync(client, index=0, applied=None):
    return client.post("/v1/gateway/sync",
        headers={"Authorization": f"Bearer gateway-token-{index}"},
        json={"public_key": KEY, "applied_assignment_ids": applied or []})


def set_node(client, index, action):
    with client.app.state.database.session_factory() as session:
        node = session.scalar(select(GatewayNode).where(GatewayNode.name == f"sh-{index}"))
        change_gateway_status(session, node, action)
        session.commit()


def register(client, headers, suffix="one"):
    return client.post("/v1/devices", headers=headers, json={
        "client_device_id": "test-device-" + suffix, "name": suffix, "platform": "macos",
        "tunnel_public_key": CLIENT_KEY if suffix == "one" else base64.b64encode(bytes([3]) * 32).decode(),
    }).json()["id"]


def prepare(client, headers, device_id, suffix="one"):
    return client.post(f"/v1/devices/{device_id}/switches",
        headers={**headers, "Idempotency-Key": "gateway-switch-" + suffix},
        json={"target_region_code": "shanghai"})


def test_registered_gateways_schedule_and_wait_for_real_ack(client, auth_headers):
    enroll(client)
    device = register(client, auth_headers)
    assert prepare(client, auth_headers, device).status_code == 503
    assert sync(client).status_code == 200
    assert sync(client, 1).status_code == 200
    assert prepare(client, auth_headers, device).status_code == 503
    set_node(client, 0, "online")
    set_node(client, 1, "online")
    operation = prepare(client, auth_headers, device).json()
    assert operation["profile"] is None
    op_url = f"/v1/switches/{operation['operation_id']}"
    assert client.post(op_url + "/confirm", headers=auth_headers, json={"success": True}).status_code == 409
    peers = sync(client).json()["peers"]
    assert len(peers) == 1
    assert peers[0]["public_key"] == CLIENT_KEY
    # Another gateway cannot acknowledge a peer assigned to the first node.
    sync(client, 1, [peers[0]["assignment_id"]])
    assert client.get(op_url, headers=auth_headers).json()["profile"] is None
    sync(client, 0, [peers[0]["assignment_id"]])
    profile = client.get(op_url, headers=auth_headers).json()["profile"]
    assert profile["endpoint"] == "198.51.100.1:51820"
    assert client.post(op_url + "/confirm", headers=auth_headers, json={"success": True}).json()["status"] == "committed"
    second = register(client, auth_headers, "two")
    prepare(client, auth_headers, second, "two")
    # Same region, different underlying gateway selected by the scheduler.
    assert len(sync(client, 1).json()["peers"]) == 1
    client.post(f"/v1/devices/{device}/disconnect", headers=auth_headers)
    assert sync(client).json()["peers"] == []


def test_expiry_and_gateway_authentication(client, auth_headers):
    enroll(client)
    assert client.post("/v1/gateway/sync", json={"public_key": KEY}).status_code == 401
    assert client.post("/v1/gateway/sync", headers=auth_headers, json={"public_key": KEY}).status_code == 401
    sync(client)
    set_node(client, 0, "online")
    device = register(client, auth_headers)
    operation = prepare(client, auth_headers, device).json()
    peer = sync(client).json()["peers"][0]
    with client.app.state.database.session_factory() as session:
        for subscription in session.scalars(select(Subscription)).all():
            subscription.ends_at = utcnow() - timedelta(seconds=1)
        session.commit()
    assert sync(client, applied=[peer["assignment_id"]]).json()["peers"] == []
    response = client.get(f"/v1/switches/{operation['operation_id']}", headers=auth_headers)
    assert response.json()["status"] == "rolled_back"


def test_draining_preserves_existing_peer_and_retire_revokes_node(client, auth_headers):
    enroll(client)
    sync(client)
    set_node(client, 0, "online")
    device = register(client, auth_headers)
    operation = prepare(client, auth_headers, device).json()
    peer = sync(client).json()["peers"][0]
    sync(client, applied=[peer["assignment_id"]])
    client.post(f"/v1/switches/{operation['operation_id']}/confirm",
                headers=auth_headers, json={"success": True})
    set_node(client, 0, "drain")
    assert len(sync(client).json()["peers"]) == 1
    assert prepare(client, auth_headers, register(client, auth_headers, "two"), "two").status_code == 503
    set_node(client, 0, "retire")
    assert sync(client).status_code == 403
    assert client.get("/v1/devices", headers=auth_headers).json()[0]["active_region_code"] is None


def test_agent_lease_expiry_fails_closed():
    class FakeWG:
        peers = []
        def public_key(self): return KEY
        def reconcile(self, peers): self.peers = peers
    clock = [0]
    reachable = [True]
    def synchronize(key, applied):
        if not reachable[0]: raise ConnectionError()
        return {"peers": [{"assignment_id": "one", "public_key": CLIENT_KEY,
                           "address": "10.77.1.2/32", "lease_seconds": 10}]}
    wg = FakeWG()
    agent = Agent(wg, synchronize, lambda: clock[0])
    agent.tick()
    assert len(wg.peers) == 1
    reachable[0] = False
    clock[0] = 9
    agent.tick()
    assert len(wg.peers) == 1
    clock[0] = 10
    agent.tick()
    assert wg.peers == []


def test_wireguard_updates_are_incremental_and_validate_before_execution():
    import subprocess
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")
    wg = WireGuard("wg-regional", run)
    wg.reconcile([{"public_key": CLIENT_KEY, "address": "10.77.1.2/32"}])
    assert calls[-1] == ["wg", "set", "wg-regional", "peer", CLIENT_KEY, "allowed-ips", "10.77.1.2/32"]
    before = len(calls)
    import pytest
    with pytest.raises(ValueError):
        wg.reconcile([{"public_key": "bad-key", "address": "0.0.0.0/0"}])
    assert len(calls) == before
