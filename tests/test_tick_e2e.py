import json
import textwrap

from conftest import git, init_lane

from software_factory import decision_log, tick

FAKE_BUILDER = textwrap.dedent("""\
    import json, subprocess, sys
    from pathlib import Path
    repo = Path(sys.argv[1])
    mode = sys.argv[2]
    qp = repo / ".factory" / "queue_state.json"
    q = json.loads(qp.read_text())
    rid = next(k for k, v in q["rungs"].items()
               if v["status"] in ("OPEN", "IN_PROGRESS"))
    def g(*a):
        return subprocess.run(["git", "-C", str(repo), *a],
                              capture_output=True, text=True)
    if mode == "land":
        q["rungs"][rid].update(status="LANDED", claimed_by="fake-builder",
                               claimed_at="t", landed_at="t", commit="PENDING")
        qp.write_text(json.dumps(q, indent=2, ensure_ascii=False))
        (repo / f".factory/receipts/{rid}_RECEIPT.md").write_text(
            "# RECEIPT\\n\\n## What PASS proves\\nfake\\n"
            "## What this does NOT prove\\n- nothing real happened\\n")
        g("add", ".factory/queue_state.json",
          f".factory/receipts/{rid}_RECEIPT.md")
        g("commit", "-qm", f"{rid}: land")
        sha = g("rev-parse", "HEAD").stdout.strip()
        q["rungs"][rid]["commit"] = sha
        qp.write_text(json.dumps(q, indent=2, ensure_ascii=False))
        g("add", ".factory/queue_state.json")
        g("commit", "-qm", f"{rid}: pin sha")
    elif mode == "claim_no_commit":
        q["rungs"][rid].update(status="IN_PROGRESS",
                               claimed_by="fake-builder")
        qp.write_text(json.dumps(q, indent=2, ensure_ascii=False))
    elif mode == "sloppy_receipt":
        q["rungs"][rid].update(status="LANDED", claimed_by="fake-builder",
                               claimed_at="t", landed_at="t", commit="PENDING")
        qp.write_text(json.dumps(q, indent=2, ensure_ascii=False))
        (repo / f".factory/receipts/{rid}_RECEIPT.md").write_text(
            "# RECEIPT\\n\\n## What PASS proves\\nfake without proof limits\\n")
        g("add", ".factory/queue_state.json",
          f".factory/receipts/{rid}_RECEIPT.md")
        g("commit", "-qm", f"{rid}: sloppy land")
    elif mode == "unclaimed":
        # commits real work + a valid receipt but forgets claimed_by —
        # the rung becomes unreachable by next_actionable forever
        q["rungs"][rid].update(status="IN_PROGRESS")
        qp.write_text(json.dumps(q, indent=2, ensure_ascii=False))
        (repo / f".factory/receipts/{rid}_RECEIPT.md").write_text(
            "# RECEIPT\\n\\n## What PASS proves\\nfake\\n"
            "## What this does NOT prove\\n- nothing real happened\\n")
        g("add", ".factory/queue_state.json",
          f".factory/receipts/{rid}_RECEIPT.md")
        g("commit", "-qm", f"{rid}: unclaimed land")
    # mode "nothing": exit 0 without touching anything
""")


def setup_builder(repo, mode, verify_cmd="true"):
    b = repo / "_fake_builder.py"
    b.write_text(FAKE_BUILDER)
    init_lane(repo, verify_cmd=verify_cmd,
              builder_cmd=f"python3 {b} {{repo}} {mode}")
    # register a rung + ticket
    t = repo / ".factory" / "tickets" / "t1.md"
    t.write_text("# TICKET — t1: demo\\n## Goal\\nx\\n## Stages\\n- s\\n## Constraints\\n- c\\n")
    from software_factory import queue_state
    q = queue_state.load(repo)
    queue_state.register_rung(q, "t1", "demo", ".factory/tickets/t1.md")
    queue_state.save(repo, q)


def test_full_success_loop(repo):
    setup_builder(repo, "land")
    code, msg = tick.run_tick(repo)
    assert code == tick.EXIT_OK, msg
    assert msg.startswith("WAKE")
    q = json.loads((repo / ".factory" / "queue_state.json").read_text())
    r = q["rungs"]["t1"]
    assert r["status"] == "LANDED"
    assert "PENDING" not in r["commit"]          # real sha pinned, never prose
    recs = decision_log.read_all(repo)
    assert any("tick" in r_ and r_["tick"]["rung"] == "t1" for r_ in recs)
    state = tick.load_state(repo)
    assert state["wakes_total"] == 1 and not state["parked"]


def test_second_tick_suppressed(repo):
    setup_builder(repo, "land")
    code, msg = tick.run_tick(repo)
    assert code == tick.EXIT_OK
    code, msg = tick.run_tick(repo)
    assert code == tick.EXIT_OK
    assert msg.startswith("SUPPRESSED no_change")
    state = tick.load_state(repo)
    assert state["suppressed_total"] == 1
    markers = list((repo / ".factory" / "runs").glob("*-suppressed"))
    assert markers, "suppressed tick should leave a cheap marker"


def test_builder_zero_but_no_commit_violates_wake_discipline(repo):
    setup_builder(repo, "claim_no_commit")
    code, msg = tick.run_tick(repo)
    assert code != 0
    recs = decision_log.read_all(repo)
    failed = [r for r in recs if "tick_failed" in r]
    assert failed and "WAKE DISCIPLINE" in failed[-1]["tick_failed"]["problem"]


