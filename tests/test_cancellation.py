"""Tests for CancelScope signal and ESC cancellation."""

from __future__ import annotations

import signal
from unittest.mock import patch

from orchid_cli._cancellation import CancelScope


class TestCancelScope:
    def test_default_state(self):
        """CancelScope starts with cancelled=False and watch_esc=False."""
        scope = CancelScope()
        assert scope.cancelled is False
        assert scope.watch_esc is False
        assert scope._fd is None

    def test_enter_restores_handler_on_exit(self):
        """Original SIGINT handler is restored after context exit."""
        original = signal.getsignal(signal.SIGINT)
        with CancelScope():
            pass
        assert signal.getsignal(signal.SIGINT) == original

    def test_sigint_sets_cancelled(self):
        """SIGINT handler sets cancelled to True."""
        scope = CancelScope()
        with scope:
            scope._handler(signal.SIGINT, None)
            assert scope.cancelled is True

    async def test_check_esc_returns_false_when_no_fd(self):
        """check_esc returns False when _fd is None (TTY not set up)."""
        scope = CancelScope()
        result = await scope.check_esc()
        assert result is False

    async def test_check_esc_returns_true_when_already_cancelled(self):
        """check_esc returns True immediately if already cancelled."""
        scope = CancelScope()
        scope.cancelled = True
        result = await scope.check_esc()
        assert result is True

    async def test_check_esc_handles_oserror_gracefully(self):
        """check_esc catches OSError and returns current cancelled state."""
        scope = CancelScope()
        scope._fd = 0
        with patch("select.select", side_effect=OSError("bad fd")):
            result = await scope.check_esc()
            assert result is False
