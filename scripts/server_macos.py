"""Generate a reviewable macOS LaunchAgent and wrapper; never install or load it."""

from __future__ import annotations

import argparse
import os
import plistlib
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

LABEL = "com.nono.chess-server"


def _mkdir_private(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"Output parent must be a directory: {path}")
        return
    _mkdir_private(path.parent)
    path.mkdir(mode=0o700, exist_ok=True)


def _create(path: Path, content: bytes, mode: int) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _server_ref(checkout: Path) -> str:
    result = subprocess.run(["git", "-C", str(checkout), "rev-parse", "--verify", "HEAD"],
                            capture_output=True, text=True, check=False, timeout=5)
    revision = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        raise ValueError("Checkout must have a committed Git revision")
    dirty = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, check=False, timeout=5)
    return revision + ("-dirty" if dirty.stdout.strip() else "")


def generate(checkout: Path, output: Path, access_file: Path, config: Path,
             public_origin: str, port: int = 8011, server_ref: str | None = None) -> dict:
    checkout, output, access_file, config = [path.expanduser().absolute() for path in (checkout, output, access_file, config)]
    if any(ord(character) <= 32 for character in public_origin):
        raise ValueError("Public origin must not contain whitespace or control characters")
    parsed = urlsplit(public_origin)
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Public origin port must be between 1 and 65535")
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Public origin must be an HTTP(S) origin without credentials")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Public origin must contain only scheme, hostname, and optional port")
    if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Remote access requires HTTPS; HTTP is supported only for a local SSH tunnel")
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    executable = checkout / ".venv" / "bin" / "nono-server"
    if not executable.is_file():
        raise ValueError(f"Server entry point is missing; run uv sync in the stable checkout: {executable}")
    if not config.is_file() or not access_file.is_file():
        raise ValueError("Config and initialized team access files must exist before generating the service")
    revision = server_ref or _server_ref(checkout)
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,128}", revision):
        raise ValueError("Server revision must be a short Git revision label")
    _mkdir_private(output)
    wrapper = output / "run-nono-server.sh"
    plist_path = output / f"{LABEL}.plist"
    if wrapper.exists() or wrapper.is_symlink() or plist_path.exists() or plist_path.is_symlink():
        raise ValueError("Generated service files already exist; choose a fresh --output directory for review")
    shell = f"#!/bin/sh\nset -eu\numask 077\ncd {shlex.quote(str(checkout))}\nexec {shlex.quote(str(executable))}\n"
    payload = {"Label": LABEL, "ProgramArguments": [str(wrapper)], "WorkingDirectory": str(checkout),
               "EnvironmentVariables": {"NONO_ACCESS_FILE": str(access_file), "NONO_CONFIG": str(config),
                                        "NONO_PUBLIC_ORIGIN": public_origin.rstrip("/"), "NONO_PORT": str(port),
                                        "NONO_SERVER_REF": revision},
               "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10, "ProcessType": "Background",
               "Umask": 0o077, "StandardOutPath": str(output / "server.stdout.log"),
               "StandardErrorPath": str(output / "server.stderr.log")}
    _create(wrapper, shell.encode(), 0o700)
    try:
        _create(plist_path, plistlib.dumps(payload, sort_keys=False), 0o600)
    except Exception:
        wrapper.unlink(missing_ok=True)
        raise
    return {"plist": str(plist_path), "wrapper": str(wrapper), "server_ref": revision,
            "installed": False, "public_origin": public_origin.rstrip("/")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, help="Artifact directory; generating does not install the service")
    parser.add_argument("--access-file", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--server-ref")
    args = parser.parse_args(argv)
    checkout = args.checkout.expanduser().absolute()
    try:
        result = generate(checkout, args.output or checkout / "artifacts" / "server",
                          args.access_file or checkout / "config" / "team-access.json",
                          args.config or checkout / "config" / "nono.json", args.public_origin,
                          args.port, args.server_ref)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"server_macos: {exc}\n")
    import json
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