def test_park_after_three_failures_then_force_unparks(repo):
    setup_builder(repo, "claim_no_commit")
    codes = []
    for _ in range(3):
        code, msg = tick.run_tick(repo)
        codes.append(code)
    assert all(c != 0 for c in codes)
    state = tick.load_state(repo)
    assert state["parked"], "lane must park after 3 consecutive failures"
    assert state["consecutive_failures"] == 3
    # parked: even a changed tree will not dispatch
    code, msg = tick.run_tick(repo)
    assert code == tick.EXIT_PARKED
    # operator fixes the builder, force-unparks
    b = repo / "_fake_builder.py"
    cfg_path = repo / ".factory" / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["builder"]["cmd"] = f"python3 {b} {{repo}} land"
    cfg_path.write_text(json.dumps(cfg, indent=2))
    code, msg = tick.run_tick(repo, force=True)
    assert code == tick.EXIT_OK, msg
    state = tick.load_state(repo)
    assert not state["parked"]


def test_verify_red_blocks_landing(repo):
    setup_builder(repo, "land", verify_cmd="false")
    code, msg = tick.run_tick(repo)
    assert code == tick.EXIT_VERIFY_RED
    recs = decision_log.read_all(repo)
    failed = [r for r in recs if "tick_failed" in r]
    assert failed and "verify gate RED" in failed[-1]["tick_failed"]["problem"]
    # fingerprint NOT advanced → the next tick re-wakes instead of suppressing;
    # here the builder DID land the rung (commits moved HEAD), so the wake
    # finds no actionable ticket — the point is it did NOT say SUPPRESSED
    code2, msg2 = tick.run_tick(repo)
    assert code2 == tick.EXIT_OK
    assert msg2.startswith("WAKE no_actionable_ticket")


def test_dry_run_leaves_no_state(repo):
    setup_builder(repo, "land")
    before = tick.load_state(repo)
    code, msg = tick.run_tick(repo, dry_run=True)
    assert code == tick.EXIT_OK and msg.startswith("DRY-RUN")
    assert tick.load_state(repo) == before


def test_noop_adapter_accepts_five_args_without_type_error(repo):
    setup_builder(repo, "land")
    cfg_path = repo / ".factory" / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["builder"]["adapter"] = "noop"
    cfg_path.write_text(json.dumps(cfg, indent=2))
    code, msg = tick.run_tick(repo)
    # noop returns 0 without creating a receipt, so tick fails on missing receipt
    # rather than crashing with TypeError inside adapter_fn
    assert "TypeError" not in msg
    assert "receipt missing" in msg


def test_force_tick_on_degraded_repo_unparks_and_exits_nonzero(repo, monkeypatch, tmp_path):
    setup_builder(repo, "claim_no_commit")
    for _ in range(3):
        tick.run_tick(repo)
    assert tick.load_state(repo)["parked"] is True

    # Simulate transient git failure
    monkeypatch.setattr(tick.digest, "compute",
                        lambda *a, **kw: tick.digest.Fingerprint({}, degraded=True))
    code, msg = tick.run_tick(repo, force=True)
    assert code == tick.EXIT_DEGRADED
    assert "SUPPRESSED degraded" in msg
    state = tick.load_state(repo)
    assert state["parked"] is False
    assert state["consecutive_failures"] == 0


def test_flock_concurrency_guard_prevents_overlapping_ticks(repo):
    import fcntl
    setup_builder(repo, "land")
    lp = tick.lock_path(repo)
    lp.parent.mkdir(parents=True, exist_ok=True)
    with open(lp, "a+", encoding="utf-8") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            code, msg = tick.run_tick(repo)
            assert code == tick.EXIT_LOCKED
            assert "SUPPRESSED locked" in msg
        finally:
            fcntl.flock(held.fileno(), fcntl.LOCK_UN)
    # Once released, tick proceeds normally
    code2, msg2 = tick.run_tick(repo)
    assert code2 == tick.EXIT_OK
    assert msg2.startswith("WAKE")


def test_transient_builder_timeout_does_not_park_lane(repo):
    init_lane(repo, verify_cmd="true", builder_cmd="sleep 5")
    t = repo / ".factory" / "tickets" / "t1.md"
    t.write_text("# TICKET — t1: demo\n## Goal\nx\n## Stages\n- s\n## Constraints\n- c\n")
    from software_factory import queue_state
    q = queue_state.load(repo)
    queue_state.register_rung(q, "t1", "demo", ".factory/tickets/t1.md")
    queue_state.save(repo, q)

    for _ in range(3):
        code, msg = tick.run_tick(repo, builder_timeout=1)
        assert code == tick.EXIT_BUILDER_FAILED
        assert "builder TIMEOUT" in msg

    state = tick.load_state(repo)
    assert state["parked"] is False
    assert state["consecutive_failures"] == 0
    assert state["transient_failures"] == 3


def test_sloppy_receipt_missing_proof_limits_rejected(repo):
    setup_builder(repo, "sloppy_receipt")
    code, msg = tick.run_tick(repo)
    assert code == tick.EXIT_BUILDER_FAILED
    assert "receipt incomplete" in msg
    assert "## What this does NOT prove" in msg


def test_unclaimed_in_progress_violates_queue_discipline(repo):
    """A rung left IN_PROGRESS with no claimed_by is unreachable by
    next_actionable — without this check the tick goes GREEN, the next tick
    suppresses, and the lane silently dies with the rung half-done."""
    setup_builder(repo, "unclaimed")
    code, msg = tick.run_tick(repo)
    assert code == tick.EXIT_BUILDER_FAILED
    assert "QUEUE DISCIPLINE" in msg
    recs = decision_log.read_all(repo)
    failed = [r for r in recs if "tick_failed" in r]
    assert "QUEUE DISCIPLINE" in failed[-1]["tick_failed"]["problem"]
    # and it was NOT a wake-discipline hit: the builder did commit
    assert "WAKE DISCIPLINE" not in failed[-1]["tick_failed"]["problem"]
