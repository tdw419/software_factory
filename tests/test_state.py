import json

from conftest import init_lane

from software_factory import decision_log, gate, queue_state


def test_log_is_raw_utf8_not_escaped(repo):
    decision_log.append(repo, {"actor": "t", "note": "GO gate B — laptop"})
    raw = (repo / ".factory" / "decision_log.jsonl").read_bytes()
    assert "—".encode() in raw          # raw em dash survives
    assert b"\\u2014" not in raw        # never the escape form
    json.loads(raw.splitlines()[0])     # still valid JSON


def test_go_abort_pairing(repo):
    rec = decision_log.append(repo, {"actor": "op", "scanout_go": "GO now"})
    assert len(decision_log.un_abortedgos(repo, "scanout")) == 1
    decision_log.mark_aborted(repo, "scanout", rec["ts"], "changed mind")
    assert decision_log.un_abortedgos(repo, "scanout") == []


def test_queue_validation(repo):
    init_lane(repo)
    q = queue_state.load(repo)
    assert q["lane"] == "lane"
    assert len(q["rules"]) == 10
    bad = dict(q)
    bad["rungs"] = {"r0": {"status": "NOPE"}}
    try:
        queue_state.validate(bad)
        assert False, "expected QueueError"
    except queue_state.QueueError:
        pass


def test_next_actionable_order_and_resume(repo):
    init_lane(repo)
    q = queue_state.load(repo)
    queue_state.register_rung(q, "r1", "one", ".factory/tickets/t1.md")
    queue_state.register_rung(q, "r2", "two", ".factory/tickets/t2.md")
    queue_state.save(repo, q)
    rid, resuming = queue_state.next_actionable(q)
    assert (rid, resuming) == ("r1", False)
    q["rungs"]["r1"]["status"] = "IN_PROGRESS"
    q["rungs"]["r1"]["claimed_by"] = "lane"
    rid, resuming = queue_state.next_actionable(q)
    assert (rid, resuming) == ("r1", True)
    q["rungs"]["r1"]["status"] = "LANDED"
    rid, _ = queue_state.next_actionable(q)
    assert rid == "r2"


def test_register_dup_refused(repo):
    init_lane(repo)
    q = queue_state.load(repo)
    queue_state.register_rung(q, "r1", "one", "t.md")
    try:
        queue_state.register_rung(q, "r1", "one", "t.md")
        assert False, "expected QueueError"
    except queue_state.QueueError:
        pass
