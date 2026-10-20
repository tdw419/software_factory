"""p2 — rung conflict metadata (--files) + symmetric path/glob overlap filter.

Covers:
  1. queue_state.files_overlap symmetry: exact paths, directory prefixes vs
     nested files, path-boundary non-matches (foo vs foobar.py), r6 globs.
  2. `factory ticket add --files` and `factory ticket set --files`.
  3. next_actionable(q, in_flight_files=...) conflict skipping: later
     non-conflicting OPEN rung picked, (None, False) when all OPEN rungs
     conflict, and claimed IN_PROGRESS rungs never skipped.
"""

import json

from conftest import init_lane

from software_factory import queue_state
from software_factory.cli import main


# ---------- 1. files_overlap ----------

def test_files_overlap_exact_paths_symmetric():
    a = ["software_factory/observer.py"]
    b = ["software_factory/observer.py"]
    assert queue_state.files_overlap(a, b)
    assert queue_state.files_overlap(b, a)


def test_files_overlap_directory_prefix_vs_nested_file():
    d = ["software_factory"]
    f = ["software_factory/observer.py"]
    assert queue_state.files_overlap(d, f)
    assert queue_state.files_overlap(f, d)


def test_files_overlap_path_boundary_no_false_conflict():
    assert not queue_state.files_overlap(["foo"], ["foobar.py"])
    assert not queue_state.files_overlap(["foobar.py"], ["foo"])


def test_files_overlap_globs_symmetric():
    assert queue_state.files_overlap(["tests/test_*.py"], ["tests/test_pool.py"])
    assert queue_state.files_overlap(["tests/test_pool.py"], ["tests/test_*.py"])


def test_files_overlap_disjoint_paths():
    assert not queue_state.files_overlap(["a.py"], ["b.py"])


def test_files_overlap_empty_or_none_is_false():
    assert not queue_state.files_overlap(None, ["a.py"])
    assert not queue_state.files_overlap(["a.py"], None)
    assert not queue_state.files_overlap([], ["a.py"])
    assert not queue_state.files_overlap(["a.py"], [])
    assert not queue_state.files_overlap(None, None)


def test_files_overlap_normalization_dot_slash_and_trailing_slash():
    assert queue_state.files_overlap(["./software_factory/"], ["software_factory/x.py"])
    assert queue_state.files_overlap(["software_factory/observer.py"], ["./software_factory/observer.py"])


# ---------- 2. CLI --files passthrough ----------

def _ticket_file(repo, name="t.md"):
    p = repo / ".factory" / "tickets" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("## Goal\n\n## Stages\n\n## Constraints\n\n## What this does NOT prove\n")
    return str(p.relative_to(repo))


def test_ticket_add_files_flag(repo, capsys):
    init_lane(repo)
    t = _ticket_file(repo)
    assert main(["--repo", str(repo), "ticket", "add", "--id", "x1",
                 "--title", "X", "--ticket", t,
                 "--files", "software_factory/observer.py, tests/test_*.py"]) == 0
    q = queue_state.load(repo)
    assert q["rungs"]["x1"]["files"] == ["software_factory/observer.py", "tests/test_*.py"]


def test_ticket_set_files_flag(repo, capsys):
    init_lane(repo)
    t = _ticket_file(repo)
    assert main(["--repo", str(repo), "ticket", "add", "--id", "x1",
                 "--title", "X", "--ticket", t]) == 0
    assert "files" not in queue_state.load(repo)["rungs"]["x1"]
    assert main(["--repo", str(repo), "ticket", "set", "x1",
                 "--files", " a.py ,  b/c.py ,"]) == 0
    q = queue_state.load(repo)
    # whitespace stripped, empty items dropped
    assert q["rungs"]["x1"]["files"] == ["a.py", "b/c.py"]


def test_register_and_update_rung_files_validation():
    q = queue_state.new_queue("lane")
    queue_state.register_rung(q, "r1", "t", "t.md", files=["a.py"])
    assert q["rungs"]["r1"]["files"] == ["a.py"]
    import pytest
    with pytest.raises(queue_state.QueueError):
        queue_state.update_rung(q, "r1", files=["a.py", ""])
    with pytest.raises(queue_state.QueueError):
        queue_state.update_rung(q, "r1", files=[123])
    _, changes = queue_state.update_rung(q, "r1", files=["b.py"])
    assert changes["files"] == ["b.py"]


# ---------- 3. next_actionable in_flight_files ----------

def _queue_with(rid, status, files=None, claimed_by=None):
    q = queue_state.new_queue("lane")
    queue_state.register_rung(q, rid, rid, f"{rid}.md", status=status,
                              claimed_by=claimed_by, files=files)
    return q


def test_next_actionable_backward_compat_single_arg():
    q = _queue_with("r1", "OPEN")
    assert queue_state.next_actionable(q) == ("r1", False)


def test_next_actionable_skips_conflicting_open_picks_later():
    q = _queue_with("r1", "OPEN", files=["a.py"])
    queue_state.register_rung(q, "r2", "r2", "r2.md", files=["b.py"])
    rid, resuming = queue_state.next_actionable(q, in_flight_files=["a.py"])
    assert (rid, resuming) == ("r2", False)


def test_next_actionable_none_when_all_open_conflict():
    q = _queue_with("r1", "OPEN", files=["a.py"])
    queue_state.register_rung(q, "r2", "r2", "r2.md", files=["a/b.py"])
    assert queue_state.next_actionable(q, in_flight_files=["a.py"]) == (None, False)


def test_next_actionable_never_skips_claimed_in_progress():
    q = _queue_with("r1", "IN_PROGRESS", claimed_by="hermes-cli", files=["a.py"])
    queue_state.register_rung(q, "r2", "r2", "r2.md", files=["a.py"])
    rid, resuming = queue_state.next_actionable(q, in_flight_files=["a.py"])
    assert (rid, resuming) == ("r1", True)


def test_next_actionable_open_without_files_never_conflicts():
    q = _queue_with("r1", "OPEN", files=["a.py"])
    queue_state.register_rung(q, "r2", "r2", "r2.md")
    rid, resuming = queue_state.next_actionable(q, in_flight_files=["a.py"])
    assert (rid, resuming) == ("r2", False)
