"""Shared-server boundaries without cameras, sockets, or real credentials."""

import hashlib
import json
import threading
from types import SimpleNamespace

import anyio
import pytest
from chessbot import team_access
from chessbot.team_access import COOKIE_NAME, attach_team_access, load_access_file
from fastapi import FastAPI
from fastapi.testclient import TestClient

TOKENS = {"reader": "test-reader-credential", "alpha": "test-alpha-credential", "beta": "test-beta-credential"}
ORIGIN = "http://127.0.0.1:8011"


def bearer(identifier):
    return {"Authorization": f"Bearer {TOKENS[identifier]}"}


@pytest.fixture
def access_file(tmp_path):
    document = {"version": 1, "clients": [
        {"id": identifier, "name": identifier.title(), "role": "viewer" if identifier == "reader" else "operator",
         "token_sha256": hashlib.sha256(token.encode()).hexdigest(), "revoked": False}
        for identifier, token in TOKENS.items()
    ]}
    path = tmp_path / "access.json"
    path.write_text(json.dumps(document))
    return path


@pytest.fixture
def clock(monkeypatch):
    value = SimpleNamespace(now=1000.0, epoch=1_800_000_000.0)
    # Replace only this module's clock; the test client's event loop keeps its
    # actual monotonic clock and timeout behavior.
    monkeypatch.setattr(team_access, "time", SimpleNamespace(
        monotonic=lambda: value.now, time=lambda: value.epoch + value.now))
    return value


def make_app(path, origin=ORIGIN):
    app = FastAPI()
    app.state.cell = SimpleNamespace(status="ready", mutations=0)

    @app.get("/")
    async def shell():
        return {"shell": True}

    @app.get("/web-assets/app.js")
    async def script():
        return {"script": True}

    @app.get("/api/health")
    async def health():
        return {"ok": True, "private_device_info": "must-not-be-public"}

    @app.get("/api/state")
    async def state():
        return {"state": "private"}

    @app.get("/assets/so101/model.stl")
    async def model():
        return {"model": "private"}

    @app.post("/api/ik")
    async def ik():
        return {"reachable": False}

    @app.post("/api/reset")
    async def reset():
        app.state.cell.mutations += 1
        return {"ok": True}

    attach_team_access(app, path, origin)
    return app


@pytest.fixture
def client(access_file):
    with TestClient(make_app(access_file), base_url=ORIGIN) as result:
        yield result


def test_public_shell_and_minimal_health_but_private_api_and_robot_assets(client):
    assert client.get("/").status_code == 200
    assert client.get("/web-assets/app.js").status_code == 200
    assert client.get("/api/health").json() == {"ok": True, "team_access": True}
    for path in ["/api/state", "/api/auth/me", "/api/control", "/assets/so101/model.stl"]:
        result = client.get(path)
        assert result.status_code == 401
        assert result.headers["www-authenticate"] == "Bearer"
        assert "no-store" in result.headers["cache-control"]
    assert client.get("/api/state", headers=bearer("reader")).status_code == 200
    assert client.get("/assets/so101/model.stl", headers=bearer("reader")).status_code == 200


def test_viewer_may_read_and_solve_ik_but_cannot_control_or_mutate(client):
    identity = client.get("/api/auth/me", headers=bearer("reader")).json()
    assert identity == {"id": "reader", "name": "Reader", "role": "viewer", "authentication": "bearer"}
    assert client.post("/api/ik", headers=bearer("reader")).status_code == 200
    assert client.post("/api/reset", headers=bearer("reader")).status_code == 403
    assert client.post("/api/control/acquire", headers=bearer("reader"), json={}).status_code == 403
    assert client.app.state.cell.mutations == 0


