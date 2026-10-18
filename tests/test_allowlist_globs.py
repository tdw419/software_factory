"""r6: allowlist glob patterns.

Entries containing glob metacharacters (*, ?, [) match via fnmatch.fnmatch
against the full lane-relative path. Entries without metacharacters keep the
exact/prefix semantics (zero behavior change for existing configs).
"""
from conftest import git, init_lane

from software_factory.common import is_under_allowlist, scoped_dirty_rows
from software_factory.digest import compute


def test_glob_entry_suppresses_wake(repo):
    before = compute(repo, allowlist=("*.local.json",)).stable
    (repo / "db.local.json").write_text("x\n")
    after = compute(repo, allowlist=("*.local.json",)).stable
    assert before == after
    assert compute(repo, allowlist=("*.local.json",)).parts["TREE"] == "CLEAN"


def test_glob_dir_pattern_suppresses_wake(repo):
    allow = ("audits/*.md",)
    before = compute(repo, allowlist=allow).stable
    (repo / "audits").mkdir()
    (repo / "audits" / "q1.md").write_text("audit\n")
    assert compute(repo, allowlist=allow).stable == before
    # fnmatch '*' crosses path separators: nested audit notes are matched too
    (repo / "audits" / "nested").mkdir()
    (repo / "audits" / "nested" / "deep.md").write_text("deep\n")
    assert compute(repo, allowlist=allow).stable == before
    # non-matching extension under the same dir still wakes
    (repo / "audits" / "raw.txt").write_text("raw\n")
    assert compute(repo, allowlist=allow).stable != before


def test_glob_question_mark_is_single_char(repo):
    allow = ("audit?.md",)
    assert is_under_allowlist("audit1.md", allow)
    assert not is_under_allowlist("audit12.md", allow)


def test_glob_bracket_class(repo):
    allow = ("run[0-9].txt",)
    assert is_under_allowlist("run3.txt", allow)
    assert not is_under_allowlist("runX.txt", allow)


def test_non_glob_semantics_unchanged_alongside_globs(repo):
    allow = ("*.local.json", "notes/", "exact.txt")
    assert is_under_allowlist("exact.txt", allow)          # exact
    assert is_under_allowlist("notes/a/b.txt", allow)      # dir prefix
    assert not is_under_allowlist("notes_backup/x", allow)  # boundary still holds
    assert not is_under_allowlist("exact.txt.old", allow)   # exact, not prefix
    assert not is_under_allowlist("db.local.jsonx", allow)  # glob must be full-path


def test_scoped_dirty_rows_uses_same_matcher(repo):
    (repo / "db.local.json").write_text("x\n")
    (repo / "other.txt").write_text("y\n")
    ok, rows = scoped_dirty_rows(repo, allowlist=("*.local.json",))
    assert ok
    assert len(rows) == 1 and rows[0].endswith("other.txt")


def test_default_config_no_globs_digest_unchanged_by_r6(repo):
    """Regression leg: a config without glob entries keeps exact/prefix
    matching — digests computed before and after the r6 change must agree
    (pre-fix value recorded in .factory/receipts/r6_RECEIPT.md)."""
    init_lane(repo)
    before = compute(repo).stable
    with open(repo / ".factory" / "decision_log.jsonl", "a") as f:
        f.write('{"actor":"test","note":"churn"}\n')
    (repo / ".factory" / "runs").mkdir(exist_ok=True)
    (repo / ".factory" / "runs" / "m1").write_text("x\n")
    (repo / "wake.txt").write_text("wakes\n")
    after = compute(repo).stable
    assert before != after  # non-allowlisted dirt wakes (unchanged)
    (repo / "wake.txt").unlink()
    assert compute(repo).stable == before  # allowlisted churn silent (unchanged)


def test_glob_allowlisted_ticket_still_moves_TICKETS_channel(repo):
    """Safety leg: a glob matching digest-needed files (e.g.
    .factory/tickets/*.md) suppresses TREE dirt but TICKETS still hashes the
    file content — the fingerprint still moves via its dedicated channel."""
    init_lane(repo)
    allow = (".factory/tickets/*.md", ".factory/decision_log.jsonl",
             ".factory/state.json", ".factory/runs/", ".factory/asks/",
             ".factory/pending_gate.json", ".factory/tick.lock")
    git(repo, "add", ".factory")
    git(repo, "commit", "-qm", "lane files")  # no untracked noise in status
    (repo / ".factory" / "tickets" / "t9_w.md").write_text("v1\n")
    git(repo, "add", ".factory/tickets/t9_w.md")
    git(repo, "commit", "-qm", "ticket t9")
    fp1 = compute(repo, allowlist=allow)
    assert fp1.parts["TREE"] == "CLEAN"
    (repo / ".factory" / "tickets" / "t9_w.md").write_text("v2\n")
    fp2 = compute(repo, allowlist=allow)
    assert fp2.parts["TREE"] == "CLEAN"          # glob suppresses the tree row
    assert fp2.parts["TICKETS"] != fp1.parts["TICKETS"]  # dedicated channel wakes
    assert fp2.stable != fp1.stable
