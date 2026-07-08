"""Script version-management (revision snapshots) — the "baseline" contract.

Regression home for the version-history bug where the diff baseline was off by
one: snapshots were taken *after* the new file content had already been written,
so every revision captured the post-save state, the newest revision always
equalled the current content (empty diff), and there was no baseline for the
pristine starting point.

The contract these lock in:
  - creating a script (and forking one) records a baseline revision #1 = the
    starting content, so history has a true origin to diff against;
  - a snapshot captures the content *as it is now*, and older revisions are
    never mutated — so diffing revision #N against #N-1 shows exactly what that
    version changed;
  - automatic (unlabeled) snapshots de-dupe when nothing that defines a version
    (files / requirements / entry_function) changed, so a metadata-only save
    can't flood the history with identical revisions; a *labeled* snapshot is
    always kept (the caller explicitly wants a marked point).
"""
from app.routers.scripts import (
    create_script, _snapshot, list_revisions, get_revision, fork_revision,
)
from app.schemas import ScriptCreate, ForkRevisionRequest
from app.models import ScriptFile


def _new_script(db, name="s1"):
    return create_script(ScriptCreate(name=name), db)


def _main_content(detail):
    return next(f for f in detail.files if f.is_main).content


def _edit_main(db, script_id, content):
    f = db.query(ScriptFile).filter_by(script_id=script_id, is_main=True).first()
    f.content = content
    db.commit()


def test_create_records_baseline_revision(db):
    s = _new_script(db)
    revs = list_revisions(s.id, db)
    assert [r.revision_number for r in revs] == [1]
    detail = get_revision(s.id, revs[0].id, db)
    assert "def run" in _main_content(detail)  # the pristine template


def test_snapshot_captures_new_content_and_keeps_baseline_intact(db):
    """The heart of the bug: after an edit, #2 = new content and #1 (baseline)
    is untouched, so a #2-vs-#1 diff actually shows the change."""
    s = _new_script(db)
    _edit_main(db, s.id, "def run(input):\n    return {'v': 2}\n")
    _snapshot(s.id, "", db)

    revs = list_revisions(s.id, db)  # newest first
    assert [r.revision_number for r in revs] == [2, 1]

    latest = get_revision(s.id, revs[0].id, db)
    baseline = get_revision(s.id, revs[1].id, db)
    assert "return {'v': 2}" in _main_content(latest)
    # Baseline still holds the ORIGINAL template — not the post-edit content.
    assert "return {'v': 2}" not in _main_content(baseline)


def test_unlabeled_snapshot_dedupes_when_nothing_changed(db):
    s = _new_script(db)  # baseline #1
    _snapshot(s.id, "", db)  # no change → must NOT create a duplicate
    assert [r.revision_number for r in list_revisions(s.id, db)] == [1]


def test_labeled_snapshot_always_kept_even_if_identical(db):
    s = _new_script(db)  # #1
    _snapshot(s.id, "manual mark", db)  # explicit label → keep even if identical
    revs = list_revisions(s.id, db)
    assert [r.revision_number for r in revs] == [2, 1]
    assert revs[0].label == "manual mark"


def test_snapshot_created_when_content_changes(db):
    s = _new_script(db)
    _edit_main(db, s.id, "x = 1\n")
    _snapshot(s.id, "", db)
    assert len(list_revisions(s.id, db)) == 2
    # A second unlabeled snapshot with no further change de-dupes again.
    _snapshot(s.id, "", db)
    assert len(list_revisions(s.id, db)) == 2


def test_fork_gets_its_own_baseline_revision(db):
    s = _new_script(db)
    rev = list_revisions(s.id, db)[0]
    forked = fork_revision(s.id, rev.id, ForkRevisionRequest(name="forked"), db)
    revs = list_revisions(forked.id, db)
    assert [r.revision_number for r in revs] == [1]
    assert "def run" in _main_content(get_revision(forked.id, revs[0].id, db))
