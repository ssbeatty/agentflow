"""Async script-folder reclamation (services/script_cleanup.py).

Covers the two halves of the async-delete design:
  - `delete_script_dir` removes a script's on-disk folder (the background task).
  - `sweep_orphan_script_dirs` (startup fallback) removes only folders with NO
    live Script row, and NEVER a live script's — including the AI assistant.

Uses the `db` fixture (temp sqlite) + the isolated temp DATA_DIR from conftest.
"""
from app.config import DATA_DIR
from app.models import Script
from services.script_cleanup import delete_script_dir, sweep_orphan_script_dirs


def _make_dir(name: str):
    d = DATA_DIR / name
    (d / ".venv").mkdir(parents=True, exist_ok=True)
    (d / ".venv" / "big.bin").write_bytes(b"x" * 1024)
    return d


def test_delete_script_dir_removes_folder():
    d = _make_dir("some-script-id")
    assert d.exists()
    delete_script_dir("some-script-id")
    assert not d.exists()


def test_delete_script_dir_missing_is_noop():
    # No folder on disk (e.g. a script that never ran) → silent no-op, no raise.
    delete_script_dir("never-materialized")


def test_sweep_removes_only_orphans(db):
    live = Script(name="live")
    db.add(live)
    db.flush()
    db.commit()

    live_dir = _make_dir(live.id)
    orphan1 = _make_dir("orphan-aaaa")
    orphan2 = _make_dir("orphan-bbbb")
    # A dot-dir (transient tooling) and a stray file must be left untouched.
    (DATA_DIR / ".trash").mkdir(exist_ok=True)
    (DATA_DIR / "stray.txt").write_text("keep me")

    removed = sweep_orphan_script_dirs(db)

    # >= 2 (not == 2): DATA_DIR is shared for the whole test session, so other
    # test files may have left orphan folders that this sweep also reaps.
    assert removed >= 2
    assert live_dir.exists()          # live script protected (has a DB row)
    assert not orphan1.exists()
    assert not orphan2.exists()
    assert (DATA_DIR / ".trash").exists()
    assert (DATA_DIR / "stray.txt").exists()


def test_sweep_never_deletes_assistant(db):
    """The built-in AI assistant is a live Script → its folder is protected,
    exactly like any other live script."""
    from services.assistant_seed import ASSISTANT_SCRIPT_NAME

    assistant = Script(name=ASSISTANT_SCRIPT_NAME)
    db.add(assistant)
    db.flush()
    db.commit()
    assistant_dir = _make_dir(assistant.id)

    sweep_orphan_script_dirs(db)

    assert assistant_dir.exists()
