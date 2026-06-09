import asyncio

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.elder_sessions import clear_all_sessions
from backend.main import app


@pytest.fixture(autouse=True)
def reset_session_state(monkeypatch):
    monkeypatch.setattr(main_module, "CARE4U_DEMO_MODE", True)
    monkeypatch.setattr(main_module, "ADMIN_PASSWORD", "")
    monkeypatch.setattr(main_module, "ADMIN_USERS", "")
    clear_all_sessions()
    with main_module.admin_auth_fail_lock:
        main_module.admin_auth_fail_counts.clear()
    with main_module.chat_background_results_lock:
        main_module.chat_background_results.clear()
    yield
    clear_all_sessions()
    with main_module.admin_auth_fail_lock:
        main_module.admin_auth_fail_counts.clear()
    with main_module.chat_background_results_lock:
        main_module.chat_background_results.clear()


@pytest.fixture
def local_client():
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        yield client


def issue_and_login(client, elder_id="W001"):
    pin_response = client.post(
        "/api/admin/elder-pin",
        json={"elder_id": elder_id, "ttl_minutes": 480},
    )
    assert pin_response.status_code == 200
    pin = pin_response.json()["pin"]
    login_response = client.post("/api/elder-login", json={"pin": pin})
    assert login_response.status_code == 200
    return pin, login_response.json()


def test_system_mode_only_enables_demo_controls_on_localhost(local_client):
    local_response = local_client.get("/api/system/mode")
    remote_response = TestClient(app).get("/api/system/mode")

    assert local_response.json()["demo_mode"] is True
    assert remote_response.json()["demo_mode"] is False


def test_pin_is_one_time_and_token_reads_bound_profile(local_client):
    pin, login = issue_and_login(local_client, "W001")

    reused = local_client.post("/api/elder-login", json={"pin": pin})
    profile = local_client.get(
        "/api/elder/profile?elder_id=W001",
        headers={"Authorization": f"Bearer {login['elder_token']}"},
    )

    assert reused.status_code == 401
    assert profile.status_code == 200
    assert profile.json()["elder_id"] == "W001"


def test_greet_uses_body_elder_id(local_client, monkeypatch):
    seen = {}

    class FakeDecision:
        def greet(self):
            return {"message": "ok"}

    def fake_get_decision(elder_id, session_id="default", persona_id=None):
        seen["elder_id"] = elder_id
        return FakeDecision()

    monkeypatch.setattr(main_module, "get_decision", fake_get_decision)
    response = local_client.post(
        "/api/greet",
        json={"elder_id": "C001"},
    )

    assert response.status_code == 200
    assert seen["elder_id"] == "C001"


def test_chat_uses_body_elder_id(local_client, monkeypatch):
    seen = {}

    class FakeDecision:
        def __init__(self):
            self._lock = asyncio.Lock()

        def chat(self, message, speed_emotion):
            return {
                "message": message,
                "emotion": "normal",
                "escalation_level": 2,
            }

    fake_decision = FakeDecision()

    def fake_get_decision(elder_id, session_id="default", persona_id=None):
        seen["elder_id"] = elder_id
        return fake_decision

    monkeypatch.setattr(main_module, "get_decision", fake_get_decision)
    response = local_client.post(
        "/api/chat",
        json={"elder_id": "W001", "message": "hello"},
    )

    assert response.status_code == 200
    assert seen["elder_id"] == "W001"


def test_background_result_is_private_to_elder_id(local_client):
    task_id = main_module._reserve_background_result("W001")

    denied = local_client.get(
        f"/api/elder/chat/background/{task_id}?elder_id=C001",
    )
    allowed = local_client.get(
        f"/api/elder/chat/background/{task_id}?elder_id=W001",
    )

    assert denied.status_code == 404
    assert allowed.status_code == 200


def test_elder_profile_rejects_disallowed_elder_id(local_client, monkeypatch):
    monkeypatch.setattr(main_module, "ALLOWED_ELDER_IDS", ("W001",))
    response = local_client.get("/api/elder/profile?elder_id=L001")

    assert response.status_code == 403


def test_revoke_keeps_simplified_elder_profile_access(local_client):
    issue_and_login(local_client, "L001")
    revoked = local_client.post(
        "/api/admin/elder-session/revoke",
        json={"elder_id": "L001"},
    )
    profile = local_client.get(
        "/api/elder/profile?elder_id=L001",
    )

    assert revoked.status_code == 200
    assert profile.status_code == 200


def test_elder_login_rate_limit(local_client):
    for _ in range(5):
        response = local_client.post(
            "/api/elder-login",
            json={"pin": "999999"},
        )
        assert response.status_code == 401

    blocked = local_client.post("/api/elder-login", json={"pin": "999999"})
    assert blocked.status_code == 429


def test_admin_basic_auth_rate_limit(local_client, monkeypatch):
    monkeypatch.setattr(main_module, "CARE4U_DEMO_MODE", False)
    monkeypatch.setattr(main_module, "ADMIN_PASSWORD", "correct-password")
    monkeypatch.setattr(main_module, "ADMIN_USERS", "")

    for _ in range(5):
        response = local_client.get(
            "/api/admin/me",
            auth=("admin", "wrong-password"),
        )
        assert response.status_code == 401

    blocked = local_client.get(
        "/api/admin/me",
        auth=("admin", "correct-password"),
    )
    assert blocked.status_code == 429
