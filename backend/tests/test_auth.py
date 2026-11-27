"""Signing in (core/auth.py, api/routers/auth.py)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ecosim.core import auth

ADMIN_PW = "0123456789ab"
TESTER_PW = "tester-pass-42"


@pytest.fixture
def client():
    from ecosim.api.app import create_app

    with TestClient(create_app()) as c:
        yield c
    auth.clear_failures("testclient")


def _login(client, user, pw):
    return client.post("/auth/login", json={"username": user, "password": pw})


def test_password_hash_round_trip():
    h = auth.hash_password("correct horse battery")
    assert h.startswith("scrypt$") and "correct" not in h
    assert auth.verify_password("correct horse battery", h)
    assert not auth.verify_password("wrong password!", h)
    assert not auth.verify_password("x", "garbage")


def test_accounts_need_an_admin_first():
    with pytest.raises(ValueError, match="administrator first"):
        auth.set_user("t", TESTER_PW, "tester")
    with pytest.raises(ValueError, match="at least 10"):
        auth.set_user("admin", "short", "admin")
    auth.set_user("admin", ADMIN_PW, "admin")
    auth.set_user("t", TESTER_PW, "tester")
    with pytest.raises(ValueError, match="last administrator"):
        auth.remove_user("admin")
    assert auth.remove_user("t") and not auth.remove_user("t")


def test_session_token_signed_expiring_and_tied_to_password():
    auth.set_user("admin", ADMIN_PW, "admin")
    cfg = auth.load_config()
    token = auth.make_session(cfg, cfg.account("admin"), now=1000)
    assert auth.session_account(token, cfg, now=1001).username == "admin"
    assert auth.session_account(token, cfg, now=1000 + auth.SESSION_SECONDS + 1) is None  # expired
    payload, sig = token.rsplit(".", 1)
    assert auth.session_account(payload + "." + "0" * len(sig), cfg, now=1001) is None  # forged
    auth.set_user("admin", "another-password", "admin")  # a new password ends that account's sessions
    assert auth.session_account(token, auth.load_config(), now=1001) is None


def test_open_without_setup(client):
    assert client.get("/auth/status").json() == {"enabled": False, "user": None, "role": None}
    assert client.get("/areas").status_code == 200


def test_required_but_not_set_up_locks_everything(client, monkeypatch):
    monkeypatch.setenv("ECOSIM_REQUIRE_AUTH", "1")
    assert client.get("/areas").status_code == 401
    assert _login(client, "a", "b").status_code == 503


def test_login_flow(client):
    auth.set_user("admin", ADMIN_PW, "admin")
    assert client.get("/areas").status_code == 401
    assert client.get("/openapi.json").status_code == 401
    assert client.get("/health").status_code == 200
    assert _login(client, "admin", "nope-nope-nope").status_code == 401
    assert _login(client, "nobody", ADMIN_PW).status_code == 401
    r = _login(client, "admin", ADMIN_PW)
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert "samesite=strict" in r.headers["set-cookie"].lower()
    assert client.get("/auth/status").json() == {"enabled": True, "user": "admin", "role": "admin"}
    assert client.get("/areas").status_code == 200
    client.post("/auth/logout")
    assert client.get("/areas").status_code == 401


def test_tester_can_look_but_not_change_the_setup(client):
    auth.set_user("admin", ADMIN_PW, "admin")
    auth.set_user("sweden", TESTER_PW, "tester")
    assert _login(client, "sweden", TESTER_PW).json()["role"] == "tester"
    assert client.get("/areas").status_code == 200
    assert client.put("/areas", json={"areas": [], "selected": []}).status_code == 200  # saving areas is fine
    assert client.get("/admin/sources").status_code == 200  # the start page lists them
    assert client.get("/admin/browse").status_code == 403  # the server's disk
    assert client.post("/admin/sources", json={}).status_code == 403
    assert client.post("/admin/sources/x/activate").status_code == 403
    assert client.delete("/regions/packs/x").status_code == 403
    assert client.post("/regions/packs", json={"path": "/"}).status_code == 403


def test_failed_attempts_are_limited(client):
    auth.set_user("admin", ADMIN_PW, "admin")
    for _ in range(5):
        assert _login(client, "admin", "bad-password").status_code == 401
    assert _login(client, "admin", ADMIN_PW).status_code == 429  # even the right password, for now


def test_r_can_be_turned_off(client, monkeypatch):
    monkeypatch.setenv("ECOSIM_DISABLE_R", "1")
    assert client.get("/analyses").json() == []
    assert client.post("/analyses/anything/run", json={}).status_code == 403