def test_browser_cookie_csrf_logout_and_bearer_origin_rules(client):
    assert client.post("/api/auth/login", json={"token": TOKENS["reader"]}).status_code == 403
    assert client.post("/api/auth/login", headers={"Origin": "https://wrong.example"},
                       json={"token": TOKENS["reader"]}).status_code == 403
    response = client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={"token": TOKENS["reader"]})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Secure" not in cookie
    assert TOKENS["reader"] not in cookie
    session = client.cookies.get(COOKIE_NAME)
    assert client.get("/api/auth/me").json()["authentication"] == "session"
    assert client.post("/api/ik").status_code == 403
    assert client.post("/api/ik", headers={"Origin": ORIGIN}).status_code == 200
    assert client.post("/api/ik", headers={"Origin": "http://127.0.0.1:8012"}).status_code == 403
    assert client.get("/api/state", headers={**bearer("reader"), "Origin": "https://wrong.example"}).status_code == 403
    assert client.post("/api/auth/logout", headers={"Origin": ORIGIN}).status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Cookie": f"{COOKIE_NAME}={session}"}).status_code == 401
    assert client.post("/api/ik", headers=bearer("reader")).status_code == 200


def test_https_session_is_secure_and_unconfigured_origin_is_bearer_only(access_file):
    with TestClient(make_app(access_file, "https://robot.example"), base_url="https://robot.example") as client:
        response = client.post("/api/auth/login", headers={"Origin": "https://robot.example"},
                               json={"token": TOKENS["alpha"]})
        assert response.status_code == 200
        assert "Secure" in response.headers["set-cookie"]
        assert client.get("/api/auth/me").json()["id"] == "alpha"
    with pytest.raises(ValueError, match="HTTPS"):
        make_app(access_file, "http://remote.example")
    with TestClient(make_app(access_file, None)) as client:
        assert client.get("/api/state", headers=bearer("reader")).status_code == 200
        assert client.post("/api/auth/login", json={"token": TOKENS["reader"]}).status_code == 403


def test_credentials_in_urls_are_rejected_and_bad_bearer_never_falls_back_to_cookie(client):
    assert client.get("/api/state", params={"token": TOKENS["reader"]}).status_code == 400
    client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={"token": TOKENS["reader"]})
    assert client.get("/api/state", headers={"Authorization": "Bearer incorrect"}).status_code == 401
    assert client.get("/api/state", headers={"Authorization": "Basic abc"}).status_code == 401


def test_revocation_and_rotation_reload_for_bearer_and_existing_sessions(client, access_file):
    client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={"token": TOKENS["reader"]})
    document = json.loads(access_file.read_text())
    document["clients"][0]["revoked"] = True
    access_file.write_text(json.dumps(document))
    assert client.get("/api/state", headers=bearer("reader")).status_code == 401
    assert client.get("/api/state").status_code == 401
    document["clients"][0]["revoked"] = False
    access_file.write_text(json.dumps(document))
    client.post("/api/auth/login", headers={"Origin": ORIGIN}, json={"token": TOKENS["reader"]})
    document["clients"][0]["token_sha256"] = hashlib.sha256(b"rotated-test-token").hexdigest()
    access_file.write_text(json.dumps(document))
    assert client.get("/api/state").status_code == 401
    assert client.get("/api/state", headers=bearer("reader")).status_code == 401


def test_invalid_missing_and_ambiguous_access_files_fail_closed(client, access_file):
    original = access_file.read_text()
    access_file.write_text("invalid json")
    assert client.get("/api/state", headers=bearer("alpha")).status_code == 503
    assert client.post("/api/reset", headers=bearer("alpha")).status_code == 503
    document = json.loads(original)
    document["clients"].append(document["clients"][0])
    access_file.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="missing or invalid"):
        load_access_file(access_file)
    assert client.get("/api/state", headers=bearer("alpha")).status_code == 503
    access_file.unlink()
    assert client.get("/api/state", headers=bearer("alpha")).status_code == 503
    assert client.get("/").status_code == 200


