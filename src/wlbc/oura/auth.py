"""Authentication for the Oura Cloud API.

Oura deprecated personal access tokens in December 2025; OAuth2 authorization
code is the only supported way to obtain a token. Both auth objects below hand
the client the same thing — a bearer token — so the transport does not care
where it came from.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .errors import OuraAuthError

AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"

ALL_SCOPES = (
    "email",
    "personal",
    "daily",
    "heartrate",
    "workout",
    "tag",
    "session",
    "spo2Daily",
)

DEFAULT_TOKEN_PATH = Path.home() / ".config" / "wlbc" / "oura_token.json"

# Refresh this many seconds before actual expiry, so a long request does not
# start with a token that dies mid-flight.
_EXPIRY_MARGIN = 60.0


class StaticTokenAuth:
    """Wraps a bearer token you already hold. Cannot refresh."""

    def __init__(self, access_token: str):
        if not access_token:
            raise OuraAuthError("StaticTokenAuth requires a non-empty access token.")
        self._token = access_token

    def access_token(self) -> str:
        return self._token

    def refresh(self) -> bool:
        """No refresh token available, so a 401 is terminal."""
        return False


@dataclass
class Token:
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None  # Unix epoch seconds
    scope: str = ""

    @classmethod
    def from_response(cls, payload: dict) -> "Token":
        expires_in = payload.get("expires_in")
        return cls(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_at=time.time() + float(expires_in) if expires_in else None,
            scope=payload.get("scope", ""),
        )

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= self.expires_at - _EXPIRY_MARGIN

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scope": self.scope,
        }


class TokenStore:
    """Persists a token as owner-readable-only JSON on disk."""

    def __init__(self, path: Path = DEFAULT_TOKEN_PATH):
        self.path = Path(path)

    def load(self) -> Token | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text())
            return Token(**data)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            raise OuraAuthError(
                f"Stored token at {self.path} is unreadable ({exc}). "
                f"Delete it and run `wlbc-oura login` again."
            ) from exc

    def save(self, token: Token) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Create with 0600 before writing, so the secret is never briefly world-readable.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as fh:
            json.dump(token.to_dict(), fh, indent=2)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class OAuth2Auth:
    """Authorization-code flow with automatic refresh."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str = "http://localhost:8765/callback",
        scopes: tuple[str, ...] = ALL_SCOPES,
        store: TokenStore | None = None,
    ):
        if not client_id or not client_secret:
            raise OuraAuthError(
                "OAuth2 needs a client ID and secret. Register an app at "
                "https://cloud.ouraring.com/oauth/applications and set "
                "OURA_CLIENT_ID / OURA_CLIENT_SECRET."
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.store = store or TokenStore()
        self._token: Token | None = None
        self._lock = threading.Lock()

    # -- token access ----------------------------------------------------

    def access_token(self) -> str:
        with self._lock:
            token = self._token or self.store.load()
            if token is None:
                raise OuraAuthError(
                    "Not logged in. Run `wlbc-oura login` to authorize with Oura."
                )
            if token.is_expired():
                token = self._do_refresh(token)
            self._token = token
            return token.access_token

    def refresh(self) -> bool:
        """Force a refresh after a 401. Returns False if no refresh token exists."""
        with self._lock:
            token = self._token or self.store.load()
            if token is None or not token.refresh_token:
                return False
            self._token = self._do_refresh(token)
            return True

    def _do_refresh(self, token: Token) -> Token:
        if not token.refresh_token:
            raise OuraAuthError(
                "Access token expired and no refresh token is stored. "
                "Run `wlbc-oura login` again."
            )
        payload = self._post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token,
            }
        )
        new_token = Token.from_response(payload)
        # Oura may omit refresh_token on refresh; keep the existing one if so.
        if not new_token.refresh_token:
            new_token.refresh_token = token.refresh_token
        self.store.save(new_token)
        return new_token

    # -- login flow ------------------------------------------------------

    def authorize_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.scopes),
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> Token:
        payload = self._post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
            }
        )
        token = Token.from_response(payload)
        self.store.save(token)
        self._token = token
        return token

    def login(self, open_browser: bool = True, timeout: float = 300.0) -> Token:
        """Run the full browser flow, capturing the callback on localhost."""
        parsed = urlparse(self.redirect_uri)
        if parsed.hostname not in ("localhost", "127.0.0.1"):
            raise OuraAuthError(
                f"login() captures the callback on localhost, but the redirect URI is "
                f"{self.redirect_uri}. Use exchange_code() with the code from your own "
                f"redirect handler instead."
            )

        state = secrets.token_urlsafe(24)
        result: dict[str, str] = {}
        done = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - name fixed by BaseHTTPRequestHandler
                query = parse_qs(urlparse(self.path).query)
                result.update({k: v[0] for k, v in query.items()})
                ok = result.get("state") == state and "code" in result
                body = (
                    b"<h2>Authorized.</h2><p>You can close this tab.</p>"
                    if ok
                    else b"<h2>Authorization failed.</h2><p>Check the terminal.</p>"
                )
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                done.set()

            def log_message(self, *args):  # silence per-request stderr logging
                pass

        server = HTTPServer((parsed.hostname, parsed.port or 80), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = self.authorize_url(state)
            print(f"Opening browser to authorize with Oura:\n  {url}\n")
            if open_browser:
                webbrowser.open(url)
            if not done.wait(timeout):
                raise OuraAuthError(f"Timed out after {timeout:.0f}s waiting for the callback.")
        finally:
            server.shutdown()
            server.server_close()

        if result.get("state") != state:
            raise OuraAuthError("State mismatch on the OAuth callback; aborting.")
        if "code" not in result:
            raise OuraAuthError(
                f"Oura returned no authorization code. "
                f"error={result.get('error')} description={result.get('error_description')}"
            )
        return self.exchange_code(result["code"])

    # -- internals -------------------------------------------------------

    def _post_token(self, data: dict) -> dict:
        data = {**data, "client_id": self.client_id, "client_secret": self.client_secret}
        response = httpx.post(TOKEN_URL, data=data, timeout=30.0)
        if not response.is_success:
            raise OuraAuthError(
                f"Token endpoint returned {response.status_code}: {response.text[:500]}"
            )
        return response.json()


def auth_from_env(store: TokenStore | None = None):
    """Build an auth object from environment variables.

    OURA_ACCESS_TOKEN wins if set; otherwise OAuth2 credentials are used.
    """
    token = os.environ.get("OURA_ACCESS_TOKEN", "").strip()
    if token:
        return StaticTokenAuth(token)

    client_id = os.environ.get("OURA_CLIENT_ID", "").strip()
    client_secret = os.environ.get("OURA_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise OuraAuthError(
            "No credentials found. Set OURA_ACCESS_TOKEN, or set OURA_CLIENT_ID and "
            "OURA_CLIENT_SECRET and run `wlbc-oura login`. Copy .env.example to .env "
            "to get started."
        )
    return OAuth2Auth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=os.environ.get("OURA_REDIRECT_URI", "http://localhost:8765/callback"),
        store=store,
    )
