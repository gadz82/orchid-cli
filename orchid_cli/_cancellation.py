"""Signal-handler and stdin utilities for user-initiated cancellation.

Provides :class:`CancelScope`, a context manager that intercepts
SIGINT (Ctrl+C) and optionally polls stdin for the ESC byte (``\\x1b``).
Both channels converge on a single ``cancelled`` flag so consuming loops
check exactly one condition.
"""

from __future__ import annotations

import select
import signal
import sys
import termios
import tty
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CancelScope:
    """SIGINT + optional ESC-press → ``cancelled`` flag.

    Restores the original SIGINT handler and terminal settings on exit.
    Nested scopes save and restore the outer scope's state correctly.

    When ``watch_esc=True``, stdin is placed in **cbreak mode** (character-
    by-character, no line buffering) for the scope's lifetime.  Call
    :meth:`check_esc` in the consuming loop's main iteration to
    non-blockingly poll for the ESC byte (``\\x1b``).
    """

    cancelled: bool = field(default=False, init=False)
    watch_esc: bool = field(default=False)
    _original_handler: Any = field(default=None, init=False)
    _original_tty: Any = field(default=None, init=False)
    _fd: int | None = field(default=None, init=False)

    def __enter__(self) -> CancelScope:
        self._original_handler = signal.signal(signal.SIGINT, self._handler)
        if self.watch_esc and sys.stdin.isatty():
            self._fd = sys.stdin.fileno()
            self._original_tty = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        return self

    def __exit__(self, *args: Any) -> None:
        signal.signal(signal.SIGINT, self._original_handler)
        if self._original_tty is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._original_tty)

    def _handler(self, sig: int, frame: Any) -> None:
        self.cancelled = True

    async def check_esc(self) -> bool:
        """Non-blocking stdin poll. Sets ``cancelled`` if ESC byte found.

        Returns the current ``cancelled`` value so callers can write::

            if await scope.check_esc():
                break
        """
        if self._fd is None or self.cancelled:
            return self.cancelled
        try:
            readable, _, _ = select.select([sys.stdin], [], [], 0)
            if readable and sys.stdin.read(1) == "\x1b":
                self.cancelled = True
        except (ValueError, TypeError, OSError):
            pass
        return self.cancelled