def test_two_operators_exclusive_lease_renewal_and_monotonic_expiry(client, clock):
    assert client.post("/api/reset", headers=bearer("alpha")).status_code == 409
    first = client.post("/api/control/acquire", headers=bearer("alpha"), json={"ttl_seconds": 30})
    assert first.status_code == 200
    assert first.json()["owner"] == {"id": "alpha", "name": "Alpha"}
    assert first.json()["held_by_you"]
    assert client.get("/api/control", headers=bearer("beta")).json()["held_by_you"] is False
    assert client.post("/api/control/acquire", headers=bearer("beta"), json={}).status_code == 409
    assert client.post("/api/reset", headers=bearer("beta")).status_code == 409
    assert client.post("/api/reset", headers=bearer("alpha")).status_code == 200
    clock.epoch += 100000  # Wall-clock adjustment must not expire a lease.
    assert client.get("/api/control", headers=bearer("alpha")).json()["active"]
    clock.now += 20
    assert client.post("/api/control/renew", headers=bearer("alpha"), json={"ttl_seconds": 60}).status_code == 200
    clock.now += 59
    assert client.get("/api/control", headers=bearer("alpha")).json()["active"]
    clock.now += 2
    assert client.get("/api/control", headers=bearer("alpha")).json()["owner"] is None
    assert client.post("/api/control/acquire", headers=bearer("beta"), json={}).status_code == 200
    assert client.post("/api/reset", headers=bearer("alpha")).status_code == 409
    assert client.app.state.cell.mutations == 1


@pytest.mark.parametrize("status", ["planning", "moving", "capturing"])
def test_busy_cell_keeps_owner_after_expiry_and_refuses_release_or_transfer(client, clock, status):
    client.post("/api/control/acquire", headers=bearer("alpha"), json={"ttl_seconds": 30})
    client.app.state.cell.status = status
    assert client.post("/api/control/release", headers=bearer("alpha"), json={}).status_code == 409
    clock.now += 31
    control = client.get("/api/control", headers=bearer("beta")).json()
    assert control["owner"]["id"] == "alpha" and not control["active"] and control["busy"]
    assert client.post("/api/control/acquire", headers=bearer("beta"), json={}).status_code == 409
    assert client.post("/api/control/renew", headers=bearer("alpha"), json={}).status_code == 200
    client.app.state.cell.status = "ready"
    assert client.post("/api/control/release", headers=bearer("alpha"), json={}).status_code == 200
    assert client.post("/api/control/acquire", headers=bearer("beta"), json={}).status_code == 200


def test_invalid_ttl_and_unowned_renewal_are_rejected(client):
    for value in [29, 901, 30.5, True]:
        assert client.post("/api/control/acquire", headers=bearer("alpha"),
                           json={"ttl_seconds": value}).status_code == 422
    assert client.post("/api/control/renew", headers=bearer("alpha"), json={}).status_code == 409
    client.app.state.cell.status = "moving"
    assert client.post("/api/control/acquire", headers=bearer("alpha"), json={}).status_code == 409


def test_inflight_mutation_reserves_control_before_cell_status_changes(access_file, clock):
    app = make_app(access_file)
    entered, finish = threading.Event(), threading.Event()

    @app.post("/api/slow")
    async def slow():
        entered.set()
        await anyio.to_thread.run_sync(finish.wait)
        return {"ok": True}

    with TestClient(app, base_url=ORIGIN) as client:
        client.post("/api/control/acquire", headers=bearer("alpha"), json={"ttl_seconds": 30})
        responses = []
        worker = threading.Thread(target=lambda: responses.append(client.post("/api/slow", headers=bearer("alpha"))))
        worker.start()
        try:
            assert entered.wait(timeout=3)
            assert app.state.cell.status == "ready"
            clock.now += 31
            assert client.post("/api/control/acquire", headers=bearer("beta"), json={}).status_code == 409
            assert client.post("/api/control/release", headers=bearer("alpha"), json={}).status_code == 409
        finally:
            finish.set()
            worker.join(timeout=3)
        assert not worker.is_alive()
        assert responses[0].status_code == 200
        assert client.post("/api/control/acquire", headers=bearer("beta"), json={}).status_code == 200
