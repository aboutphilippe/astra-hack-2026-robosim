"""Local team credential administration; raw tokens go only to private files."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .config import ROOT


def _path(value: str | Path) -> Path:
    return Path(value).expanduser().absolute()


def _mkdir_private(path: Path) -> None:
    """Protect newly created directories without changing existing repo folders."""
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"Expected a directory: {path}")
        return
    _mkdir_private(path.parent)
    path.mkdir(mode=0o700, exist_ok=True)


def _atomic_bytes(path: Path, content: bytes, *, replace: bool) -> None:
    _mkdir_private(path.parent)
    if path.is_symlink():
        raise ValueError(f"Refusing a symbolic-link output: {path}")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            # Same-filesystem link is atomic and fails if the target exists.
            os.link(temporary, path)
        parent_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _write_access(path: Path, data: dict, *, replace: bool = True) -> None:
    _atomic_bytes(path, (json.dumps(data, indent=2) + "\n").encode(), replace=replace)


@contextmanager
def _locked(path: Path):
    _mkdir_private(path.parent)
    descriptor = os.open(path.with_name(f".{path.name}.lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def load_access(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError("The access file must not be a symbolic link")
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ValueError("Access file does not exist; run nono-team init first") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Access file is not valid JSON") from exc
    if (not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1
            or not isinstance(data.get("clients"), list)):
        raise ValueError("Expected access schema version 1 with a clients list")
    ids, names, hashes = set(), set(), set()
    for client in data["clients"]:
        if not isinstance(client, dict):
            raise TypeError("Each access client must be an object")
        name, identifier = client.get("name"), client.get("id")
        if (not isinstance(name, str) or not name.strip() or len(name) > 128
                or not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", identifier)):
            raise ValueError("Every access client requires a name and id")
        if identifier in ids or name.casefold() in names:
            raise ValueError("Access file contains duplicate client names or ids")
        if client.get("role") not in ("viewer", "operator") or not isinstance(client.get("revoked"), bool):
            raise ValueError("Every client requires a valid role and revoked boolean")
        if not isinstance(client.get("token_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", client["token_sha256"]):
            raise ValueError("Every client requires a SHA-256 token digest")
        if client["token_sha256"] in hashes:
            raise ValueError("Access file contains duplicate token credentials")
        ids.add(identifier)
        names.add(name.casefold())
        hashes.add(client["token_sha256"])
    return data


def initialize(path: Path) -> dict:
    with _locked(path):
        _write_access(path, {"version": 1, "clients": []}, replace=False)
    return {"access_file": str(path), "initialized": True}


def add_client(path: Path, name: str, role: str, token_output: Path) -> dict:
    name = name.strip()
    if not 1 <= len(name) <= 80 or any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ValueError("Client name must contain 1–80 printable characters")
    if role not in ("viewer", "operator"):
        raise ValueError("Role must be viewer or operator")
    if path == token_output:
        raise ValueError("Token output must be separate from the access file")
    with _locked(path):
        data = load_access(path)
        if any(client["name"].casefold() == name.casefold() for client in data["clients"]):
            raise ValueError("That client name already exists; use a new name for replacement credentials")
        token = "nono_" + secrets.token_urlsafe(32)
        client = {"id": uuid4().hex, "name": name, "role": role,
                  "token_sha256": hashlib.sha256(token.encode()).hexdigest(), "revoked": False}
        _atomic_bytes(token_output, (token + "\n").encode(), replace=False)
        try:
            data["clients"].append(client)
            _write_access(path, data)
        except Exception:
            token_output.unlink(missing_ok=True)
            raise
    return {"id": client["id"], "name": name, "role": role, "token_file": str(token_output)}


def revoke_client(path: Path, selector: str) -> dict:
    with _locked(path):
        data = load_access(path)
        matched = [client for client in data["clients"]
                   if client["id"] == selector or client["name"].casefold() == selector.casefold()]
        if len(matched) != 1:
            raise ValueError("Identify exactly one existing client by id or name")
        client = matched[0]
        client["revoked"] = True
        _write_access(path, data)
    return {"id": client["id"], "name": client["name"], "role": client["role"], "revoked": True}


def list_clients(path: Path) -> list[dict]:
    return [{key: client[key] for key in ("id", "name", "role", "revoked")}
            for client in load_access(path)["clients"]]


def _probe(command: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def doctor(path: Path, port: int = 8011) -> dict:
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    report = {"access_file": str(path), "platform": sys.platform, "loopback_port": port}
    try:
        clients = list_clients(path)
        report["access"] = {"valid": True, "active_clients": sum(not client["revoked"] for client in clients)}
    except (OSError, TypeError, ValueError) as exc:
        report["access"] = {"valid": False, "error": str(exc)}
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            report["local_server_listening"] = True
    except OSError:
        report["local_server_listening"] = False
    launchctl = shutil.which("launchctl")
    report["launchd"] = {"available": bool(launchctl), "loaded": False}
    if launchctl and sys.platform == "darwin":
        result = _probe([launchctl, "print", f"gui/{os.getuid()}/com.nono.chess-server"])
        report["launchd"]["loaded"] = bool(result and result.returncode == 0)
        report["launchd"]["running"] = bool(result and re.search(r"state\s*=\s*running", result.stdout))
    tailscale = shutil.which("tailscale")
    app_cli = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
    if not tailscale and app_cli.is_file():
        tailscale = str(app_cli)
    report["tailscale"] = {"cli": tailscale, "available": bool(tailscale)}
    if tailscale:
        result = _probe([tailscale, "ip", "-4"])
        report["tailscale"]["local_ipv4"] = result.stdout.strip()[:100] if result and result.returncode == 0 else None
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--access-file", default=os.environ.get("NONO_ACCESS_FILE", str(ROOT / "config" / "team-access.json")))
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "add", "revoke", "list", "doctor"):
        child = commands.add_parser(command)
        child.add_argument("--access-file", default=argparse.SUPPRESS)
        if command == "add":
            child.add_argument("--name", required=True)
            child.add_argument("--role", choices=("viewer", "operator"), default="viewer")
            child.add_argument("--token-output", "--output", required=True, dest="token_output")
        elif command == "revoke":
            child.add_argument("client", help="Client id or name")
        elif command == "doctor":
            child.add_argument("--port", type=int, default=8011)
    args = parser.parse_args(argv)
    path = _path(args.access_file)
    try:
        if args.command == "init":
            result = initialize(path)
        elif args.command == "add":
            result = add_client(path, args.name, args.role, _path(args.token_output))
        elif args.command == "revoke":
            result = revoke_client(path, args.client)
        elif args.command == "list":
            result = list_clients(path)
        else:
            result = doctor(path, args.port)
    except (OSError, TypeError, ValueError) as exc:
        # Errors never include raw token material or access-file contents.
        print(f"nono-team: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
