"""Security regressions for ``orchid_cli.auth.token_store``.

These tests pin down two properties the hardening pass added:

  1. The on-disk token file is never world-readable, even between the
     write call and the chmod call (``mkstemp`` + ``fchmod`` close the
     window).
  2. Concurrent readers and writers don't see torn JSON — file locks
     serialise readers behind any in-flight writer.
"""

from __future__ import annotations

import json
import stat
import threading

import pytest

from orchid_cli.auth import token_store
from orchid_cli.auth.token_store import StoredToken, load_token, save_token


@pytest.fixture
def isolated_orchid_dir(tmp_path, monkeypatch):
    """Redirect ``~/.orchid/tokens.json`` to a per-test temp dir."""
    fake_home = tmp_path / "home"
    fake_orchid = fake_home / ".orchid"
    monkeypatch.setattr(token_store, "_ORCHID_DIR", fake_orchid)
    monkeypatch.setattr(token_store, "_TOKEN_FILE", fake_orchid / "tokens.json")
    return fake_orchid


def test_save_creates_file_with_owner_only_perms(isolated_orchid_dir):
    """The persisted file must end up at ``0o600`` regardless of the
    process's ``umask``."""
    save_token("client-a", StoredToken(access_token="t1"))

    file_path = isolated_orchid_dir / "tokens.json"
    assert file_path.exists()
    perms = stat.S_IMODE(file_path.stat().st_mode)
    assert perms == 0o600, f"expected 0o600, got 0o{perms:o}"


def test_save_is_atomic_no_partial_files_left_behind(isolated_orchid_dir):
    """A successful save leaves only the canonical ``tokens.json``;
    no stray ``.tokens_*.tmp`` files remain in the directory."""
    save_token("client-a", StoredToken(access_token="t1"))
    save_token("client-b", StoredToken(access_token="t2"))

    children = sorted(p.name for p in isolated_orchid_dir.iterdir())
    assert children == ["tokens.json"]


def test_save_then_load_round_trips(isolated_orchid_dir):
    """Smoke test — the security hardening must not break the basic
    round-trip contract callers depend on."""
    original = StoredToken(
        access_token="abc",
        refresh_token="def",
        expires_at=12345.0,
        scopes="openid profile",
        tenant_key="tenant-1",
        user_id="user-1",
    )
    save_token("client-a", original)

    loaded = load_token("client-a")
    assert loaded is not None
    assert loaded.access_token == "abc"
    assert loaded.refresh_token == "def"
    assert loaded.tenant_key == "tenant-1"


def test_concurrent_writes_do_not_corrupt_file(isolated_orchid_dir):
    """Two threads racing on ``save_token`` for different clients must
    end with both clients persisted — neither call may corrupt the
    other's payload, and the file must still be valid JSON."""

    def _writer_a() -> None:
        for i in range(20):
            save_token("client-a", StoredToken(access_token=f"a-{i}"))

    def _writer_b() -> None:
        for i in range(20):
            save_token("client-b", StoredToken(access_token=f"b-{i}"))

    t_a = threading.Thread(target=_writer_a)
    t_b = threading.Thread(target=_writer_b)
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    file_path = isolated_orchid_dir / "tokens.json"
    parsed = json.loads(file_path.read_text())
    assert "client-a" in parsed
    assert "client-b" in parsed
    # The exact tail values are race-dependent, but both must look
    # like the right writer's output (no half-written keys).
    assert parsed["client-a"]["access_token"].startswith("a-")
    assert parsed["client-b"]["access_token"].startswith("b-")


def test_concurrent_reader_during_write_never_returns_torn_json(isolated_orchid_dir):
    """While a writer is mid-publish, a reader must see either the
    old map or the new one — never a partial JSON document."""
    # Seed an initial value.
    save_token("seed", StoredToken(access_token="seed-token"))

    write_count = 50
    read_errors: list[str] = []

    def _writer() -> None:
        for i in range(write_count):
            save_token("seed", StoredToken(access_token=f"v-{i}"))

    def _reader() -> None:
        for _ in range(write_count * 2):
            try:
                token = load_token("seed")
                # ``None`` is acceptable only if the file briefly
                # vanished; on this code path it shouldn't happen
                # because we seeded the file before starting.
                if token is None or not token.access_token.startswith(("seed-", "v-")):
                    read_errors.append(f"unexpected token: {token!r}")
            except Exception as exc:  # noqa: BLE001
                read_errors.append(repr(exc))

    t_w = threading.Thread(target=_writer)
    t_r = threading.Thread(target=_reader)
    t_w.start()
    t_r.start()
    t_w.join()
    t_r.join()

    assert not read_errors, f"reader hit {len(read_errors)} torn reads: {read_errors[:3]}"


def test_temp_file_cleaned_up_on_serialization_error(isolated_orchid_dir, monkeypatch):
    """If the JSON serializer raises mid-write, the helper must not
    leak a ``.tokens_*.tmp`` file."""

    def _boom(*_args, **_kwargs):
        raise TypeError("crafted failure")

    monkeypatch.setattr(token_store.json, "dumps", _boom)

    with pytest.raises(TypeError, match="crafted failure"):
        save_token("client-a", StoredToken(access_token="t1"))

    # No partial tmp file remains in the directory.
    leftovers = [p.name for p in isolated_orchid_dir.iterdir()]
    assert not any(name.startswith(".tokens_") for name in leftovers), leftovers
