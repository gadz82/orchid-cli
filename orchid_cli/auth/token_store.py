"""
Secure local token persistence — ``~/.orchid/tokens.json``.

Stores access and refresh tokens per provider (keyed by ``client_id``).
File permissions are set to ``0o600`` (owner-only read/write) to prevent
other users from reading credentials.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_ORCHID_DIR = Path.home() / ".orchid"
_TOKEN_FILE = _ORCHID_DIR / "tokens.json"


@dataclass
class StoredToken:
    """Token data persisted to disk."""

    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0
    scopes: str = ""
    # Identity fields (populated after IdentityResolver or userinfo call).
    tenant_key: str = ""
    user_id: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() >= self.expires_at

    @property
    def is_refresh_available(self) -> bool:
        return bool(self.refresh_token)


def save_token(client_id: str, token: StoredToken) -> None:
    """Persist a token for the given client_id."""
    _ORCHID_DIR.mkdir(parents=True, exist_ok=True)

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


def _read_all() -> dict:
    if not _TOKEN_FILE.exists():
        return {}
    try:
        return json.loads(_TOKEN_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[CLI Auth] Could not read token file: %s", exc)
        return {}


def _write_all(data: dict) -> None:
    _TOKEN_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # Restrict to owner-only (best-effort on Windows).
    try:
        os.chmod(_TOKEN_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
