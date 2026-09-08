"""Authentication and exclusive control for the optional shared Mac server.

Only credential hashes are persisted. Browser sessions and the operator lease
live in this process: run one server worker for one authoritative robot cell.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import posixpath
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

COOKIE_NAME = "nono_team_session"
SESSION_SECONDS = 12 * 60 * 60
BUSY_STATUSES = frozenset({"planning", "moving", "capturing"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class Client:
    id: str
    name: str
    role: str
    token_sha256: str
    revoked: bool = False

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "role": self.role}


def load_access_file(path: Path) -> dict[str, Client]:
    """Reload and validate all entries; any malformed entry fails the file closed.

    Server startup can call this function too. No exception includes token
    hashes, file contents, or other credentials.
    """
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError
        document = json.loads(raw)
        if not isinstance(document, dict) or type(document.get("version")) is not int or document["version"] != 1:
            raise ValueError
        if not isinstance(document.get("clients"), list):
            raise TypeError
        clients, hashes = {}, set()
        for entry in document["clients"]:
            if not isinstance(entry, dict):
                raise TypeError
            identifier, name, role = entry.get("id"), entry.get("name"), entry.get("role")
            digest, revoked = entry.get("token_sha256"), entry.get("revoked", False)
            if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", identifier):
                raise ValueError
            if not isinstance(name, str) or not name.strip() or len(name) > 128:
                raise ValueError
            if role not in ("viewer", "operator") or type(revoked) is not bool:
                raise ValueError
            if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
                raise ValueError
            digest = digest.lower()
            if identifier in clients or digest in hashes:
                raise ValueError
            clients[identifier] = Client(identifier, name, role, digest, revoked)
            hashes.add(digest)
        return clients
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Team access file is missing or invalid") from exc


def _origin(value: str) -> str:
    """Canonicalize one exact origin, including its non-default port."""
    try:
        if not isinstance(value, str) or any(ord(char) <= 32 for char in value):
            raise ValueError
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError
        if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        if ":" in host:
            host = f"[{host}]"
        suffix = f":{port}" if port and port != (443 if parsed.scheme == "https" else 80) else ""
        return f"{parsed.scheme}://{host}{suffix}"
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Expected an exact HTTP(S) origin without a path") from exc


class LeaseRequest(BaseModel):
    ttl_seconds: int = Field(default=300, ge=30, le=900, strict=True)


class TeamAccess:
    def __init__(self, app: FastAPI, access_file: Path, public_origin: str | None):
        self.app, self.access_file = app, Path(access_file)
        self.public_origin = _origin(public_origin) if public_origin else None
        if self.public_origin:
            parsed = urlsplit(self.public_origin)
            if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("Browser sessions require HTTPS, except for an exact loopback origin")
        self.secure_cookie = bool(self.public_origin and self.public_origin.startswith("https://"))
        self._lock = threading.RLock()
        self._sessions: dict[str, dict] = {}
        self._owner: Client | None = None
        self._expires = 0.0
        self._active_mutations = 0

    def _clients(self) -> dict[str, Client]:
        try:
            return load_access_file(self.access_file)
        except ValueError as exc:
            raise HTTPException(503, "Team access configuration unavailable") from exc

    def _token_client(self, token: str, clients: dict[str, Client]) -> Client:
        if not isinstance(token, str) or not 1 <= len(token) <= 512:
            raise HTTPException(401, "Authentication required or credential invalid")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        match = None
        for client in clients.values():
            if hmac.compare_digest(digest, client.token_sha256) and not client.revoked:
                match = client
        if match is None:
            raise HTTPException(401, "Authentication required or credential invalid")
        return match

    def authenticate(self, request: Request, clients: dict[str, Client]) -> tuple[Client, str]:
        authorization = request.headers.getlist("authorization")
        if authorization:
            parts = authorization[0].split()
            if len(authorization) != 1 or len(parts) != 2 or parts[0].lower() != "bearer":
                raise HTTPException(401, "Authentication required or credential invalid")
            return self._token_client(parts[1], clients), "bearer"
        session_id = request.cookies.get(COOKIE_NAME, "")
        if not session_id or len(session_id) > 512:
            raise HTTPException(401, "Authentication required or credential invalid")
        digest = hashlib.sha256(session_id.encode()).hexdigest()
        with self._lock:
            session = self._sessions.get(digest)
            client = clients.get(session["client_id"]) if session else None
            if (not session or session["expires"] <= time.monotonic() or not client or client.revoked
                    or not hmac.compare_digest(session["credential_hash"], client.token_sha256)):
                self._sessions.pop(digest, None)
                raise HTTPException(401, "Authentication required or credential invalid")
        return client, "session"

    def check_origin(self, request: Request, *, required: bool = False):
        supplied = request.headers.getlist("origin")
        if not supplied:
            if required:
                raise HTTPException(403, "Browser requests require the configured Origin")
            return
        try:
            valid = len(supplied) == 1 and self.public_origin is not None and _origin(supplied[0]) == self.public_origin
        except ValueError:
            valid = False
        if not valid:
            raise HTTPException(403, "Origin is not allowed")

    def _busy(self) -> tuple[bool, str]:
        cell = getattr(self.app.state, "cell", None)
        status = getattr(cell, "status", "ready")
        return status in BUSY_STATUSES or self._active_mutations > 0, status

    def _refresh_lease(self, clients: dict[str, Client]):
        if self._owner is None:
            return
        current = clients.get(self._owner.id)
        available = current is not None and not current.revoked and current.role == "operator"
        if available:
            self._owner = current
        if (not available or self._expires <= time.monotonic()) and not self._busy()[0]:
            self._owner, self._expires = None, 0.0

    def control(self, client: Client, clients: dict[str, Client] | None = None) -> dict:
        with self._lock:
            self._refresh_lease(clients if clients is not None else self._clients())
            remaining = max(0.0, self._expires - time.monotonic()) if self._owner else 0.0
            active = self._owner is not None and remaining > 0
            busy, status = self._busy()
            return {"owner": {"id": self._owner.id, "name": self._owner.name} if self._owner else None,
                    "held_by_you": bool(active and self._owner.id == client.id),
                    "active": active, "expires_at": time.time() + remaining if self._owner else None,
                    "expires_in_seconds": remaining, "busy": busy, "cell_status": status}

    @staticmethod
    def require_operator(client: Client):
        if client.role != "operator":
            raise HTTPException(403, "An operator account is required")

    def acquire(self, client: Client, ttl: int, *, renew: bool = False) -> dict:
        self.require_operator(client)
        with self._lock:
            self._refresh_lease(self._clients())
            same_owner = self._owner is not None and self._owner.id == client.id
            if renew and not same_owner:
                raise HTTPException(409, "Only the current lease holder can renew control")
            if self._owner is not None and not same_owner:
                raise HTTPException(409, "Another operator holds control")
            if self._busy()[0] and not same_owner:
                raise HTTPException(409, "Control cannot transfer while the cell is busy")
            self._owner, self._expires = client, time.monotonic() + ttl
            return self.control(client)

    def release(self, client: Client) -> dict:
        self.require_operator(client)
        with self._lock:
            self._refresh_lease(self._clients())
            if self._owner is not None and self._owner.id != client.id:
                raise HTTPException(409, "Only the current lease holder can release control")
            if self._busy()[0]:
                raise HTTPException(409, "Control cannot release while the cell is busy")
            self._owner, self._expires = None, 0.0
            return self.control(client)

    def begin_mutation(self, client: Client, clients: dict[str, Client]):
        self.require_operator(client)
        with self._lock:
            self._refresh_lease(clients)
            if self._owner is None or self._owner.id != client.id or self._expires <= time.monotonic():
                raise HTTPException(409, "Acquire an active operator lease before changing the shared cell")
            # Reserve ownership until the request finishes, even before the
            # underlying route has changed cell.status to planning/capturing.
            self._active_mutations += 1

    async def login(self, request: Request):
        self.check_origin(request, required=True)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 4096:
                raise HTTPException(413, "Login request is too large")
        try:
            document = json.loads(body)
            token = document.get("token") if isinstance(document, dict) else None
            if not isinstance(token, str) or not 1 <= len(token) <= 512:
                raise ValueError
        except (ValueError, UnicodeError) as exc:
            # Do not echo the submitted token in a validation response.
            raise HTTPException(422, "Provide a token string in the login request") from exc
        client = self._token_client(token, self._clients())
        session_id = secrets.token_urlsafe(32)
        with self._lock:
            now = time.monotonic()
            self._sessions = {key: val for key, val in self._sessions.items() if val["expires"] > now}
            if len(self._sessions) >= 8192:
                self._sessions.pop(next(iter(self._sessions)))
            self._sessions[hashlib.sha256(session_id.encode()).hexdigest()] = {
                "client_id": client.id, "credential_hash": client.token_sha256, "expires": now + SESSION_SECONDS}
        response = JSONResponse({**client.public(), "authentication": "session"})
        response.set_cookie(COOKIE_NAME, session_id, max_age=SESSION_SECONDS, httponly=True,
                            secure=self.secure_cookie, samesite="strict", path="/")
        return response

    async def logout(self, request: Request):
        session_id = request.cookies.get(COOKIE_NAME, "")
        if session_id:
            with self._lock:
                self._sessions.pop(hashlib.sha256(session_id.encode()).hexdigest(), None)
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE_NAME, httponly=True, secure=self.secure_cookie, samesite="strict", path="/")
        return response


class _TeamMiddleware:
    def __init__(self, app, access: TeamAccess):
        self.app, self.access = app, access

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        path = posixpath.normpath("/" + scope.get("path", "/").lstrip("/"))
        protected = path in ("/api", "/assets/so101") or path.startswith(("/api/", "/assets/so101/"))
        if scope["type"] == "websocket":
            if protected:
                return await send({"type": "websocket.close", "code": 1008})
            return await self.app(scope, receive, send)
        request = Request(scope)
        reserved = False

        async def private_send(message):
            if message["type"] == "http.response.start":
                headers = [(name, value) for name, value in message.get("headers", []) if name.lower() != b"cache-control"]
                message = {**message, "headers": headers + [(b"cache-control", b"private, no-store")]}
            await send(message)

        try:
            if protected or request.headers.get("authorization") or request.cookies.get(COOKIE_NAME) or request.method not in SAFE_METHODS:
                self.access.check_origin(request)
            if not protected:
                return await self.app(scope, receive, send)
            if any(key.lower() in {"token", "access_token", "api_key", "authorization"} for key in request.query_params):
                raise HTTPException(400, "Credentials must not be supplied in URLs")
            if path == "/api/health" and request.method in {"GET", "HEAD"}:
                self.access._clients()
                return await JSONResponse({"ok": True, "team_access": True})(scope, receive, private_send)
            if request.method == "OPTIONS":
                self.access.check_origin(request, required=True)
                return await JSONResponse({}, status_code=200, headers={
                    "Access-Control-Allow-Origin": self.access.public_origin,
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Methods": "GET, HEAD, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type",
                    "Vary": "Origin",
                })(scope, receive, private_send)
            clients = self.access._clients()
            if path == "/api/auth/login" and request.method == "POST":
                self.access.check_origin(request, required=True)
                return await self.app(scope, receive, private_send)
            client, method = self.access.authenticate(request, clients)
            if method == "session" and request.method not in SAFE_METHODS:
                self.access.check_origin(request, required=True)
            scope.setdefault("state", {}).update({"team_client": client, "team_authentication": method})
            exempt = {"/api/ik", "/api/auth/logout", "/api/control/acquire", "/api/control/renew", "/api/control/release"}
            if request.method not in SAFE_METHODS and path not in exempt:
                self.access.begin_mutation(client, clients)
                reserved = True
            return await self.app(scope, receive, private_send)
        except HTTPException as exc:
            headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else {}
            return await JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)(scope, receive, private_send)
        finally:
            if reserved:
                with self.access._lock:
                    self.access._active_mutations -= 1


def attach_team_access(app: FastAPI, access_file: Path, public_origin: str | None = None) -> TeamAccess:
    """Attach before starting the app, and before mounting a catch-all SPA.

    The exact public origin enables browser login; None supports bearer-only
    clients. Existing local create_app() calls remain unchanged unless this
    function is explicitly called by the shared-server entry point.
    """
    if getattr(app.state, "team_access", None) is not None:
        raise ValueError("Team access is already attached")
    access = TeamAccess(app, access_file, public_origin)
    app.state.team_access = access

    @app.get("/api/auth/me")
    async def me(request: Request):
        return {**request.state.team_client.public(), "authentication": request.state.team_authentication}

    app.add_api_route("/api/auth/login", access.login, methods=["POST"])
    app.add_api_route("/api/auth/logout", access.logout, methods=["POST"])

    @app.get("/api/control")
    async def control(request: Request):
        return access.control(request.state.team_client)

    @app.post("/api/control/acquire")
    async def acquire(request: Request, body: LeaseRequest | None = None):
        return access.acquire(request.state.team_client, (body or LeaseRequest()).ttl_seconds)

    @app.post("/api/control/renew")
    async def renew(request: Request, body: LeaseRequest | None = None):
        return access.acquire(request.state.team_client, (body or LeaseRequest()).ttl_seconds, renew=True)

    @app.post("/api/control/release")
    async def release(request: Request):
        return access.release(request.state.team_client)

    app.add_middleware(_TeamMiddleware, access=access)
    return access
