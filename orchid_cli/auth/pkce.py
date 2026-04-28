"""
Shared OAuth 2.0 Authorization Code + PKCE primitives for the CLI.

Consolidates the handful of low-level building blocks that both
:mod:`orchid_cli.auth.flow` (user login) and
:mod:`orchid_cli.commands.mcp` (per-server MCP authorization) need:

  * :func:`generate_code_verifier` / :func:`generate_code_challenge` —
    RFC 7636 PKCE derivations.
  * :func:`find_free_port` — pick a localhost port for the redirect URI.
  * :func:`wait_for_callback` — spin up a one-shot HTTP server and
    return the decoded OAuth query parameters.
  * :func:`exchange_code_for_tokens` — POST to the token endpoint.
  * :func:`run_pkce_flow` — the whole dance: build URL, open browser,
    wait for callback, exchange code.  Used by MCP; the higher-level
    :mod:`flow` module layers extra policy on top (timeout handling,
    state verification errors, ``StoredToken`` assembly).

The module is deliberately stdlib-only plus ``httpx`` — no Typer, no
Rich, no CLI coupling — so it can be unit-tested without a console and
reused from non-CLI contexts if ever needed.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import logging
import os
import secrets
import shlex
import socket
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

logger = logging.getLogger(__name__)

# Matches :func:`webbrowser.open` — injectable so tests / headless CI
# can redirect or suppress the browser launch.
BrowserOpener = Callable[[str], bool]


# ── PKCE derivations (RFC 7636) ───────────────────────────────


def generate_code_verifier(length: int = 64) -> str:
    """Generate a cryptographically random PKCE code verifier.

    RFC 7636 §4.1 requires 43-128 characters of the unreserved URL
    alphabet.  ``secrets.token_urlsafe`` gives us the right alphabet;
    we truncate to 128 to stay within spec.
    """
    return secrets.token_urlsafe(length)[:128]


def generate_code_challenge(verifier: str) -> str:
    """Derive the S256 code challenge from the verifier (RFC 7636 §4.2)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ── Localhost callback server ─────────────────────────────────


def find_free_port(start: int = 9876, attempts: int = 20) -> int:
    """Find an available TCP port, trying a range starting from *start*.

    Falls back to an OS-assigned port if every candidate in the range
    is taken.  There's a theoretical TOCTOU race between the bind-check
    here and the actual listener creation downstream; acceptable for the
    CLI's one-shot redirect listener.
    """
    for offset in range(attempts):
        port = start + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class CallbackResult:
    """What a successful OAuth redirect returns us."""

    code: str = ""
    state: str = ""
    error: str = ""
    error_description: str = ""


def _build_callback_handler(
    *,
    result: CallbackResult,
    success_title: str,
    success_body: str,
) -> type[BaseHTTPRequestHandler]:
    """Factory — returns a handler class that writes into *result*.

    The class is built per-call so each flow gets its own *result*
    reference and success message (user login vs MCP per-server).
    """

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — required by BaseHTTPRequestHandler
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)

            result.error = params.get("error", [""])[0]
            result.error_description = params.get("error_description", [""])[0]
            result.code = params.get("code", [""])[0]
            result.state = params.get("state", [""])[0]

            status = 400 if result.error or not result.code else 200
            title = f"Error: {result.error}" if result.error else success_title
            body = result.error_description or success_body

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

    return _Handler


def wait_for_callback(
    port: int,
    *,
    timeout: float = 120.0,
    success_title: str = "Authorization complete",
    success_body: str = "You can close this window and return to the terminal.",
) -> CallbackResult:
    """Start a temporary HTTP server and block until an OAuth redirect arrives.

    Returns a :class:`CallbackResult`.  When the timeout elapses the
    result's ``code`` stays empty and ``error`` is ``"timeout"``.
    """
    result = CallbackResult()
    handler = _build_callback_handler(
        result=result,
        success_title=success_title,
        success_body=success_body,
    )

    server = HTTPServer(("127.0.0.1", port), handler)
    server.timeout = timeout

    thread = Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    server.server_close()

    if not result.code and not result.error:
        result.error = "timeout"
        result.error_description = "No callback received within timeout."
    return result


# ── Token exchange ────────────────────────────────────────────


async def exchange_code_for_tokens(
    *,
    token_endpoint: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str = "",
    timeout: float = 30.0,
) -> dict:
    """POST the authorization code to the token endpoint; return the JSON body.

    ``client_secret`` is optional — populate it when the OAuth server
    treats the CLI as a CONFIDENTIAL client (PKCE alone isn't enough
    — the token endpoint demands the secret as well).  Sent as
    ``client_secret_post`` (form-body field) per RFC 6749 §2.3.1
    because that's what every OAuth server we've seen accepts and it
    doesn't require pre-flight knowledge of which auth method the
    server supports.

    Raises ``httpx.HTTPStatusError`` on non-2xx responses so callers can
    distinguish transport errors from OAuth errors.

    Note: the equivalent ``curl`` invocation is rendered by
    :func:`run_pkce_flow` (pre-flight when ``ORCHID_AUTH_DEBUG_CURL``
    is set, post-mortem on failure regardless).  Putting the diagnostic
    one level up keeps this primitive HTTP-only.
    """
    payload: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            token_endpoint,
            data=payload,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


