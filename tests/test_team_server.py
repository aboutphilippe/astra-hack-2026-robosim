"""Exercise the shared runtime's static shell and authenticated live cell together."""
import hashlib
import json

import pytest
from chessbot.team_server import create_team_app
from fastapi.testclient import TestClient


@pytest.fixture
def shared_app(tmp_path):
    access = tmp_path / "access.json"
    access.write_text(json.dumps({"version": 1, "clients": [{"id": "alice", "name": "Alice", "role": "operator",
             "revoked": False, "token_sha256": hashlib.sha256(b"a" * 48).hexdigest()}]}))
    dist = tmp_path / "dist"
    (dist / "web-assets").mkdir(parents=True)
    (dist / "index.html").write_text('<script src="/web-assets/app.js"></script>')
    (dist / "web-assets" / "app.js").write_text("//compiled console")
    return create_team_app(access_file=access, web_dir=dist, public_origin="http://127.0.0.1:8011")


def test_public_shell_and_authenticated_authoritative_cell(shared_app):
    with TestClient(shared_app, base_url="http://127.0.0.1:8011") as client:
        assert client.get("/").status_code == 200
        assert client.get("/web-assets/app.js").text == "//compiled console"
        assert client.get("/api/state").status_code == 401
        assert client.get("/api/server-info").status_code == 401
        assert client.get("/assets/so101/so101.xml").status_code == 401
        client.headers["Authorization"] = "Bearer " + "a" * 48
        info = client.get("/api/server-info").json()
        assert info["access"] == "team"
        assert info["capabilities"]["exclusive_control"]
        assert not info["capabilities"]["hardware_execution"]
        assert client.post("/api/move", json={"uci": "e2e4"}).status_code == 409
        assert client.post("/api/control/acquire", json={"ttl_seconds": 60}).status_code == 200
        response = client.post("/api/move", json={"uci": "e2e4"})
        assert response.status_code == 200
        assert response.json()["turn"] == "black"
        assert client.get("/assets/so101/so101.xml").status_code == 200


def test_missing_access_file_rejects_startup(tmp_path):
    (tmp_path / "index.html").write_text("console")
    with pytest.raises(ValueError, match="access file"):
        create_team_app(access_file=tmp_path / "missing.json", web_dir=tmp_path)


def test_plaintext_remote_origin_rejected(tmp_path):
    with pytest.raises(ValueError, match="HTTPS"):
        create_team_app(public_origin="http://10.0.0.2:8011", web_dir=tmp_path)
