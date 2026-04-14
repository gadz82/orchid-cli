"""
OAuth 2.0 Authorization Code + PKCE flow for CLI applications.

Opens the user's browser for login, receives the callback on a
temporary localhost HTTP server, and exchanges the authorization code
for tokens.

This implements the standard flow used by ``gh auth login``,
``gcloud auth login``, ``az login``, etc.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import logging
import secrets
import socket
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .config import OAuthProviderConfig
from .token_store import StoredToken

logger = logging.getLogger(__name__)

# ── PKCE helpers ──────────────────────────────────────────────


def _generate_code_verifier(length: int = 64) -> str:
    """Generate a cryptographically random PKCE code verifier (43-128 chars, RFC 7636)."""
    return secrets.token_urlsafe(length)[:128]


def _generate_code_challenge(verifier: str) -> str:
    """Derive S256 code challenge from verifier (RFC 7636 Section 4.2)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ── Localhost callback server ─────────────────────────────────


def _find_free_port(start: int = 9876, attempts: int = 20) -> int:
    """Find an available TCP port, trying a range starting from ``start``."""
    for offset in range(attempts):
        port = start + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    # Fallback: let the OS assign a port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler that captures the OAuth callback query parameters."""

    # Set by the server before starting.
    result: dict | None = None
    expected_state: str = ""

    def do_GET(self) -> None:  # noqa: N802  (required by BaseHTTPRequestHandler)
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        error = params.get("error", [None])[0]

        if error:
            self.result = {"error": error, "error_description": params.get("error_description", [""])[0]}
            self._respond(400, "Authentication failed", f"Error: {html.escape(error)}")
            return

        if not code:
            self._respond(400, "Missing code", "No authorization code received.")
            return

        if state != self.expected_state:
            self._respond(400, "State mismatch", "Invalid state parameter — possible CSRF attack.")
            return

        self.result = {"code": code}
        self._respond(
            200,
            "Authentication successful",
            "You can close this browser tab and return to the terminal.",
        )

    def _respond(self, status: int, title: str, body: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        page = (
            f"<!DOCTYPE html><html><head><title>{html.escape(title)}</title>"
            "<style>body{font-family:system-ui,sans-serif;display:flex;"
            "justify-content:center;align-items:center;height:100vh;margin:0;"
            "background:#f8f9fa}div{text-align:center;padding:2rem}"
            "h1{color:#333}p{color:#666}</style></head>"
            f"<body><div><h1>{html.escape(title)}</h1>"
            f"<p>{html.escape(body)}</p></div></body></html>"
        )
        self.wfile.write(page.encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        """Suppress default stderr logging."""


def _wait_for_callback(port: int, state: str, timeout: float = 120) -> dict:
    """Start a temporary HTTP server and wait for the OAuth callback.

    Returns a dict with either ``{"code": "..."}`` or ``{"error": "..."}``.
    Blocks until the callback arrives or ``timeout`` seconds elapse.
    """
    _CallbackHandler.result = None
    _CallbackHandler.expected_state = state

    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = timeout

    thread = Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    server.server_close()

    if _CallbackHandler.result is None:
        return {"error": "timeout", "error_description": "No callback received within timeout."}
    return _CallbackHandler.result


# ── Token exchange ────────────────────────────────────────────


async def _exchange_code(
    config: OAuthProviderConfig,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> StoredToken:
    """Exchange an authorization code for access + refresh tokens."""
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": config.client_id,
        "code_verifier": code_verifier,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            config.token_endpoint,
            data=payload,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

    import time

    expires_in = data.get("expires_in", 0)
    expires_at = (time.time() + expires_in) if expires_in else 0.0

    return StoredToken(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", ""),
        expires_at=expires_at,
        scopes=data.get("scope", config.scopes),
    )


# ── Public API ────────────────────────────────────────────────


async def run_login_flow(config: OAuthProviderConfig, *, timeout: float = 120) -> StoredToken:
    """Execute the full Authorization Code + PKCE flow.

    1. Generate PKCE verifier/challenge
    2. Open the browser to the authorization URL
    3. Wait for the callback on a localhost port
    4. Exchange the code for tokens

    Raises ``RuntimeError`` on failure (timeout, error response, etc.).
    """
    port = _find_free_port()
    redirect_uri = f"http://localhost:{port}/callback"
    state = secrets.token_urlsafe(32)
    code_verifier = _generate_code_verifier()
    code_challenge = _generate_code_challenge(code_verifier)

    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": redirect_uri,
        "scope": config.scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    auth_url = f"{config.authorization_endpoint}?{urlencode(params)}"
    logger.info("[CLI Auth] Opening browser for login: %s", auth_url)

    webbrowser.open(auth_url)

    # Wait for the callback in a thread (blocking stdlib HTTPServer).
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _wait_for_callback, port, state, timeout)

    if "error" in result:
        error_desc = result.get("error_description", result["error"])
        raise RuntimeError(f"OAuth login failed: {error_desc}")

    code = result["code"]
    logger.info("[CLI Auth] Authorization code received, exchanging for tokens")

    token = await _exchange_code(config, code, code_verifier, redirect_uri)
    return token