def _build_curl(url: str, body: dict[str, str]) -> str:
    """Render the equivalent ``curl`` command for a form-encoded POST.

    Each field uses ``--data-urlencode`` so ``=`` / ``&`` / spaces
    inside values can't break the line.  Output is single-line and
    backslash-continued so it pastes cleanly into a terminal.
    """
    lines = [
        f"curl -i -X POST {shlex.quote(url)} \\",
        "  -H 'Accept: application/json' \\",
        "  -H 'Content-Type: application/x-www-form-urlencoded' \\",
    ]
    items = list(body.items())
    for i, (k, v) in enumerate(items):
        sep = " \\" if i < len(items) - 1 else ""
        lines.append(f"  --data-urlencode {shlex.quote(f'{k}={v}')}{sep}")
    return "\n".join(
        [
            "",
            "── orchid-cli token-exchange curl ─────────────",
            *lines,
            "───────────────────────────────────────────────",
            "",
        ]
    )


# ── High-level orchestration ──────────────────────────────────


@dataclass
class PKCEFlowResult:
    """Result of :func:`run_pkce_flow`.

    ``success`` is the only guaranteed field; when ``False``, ``error``
    describes what went wrong (timeout, state mismatch, HTTP error).
    """

    success: bool
    access_token: str = ""
    refresh_token: str = ""
    expires_in: int = 3600
    scopes: str = ""
    error: str = ""


async def run_pkce_flow(
    *,
    auth_endpoint: str,
    token_endpoint: str,
    client_id: str,
    scopes: str,
    client_secret: str = "",
    timeout: float = 120.0,
    browser_opener: BrowserOpener = webbrowser.open,
    success_title: str = "Authorization complete",
    success_body: str = "You can close this window.",
) -> PKCEFlowResult:
    """Run the full Authorization Code + PKCE flow.

    1. Generate PKCE verifier/challenge + CSRF state.
    2. Start a localhost HTTP server and open the browser.
    3. Wait for the redirect callback.
    4. Exchange the authorization code for tokens.

    Returns a :class:`PKCEFlowResult` — never raises.
    """
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    state = secrets.token_urlsafe(32)

    port = find_free_port()
    redirect_uri = f"http://localhost:{port}/callback"

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{auth_endpoint}?{urlencode(params)}"

    # Start the server *before* opening the browser so the redirect
    # never arrives at a port with no listener.  We still rely on the
    # single-shot ``handle_request`` to return immediately.
    loop = asyncio.get_event_loop()
    browser_opener(authorize_url)
    callback = await loop.run_in_executor(
        None,
        lambda: wait_for_callback(
            port,
            timeout=timeout,
            success_title=success_title,
            success_body=success_body,
        ),
    )

    if callback.error:
        return PKCEFlowResult(
            success=False,
            error=callback.error_description or callback.error,
        )
    if callback.state != state:
        return PKCEFlowResult(success=False, error="State mismatch — possible CSRF")

    # Build the exact request payload up-front so we can render the
    # equivalent curl on failure (or when the debug env var is set).
    exchange_payload: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": callback.code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    if client_secret:
        exchange_payload["client_secret"] = client_secret

    debug_curl = os.environ.get("ORCHID_AUTH_DEBUG_CURL", "").strip().lower() not in ("", "0", "false", "no")
    if debug_curl:
        # Pre-flight dump — visible BEFORE the request goes out so the
        # operator can copy it into another terminal and replay there.
        print(_build_curl(token_endpoint, exchange_payload), flush=True)

    try:
        data = await exchange_code_for_tokens(
            token_endpoint=token_endpoint,
            code=callback.code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            client_id=client_id,
            client_secret=client_secret,
        )
    except httpx.HTTPStatusError as exc:
        # Surface the upstream OAuth error verbatim — without it, every
        # 400 looks the same and there's no way to tell ``invalid_grant``
        # apart from ``invalid_client`` apart from ``redirect_uri``
        # mismatch.  RFC 6749 §5.2 mandates the body be JSON with
        # ``error`` + ``error_description`` fields, but some servers
        # return text/html — try JSON first, fall back to raw text.
        try:
            body = exc.response.json()
            detail = f"{body.get('error', '?')}: {body.get('error_description', body)}"
        except Exception:
            detail = (exc.response.text or "<empty body>")[:300]
        return PKCEFlowResult(
            success=False,
            error=f"Token exchange failed (HTTP {exc.response.status_code}): {detail}",
        )
    except Exception as exc:  # pragma: no cover — defensive
        return PKCEFlowResult(success=False, error=f"Token exchange failed: {exc}")

    return PKCEFlowResult(
        success=True,
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", ""),
        expires_in=data.get("expires_in", 3600),
        scopes=data.get("scope", scopes),
    )
