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


def test_un_abortedgos_single_pass(repo, monkeypatch):
    decision_log.append(repo, {"actor": "op", "scanout_go": "GO now"})
    calls = {"n": 0}
    real_read_all = decision_log.read_all

    def counting_read_all(r):
        calls["n"] += 1
        return real_read_all(r)

    monkeypatch.setattr(decision_log, "read_all", counting_read_all)
    gos = decision_log.un_abortedgos(repo, "scanout")
    assert calls["n"] == 1
    assert len(gos) == 1 and gos[0]["scanout_go"] == "GO now"


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


# ---------- p5: difficulty metadata on rungs ----------

def test_register_rung_stores_stripped_nonempty_difficulty(repo):
    init_lane(repo)
    q = queue_state.load(repo)
    queue_state.register_rung(q, "r1", "one", "t.md", difficulty="  mechanical  ")
    assert q["rungs"]["r1"]["difficulty"] == "mechanical"


def test_register_rung_empty_or_missing_difficulty_not_stored(repo):
    init_lane(repo)
    q = queue_state.load(repo)
    queue_state.register_rung(q, "r1", "one", "t.md", difficulty="   ")
    queue_state.register_rung(q, "r2", "two", "t.md")
    assert "difficulty" not in q["rungs"]["r1"]
    assert "difficulty" not in q["rungs"]["r2"]


def test_update_rung_difficulty_set_and_clear(repo):
    init_lane(repo)
    q = queue_state.load(repo)
    queue_state.register_rung(q, "r1", "one", "t.md")
    _, changes = queue_state.update_rung(q, "r1", difficulty="mechanical")
    assert q["rungs"]["r1"]["difficulty"] == "mechanical"
    assert changes["difficulty"] == "mechanical"
    # whitespace-only clears the field
    _, changes = queue_state.update_rung(q, "r1", difficulty="  ")
    assert "difficulty" not in q["rungs"]["r1"]
    assert changes["difficulty"] is None
