"""Teammate credentials protect both tool requests and camera image downloads."""
import httpx
import pytest
from chessbot import mcp_server


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.delenv("NONO_API_TOKEN", raising=False)
    monkeypatch.delenv("NONO_API_TOKEN_FILE", raising=False)
    monkeypatch.setattr(mcp_server, "BASE_URL", "http://127.0.0.1:8011")


def test_remote_plain_http_rejected_before_sending_credentials(monkeypatch):
    monkeypatch.setenv("NONO_API_TOKEN", "a" * 48)
    monkeypatch.setattr(mcp_server, "BASE_URL", "http://192.168.1.42:8011")
    with pytest.raises(ValueError, match="HTTPS"):
        mcp_server.client_headers()


@pytest.mark.parametrize("url", ["https://token@host.example", "https://host.example?token=abc",
                                  "file:///tmp/socket", "https://host.example#secret"])
def test_credentials_cannot_be_embedded_in_server_url(monkeypatch, url):
    monkeypatch.setattr(mcp_server, "BASE_URL", url)
    with pytest.raises(ValueError):
        mcp_server.client_headers()


def test_token_file_rotates_for_json_and_images(monkeypatch, tmp_path):
    token_file = tmp_path / "operator.token"
    token_file.write_text("a" * 48 + "\n")
    monkeypatch.setenv("NONO_API_TOKEN_FILE", str(token_file))
    monkeypatch.setattr(mcp_server, "BASE_URL", "https://nono.example.ts.net")
    requests = []
    original_client = httpx.Client

    def handle(request):
        requests.append(request)
        if request.url.path.endswith(".jpg"):
            return httpx.Response(200, content=b"image bytes", headers={"content-type": "image/jpeg"})
        return httpx.Response(200, json={"mode": "simulation"})

    def client(*args, **kwargs):
        return original_client(*args, **kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(mcp_server.httpx, "Client", client)
    assert mcp_server.request("GET", "/api/state")["mode"] == "simulation"
    token_file.write_text("b" * 48)
    mcp_server.camera_image("/api/camera/top.jpg")
    assert requests[0].headers["authorization"] == "Bearer " + "a" * 48
    assert requests[1].headers["authorization"] == "Bearer " + "b" * 48


def test_local_development_does_not_require_a_credential():
    assert mcp_server.client_headers() == {}
