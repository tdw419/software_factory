"""r4 — decision_log compaction guard.

Compact moves entries beyond the newest N to
.factory/decision_log.archive.jsonl; GO-spend accounting must survive the
archive window (un_abortedgos scans live + archive), compact must refuse to
run while a tick holds tick.lock, and the observer must report the archive's
existence as a stable bucketed line.
"""
import fcntl

import pytest
from conftest import init_lane

from software_factory import decision_log, gate, observer

PHRASE = "GO scanout — laptop"


@pytest.fixture(autouse=True)
def lane(repo):
    init_lane(repo)
    return repo


def _ap(repo):
    return repo / ".factory" / "decision_log.archive.jsonl"


def test_compact_moves_older_entries_to_archive(repo):
    for i in range(5):
        decision_log.append(repo, {"actor": "t", "n": i})
    code, summary = decision_log.compact(repo, keep=3)
    assert code == 0, summary
    assert summary["kept"] == 3 and summary["archived"] == 2

    live = decision_log.read_all(repo)
    assert [r.get("n") for r in live if "n" in r] == [2, 3, 4]
    archived = decision_log.read_archived(repo)
    assert [r.get("n") for r in archived if "n" in r] == [0, 1]

    # order preserved oldest-first on both sides of the split
    ts_live = [r["ts"] for r in live]
    ts_arch = [r["ts"] for r in archived]
    assert ts_live == sorted(ts_live) and ts_arch == sorted(ts_arch)
    assert _ap(repo).is_file()


def test_compact_emits_log_compacted_record(repo):
    for i in range(5):
        decision_log.append(repo, {"actor": "t", "n": i})
    decision_log.compact(repo, keep=3)
    recs = decision_log.read_all(repo)
    compacts = [r["log_compacted"] for r in recs if "log_compacted" in r]
    assert len(compacts) == 1
    assert compacts[0]["kept"] == 3
    assert compacts[0]["archived"] == 2


def test_compact_noop_when_under_keep(repo):
    decision_log.append(repo, {"actor": "t", "n": 1})
    code, summary = decision_log.compact(repo, keep=2000)
    assert code == 0
    assert summary["archived"] == 0
    assert not _ap(repo).exists()
    assert not any("log_compacted" in r for r in decision_log.read_all(repo))


def test_compact_refuses_keep_below_one(repo):
    code, _ = decision_log.compact(repo, keep=0)
    assert code == 2


def test_un_abortedgos_survives_compaction(repo):
    gate.arm(repo, "scanout", PHRASE, ["true"])
    code, _ = gate.fire(repo, PHRASE)
    assert code == 0
    # push the GO into the archive window
    for i in range(6):
        decision_log.append(repo, {"actor": "t", "n": i})
    code, summary = decision_log.compact(repo, keep=3)
    assert code == 0 and summary["archived"] > 0
    # the GO record itself is now in the archive...
    assert any("scanout_go" in r for r in decision_log.read_archived(repo))
    # ...and still spend-blocks a re-fire
    gate.arm(repo, "scanout", PHRASE, ["true"])
    code, rec = gate.fire(repo, PHRASE)
    assert code == 3
    assert rec["gate_refused"]["reason"] == "un-aborted GO already spent"
    # an abort appended to the LIVE log pairs by ts with the ARCHIVED GO
    go_ts = [r["ts"] for r in decision_log.read_archived(repo) if "scanout_go" in r][0]
    decision_log.mark_aborted(repo, "scanout", go_ts, "done")
    assert decision_log.un_abortedgos(repo, "scanout") == []


def test_compact_refuses_while_tick_lock_held(repo):
    for i in range(6):
        decision_log.append(repo, {"actor": "t", "n": i})
    lock_fd = open(repo / ".factory" / "tick.lock", "a+", encoding="utf-8")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        code, summary = decision_log.compact(repo, keep=3)
        assert code == 8, summary
        # nothing moved
        assert not _ap(repo).exists()
        assert len(decision_log.read_all(repo)) == 6
    finally:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()


def test_observer_reports_log_archive(repo):
    lines = observer.observe(repo)
    assert "log_archive=no" in lines
    for i in range(6):
        decision_log.append(repo, {"actor": "t", "n": i})
    decision_log.compact(repo, keep=3)
    lines = observer.observe(repo)
    assert "log_archive=yes" in lines
