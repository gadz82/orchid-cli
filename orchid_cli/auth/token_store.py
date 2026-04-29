"""
Secure local token persistence — ``~/.orchid/tokens.json``.

Stores access and refresh tokens per provider (keyed by ``client_id``).
File permissions are set to ``0o600`` (owner-only read/write) to prevent
other users from reading credentials.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import stat
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_ORCHID_DIR = Path.home() / ".orchid"
_TOKEN_FILE = _ORCHID_DIR / "tokens.json"
# Filename of the sentinel used to serialise the read-modify-write
# sequence in ``save_token`` / ``delete_token``. The full path is
# built inside ``_exclusive_lock()`` from the current ``_ORCHID_DIR``
# so tests that monkeypatch ``_ORCHID_DIR`` don't leak writes to the
# real home directory.
_LOCK_FILENAME = ".tokens.lock"


@dataclass
class StoredToken:
    """Token data persisted to disk."""

    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0
    scopes: str = ""
    # Identity fields (populated after OrchidIdentityResolver or userinfo call).
    tenant_key: str = ""
    user_id: str = ""
    extra: dict[str, str] = field(default_factory=dict)
    # ── Cached identity-resolver result ─────────────────────
    # When ``auth_class`` is set, ``auth_state`` is a JSON-serialisable
    # dict produced by ``OrchidAuthContext.to_storage_dict()`` and
    # consumed by ``<auth_class>.from_storage_dict()``.  This lets the
    # CLI rebuild the resolver's typed subclass (with all its
    # platform-specific typed attributes — e.g. a ``.domain`` or a
    # ``.tenant_uuid`` exposed alongside the base contract) on every
    # command without re-calling the upstream resolver.  When unset
    # (legacy tokens or pure-public deployments without a resolver),
    # the middleware falls back to its old "build a bare
    # ``OrchidAuthContext``" path.
    auth_class: str = ""
    auth_state: dict[str, object] = field(default_factory=dict)  # type: ignore[type-arg]

    @property
    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() >= self.expires_at

    @property
    def is_refresh_available(self) -> bool:
        return bool(self.refresh_token)


def save_token(client_id: str, token: StoredToken) -> None:
    """Persist a token for the given client_id."""
    _ORCHID_DIR.mkdir(parents=True, exist_ok=True)

    with _exclusive_lock():
        all_tokens = _read_all()
        all_tokens[client_id] = asdict(token)
        _write_all(all_tokens)
    logger.debug("[CLI Auth] Token saved for client_id=%s", client_id)


def load_token(client_id: str) -> StoredToken | None:
    """Load a previously stored token, or None if absent.

    Unknown fields present in the on-disk JSON are ignored but logged at
    DEBUG — useful to detect schema drift (e.g. a newer CLI wrote a
    field this version doesn't know about yet).
    """
    all_tokens = _read_all()
    data = all_tokens.get(client_id)
    if not data:
        return None
    known_fields = StoredToken.__dataclass_fields__.keys()
    extras = set(data.keys()) - set(known_fields)
    if extras:
        logger.debug("[CLI Auth] Ignoring unknown token fields for %s: %s", client_id, sorted(extras))
    return StoredToken(**{k: v for k, v in data.items() if k in known_fields})


def delete_token(client_id: str) -> bool:
    """Delete the token for a client_id. Returns True if something was deleted."""
    with _exclusive_lock():
        all_tokens = _read_all()
        if client_id not in all_tokens:
            return False
        del all_tokens[client_id]
        _write_all(all_tokens)
    logger.debug("[CLI Auth] Token deleted for client_id=%s", client_id)
    return True


def delete_all_tokens() -> None:
    """Remove all stored tokens."""
    if _TOKEN_FILE.exists():
        _TOKEN_FILE.unlink()
        logger.debug("[CLI Auth] All tokens deleted")


# ── Internal helpers ──────────────────────────────────────────
#
# Token I/O has three operational requirements that the naive
# ``Path.read_text`` / ``Path.write_text`` pattern does not meet:
#
#   1. **No plaintext window before chmod.**  Writing through
#      ``mkstemp(...)`` lets us call ``fchmod(0o600)`` on the FD
#      *before* the bytes hit disk, so a snooping process can't read
#      the file between ``write_text`` and ``os.chmod``.
#   2. **Atomic publication.**  ``os.replace(tmp, dst)`` is atomic on
#      POSIX — concurrent readers see either the old file or the new
#      one, never a half-written one.
#   3. **No torn reads.**  ``fcntl.flock(LOCK_SH)`` blocks readers
#      while a writer holds an exclusive lock; combined with
#      ``os.replace`` this means concurrent ``orchid auth login`` and
#      ``orchid chat`` invocations never trip on partial JSON.
#
# Windows lacks ``fcntl``; the helpers fall back to lock-free I/O on
# that platform — acceptable because Windows is a development target
# only and concurrent CLI invocations are rare.


try:
    import fcntl as _fcntl  # POSIX-only

    _HAS_FCNTL = True
except ImportError:  # pragma: no cover — Windows
    _HAS_FCNTL = False


@contextlib.contextmanager
def _exclusive_lock() -> Iterator[None]:
    """Serialise the read-modify-write sequence used by save/delete.

    Two concurrent CLI invocations (different processes) both opening
    the sentinel and calling ``flock(LOCK_EX)`` queue behind each
    other. Without this, an interleaving like::

        P1: read → mutate
                             P2: read → mutate → write
        P1: write       (clobbers P2's mutation)

    can silently lose a token write. Falls back to a no-op on Windows
    where ``fcntl`` is unavailable; concurrent CLI invocations there
    accept a small risk of last-writer-wins.
    """
    _ORCHID_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = _ORCHID_DIR / _LOCK_FILENAME
    fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if _HAS_FCNTL:
            _fcntl.flock(fd, _fcntl.LOCK_EX)
        yield
    finally:
        if _HAS_FCNTL:
            _fcntl.flock(fd, _fcntl.LOCK_UN)
        os.close(fd)


def _read_all() -> dict:
    if not _TOKEN_FILE.exists():
        return {}
    try:
        with open(_TOKEN_FILE, encoding="utf-8") as fh:
            if _HAS_FCNTL:
                _fcntl.flock(fh.fileno(), _fcntl.LOCK_SH)
                try:
                    return json.loads(fh.read())
                finally:
                    _fcntl.flock(fh.fileno(), _fcntl.LOCK_UN)
            return json.loads(fh.read())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[CLI Auth] Could not read token file: %s", exc)
        return {}


def _write_all(data: dict) -> None:
    """Write the token map atomically with owner-only permissions.

    The on-disk byte sequence is never visible at >0o600 perms because
    ``mkstemp`` creates the temp file with mode 0o600 by default and
    ``os.replace`` is atomic on POSIX.
    """
    import tempfile

    _ORCHID_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(_ORCHID_DIR),
        prefix=".tokens_",
        suffix=".tmp",
    )
    try:
        # ``mkstemp`` already creates 0o600 on POSIX; this is a
        # belt-and-braces line that surfaces a bug if a future
        # change relaxes the default.
        try:
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        except (OSError, AttributeError):  # pragma: no cover — Windows
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            if _HAS_FCNTL:
                _fcntl.flock(fh.fileno(), _fcntl.LOCK_EX)
                try:
                    fh.write(json.dumps(data, indent=2))
                    fh.flush()
                    os.fsync(fh.fileno())
                finally:
                    _fcntl.flock(fh.fileno(), _fcntl.LOCK_UN)
            else:
                fh.write(json.dumps(data, indent=2))
        os.replace(tmp_path, str(_TOKEN_FILE))
    except Exception:
        # Clean up the temp file if the rename never happened — a
        # half-written ``.tokens_*.tmp`` would otherwise pile up.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
