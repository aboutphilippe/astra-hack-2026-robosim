"""Dedicated shared runtime: authenticated API, one cell, and the compiled console.

Bind to loopback and publish privately through Tailscale Serve or an SSH tunnel.
The development Vite server and arbitrary branch commands are never exposed.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.staticfiles import StaticFiles

from .api import create_app
from .config import ROOT
from .team_access import attach_team_access, load_access_file


def revision_info() -> dict:
    def git(*args):
        try:
            return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True,
                                           stderr=subprocess.DEVNULL, timeout=3).strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    revision = git("rev-parse", "--short=12", "HEAD")
    return {"revision": revision or "unknown", "branch": git("branch", "--show-current") or "detached",
            "dirty": bool(git("status", "--porcelain")), "deployment_ref": os.environ.get("NONO_SERVER_REF")}


def create_team_app(*, config: dict | None = None, access_file: Path | None = None,
                    public_origin: str | None = None, web_dir: Path | None = None):
    access_path = access_file or Path(os.environ.get("NONO_ACCESS_FILE", ROOT / "config" / "team-access.json"))
    port = int(os.environ.get("NONO_PORT", "8011"))
    origin = public_origin or os.environ.get("NONO_PUBLIC_ORIGIN", f"http://127.0.0.1:{port}")
    parsed = urlsplit(origin)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("NONO_PUBLIC_ORIGIN must be an HTTP(S) origin without credentials.")
    if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("NONO_PUBLIC_ORIGIN must contain only scheme, hostname and optional port.")
    if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Remote shared access requires HTTPS. Use Tailscale Serve or a localhost SSH tunnel.")
    dist = web_dir or ROOT / "web" / "dist"
    if not (dist / "index.html").is_file():
        raise ValueError("Build the shared console first: npm --prefix web run build")
    load_access_file(access_path)
    app = create_app(config)
    attach_team_access(app, access_path.resolve(), origin.rstrip("/"))
    server_info = {"name": "nono-shared", "access": "team", "api_version": 1,
                   "started_at": time.time(), "mode": "simulation", **revision_info(),
                   "capabilities": {"hardware_execution": False, "exclusive_control": True}}

    @app.get("/api/server-info")
    async def info():
        return server_info

    app.mount("/", StaticFiles(directory=dist, html=True), name="console")
    return app


def main():
    import uvicorn
    # Exactly one process must own cameras, game state and operator leases.
    uvicorn.run(create_team_app(), host="127.0.0.1", port=int(os.environ.get("NONO_PORT", "8011")),
                workers=1, proxy_headers=False)
