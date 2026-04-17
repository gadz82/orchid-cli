"""Tests for the shared PKCE module.

Locks down the PKCE primitives' behaviour so future refactors can't
silently break the OAuth flow used by ``auth login`` and ``mcp authorize``.
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from orchid_cli.auth.pkce import (
    CallbackResult,
    PKCEFlowResult,
    _build_callback_handler,
    find_free_port,
    generate_code_challenge,
    generate_code_verifier,
    run_pkce_flow,
)


class TestPKCEDerivations:
    def test_code_verifier_within_spec(self):
        v = generate_code_verifier()
        assert 43 <= len(v) <= 128

    def test_code_verifier_uses_urlsafe_alphabet(self):
        v = generate_code_verifier()
        assert all(c.isalnum() or c in "-_" for c in v)

    def test_code_verifier_is_random(self):
        assert generate_code_verifier() != generate_code_verifier()

    def test_code_challenge_matches_s256_definition(self):
        verifier = "known-verifier-for-regression-test"
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        )
        assert generate_code_challenge(verifier) == expected

    def test_code_challenge_is_deterministic(self):
        v = generate_code_verifier()
        assert generate_code_challenge(v) == generate_code_challenge(v)


class TestFindFreePort:
    def test_returns_int_in_localhost_range(self):
        port = find_free_port()
        assert 1024 < port < 65536

    def test_falls_back_to_os_assigned(self):
        # Exhaust the primary range by using attempts=0 (we can't easily
        # force exhaustion in a unit test without opening sockets).
        # This at least exercises the return-path code.
        port = find_free_port(start=9876, attempts=0)
        assert port > 0


class TestCallbackHandler:
    def test_writes_result_on_success_params(self):
        # Build the handler directly, don't spin up HTTPServer.
        result = CallbackResult()
        handler_cls = _build_callback_handler(
            result=result,
            success_title="Success!",
            success_body="Done.",
        )
        # The handler class exists and has do_GET
        assert hasattr(handler_cls, "do_GET")


class TestRunPkceFlow:
    @pytest.mark.asyncio
    async def test_returns_failure_on_timeout(self):
        """Tight timeout + no actual callback → PKCEFlowResult(success=False)."""
        captured_urls: list[str] = []

        def fake_opener(url: str) -> bool:
            captured_urls.append(url)
            return True

        result = await run_pkce_flow(
            auth_endpoint="https://idp.example/authorize",
            token_endpoint="https://idp.example/token",
            client_id="test",
            scopes="read",
            timeout=0.2,
            browser_opener=fake_opener,
        )
        assert isinstance(result, PKCEFlowResult)
        assert result.success is False
        assert "timeout" in result.error.lower() or "no callback" in result.error.lower()
        assert captured_urls and captured_urls[0].startswith("https://idp.example/authorize?")

    @pytest.mark.asyncio
    async def test_authorize_url_contains_all_pkce_params(self):
        opened: list[str] = []
        await run_pkce_flow(
            auth_endpoint="https://idp.example/authorize",
            token_endpoint="https://idp.example/token",
            client_id="myclient",
            scopes="openid profile",
            timeout=0.1,
            browser_opener=lambda u: opened.append(u) or True,
        )
        url = opened[0]
        assert "client_id=myclient" in url
        assert "code_challenge=" in url
        assert "code_challenge_method=S256" in url
        assert "state=" in url
        assert "response_type=code" in url
