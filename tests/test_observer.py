import json

from conftest import git, init_lane

from software_factory import observer, queue_state


def healthy_lane(repo):
    init_lane(repo)
    t = repo / ".factory" / "tickets" / "t1.md"
    t.write_text("ticket body\n")
    q = queue_state.load(repo)
    queue_state.register_rung(q, "t1", "demo", ".factory/tickets/t1.md",
                              receipt=".factory/receipts/t1_RECEIPT.md")
    q["rungs"]["t1"].update(status="LANDED", commit=None)
    queue_state.save(repo, q)
    (repo / ".factory" / "receipts" / "t1_RECEIPT.md").write_text("receipt\n")
    git(repo, "add", ".factory")
    git(repo, "commit", "-qm", "lane: t1")
    q = queue_state.load(repo)
    q["rungs"]["t1"]["commit"] = git(repo, "rev-parse", "HEAD")
    queue_state.save(repo, q)
    git(repo, "add", ".factory/queue_state.json")
    git(repo, "commit", "-qm", "lane: pin sha")
    return q


def test_clean_lane_observes_clean(repo):
    healthy_lane(repo)
    lines = observer.observe(repo)
    d = dict(ln.split("=", 1) for ln in lines)
    assert d["queue_parse"] == "OK"
    assert d["rung_t1_status"] == "LANDED"
    assert d["rung_t1_handle"] == "RESOLVED"
    assert d["receipts_missing"] == "none"
    assert d["tree"] == "CLEAN"


def test_observer_output_is_stable(repo):
    healthy_lane(repo)
    a = observer.observe(repo)
    b = observer.observe(repo)
    assert a == b
    assert not any(":" in ln.split("=")[-1] for ln in a), \
        "no timestamps in stdout — it is a change-gating tuple"


def test_prose_commit_handle_detected(repo):
    healthy_lane(repo)
    q = queue_state.load(repo)
    q["rungs"]["t1"]["commit"] = "this commit (see report)"
    queue_state.save(repo, q)
    d = dict(ln.split("=", 1) for ln in observer.observe(repo))
    assert d["rung_t1_handle"] == "PROSE"


def test_broken_commit_handle_detected(repo):
    healthy_lane(repo)
    q = queue_state.load(repo)
    q["rungs"]["t1"]["commit"] = "deadbeefdead"
    queue_state.save(repo, q)
    d = dict(ln.split("=", 1) for ln in observer.observe(repo))
    assert d["rung_t1_handle"] == "BROKEN"


def test_missing_commit_handle_detected(repo):
    healthy_lane(repo)
    q = queue_state.load(repo)
    q["rungs"]["t1"]["commit"] = None
    queue_state.save(repo, q)
    d = dict(ln.split("=", 1) for ln in observer.observe(repo))
    assert d["rung_t1_handle"] == "MISSING"


def test_missing_receipt_detected(repo):
    healthy_lane(repo)
    (repo / ".factory" / "receipts" / "t1_RECEIPT.md").unlink()
    d = dict(ln.split("=", 1) for ln in observer.observe(repo))
    assert d["receipts_missing"] == "t1"


def test_watch_rules_by_content_not_index(repo):
    import hashlib

    def sha12(s):
        return hashlib.sha256(s.encode()).hexdigest()[:12]

    healthy_lane(repo)
    watch = ["WAKE DISCIPLINE", "Z_ORDER_TIES"]  # second rule absent
    d = dict(ln.split("=", 1) for ln in observer.observe(repo, watch_rules=watch))
    assert d["watch_" + sha12("WAKE DISCIPLINE")] == "OK"     # found by content
    assert d["watch_" + sha12("Z_ORDER_TIES")] == "GONE"      # never by index


def test_log_written_only_on_change(repo, tmp_path):
    healthy_lane(repo)
    log_dir = tmp_path / "obslogs"
    observer.run(repo, log_dir=log_dir)
    observer.run(repo, log_dir=log_dir)
    first = (log_dir / "observer.log").read_text()
    observer.run(repo, log_dir=log_dir)
    assert (log_dir / "observer.log").read_text() == first
    # break something -> next run logs
    q = queue_state.load(repo)
    q["rungs"]["t1"]["commit"] = "deadbeefdead"
    queue_state.save(repo, q)
    observer.run(repo, log_dir=log_dir)
    assert (log_dir / "observer.log").read_text() != first
