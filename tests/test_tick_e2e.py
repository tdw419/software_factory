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
            "## Commands and outputs\\n```bash\\n$ true\\n# ok\\n```\\n"
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
            "## Commands and outputs\\n```bash\\n$ true\\n# ok\\n```\\n"
            "## What this does NOT prove\\n- nothing real happened\\n")
        g("add", ".factory/queue_state.json",
          f".factory/receipts/{rid}_RECEIPT.md")
        g("commit", "-qm", f"{rid}: unclaimed land")
    elif mode == "kernel_edit":
        (repo / "app.py").write_text("print('kernel modified')\\n")
        q["rungs"][rid].update(status="LANDED", claimed_by="fake-builder",
                               claimed_at="t", landed_at="t", commit="PENDING")
        qp.write_text(json.dumps(q, indent=2, ensure_ascii=False))
        (repo / f".factory/receipts/{rid}_RECEIPT.md").write_text(
            "# RECEIPT\\n\\n## What PASS proves\\nkernel\\n"
            "## Commands and outputs\\n```bash\\n$ true\\n# ok\\n```\\n"
            "## What this does NOT prove\\n- limits\\n")
        g("add", "app.py", ".factory/queue_state.json",
          f".factory/receipts/{rid}_RECEIPT.md")
        g("commit", "-qm", f"{rid}: kernel edit")
        sha = g("rev-parse", "HEAD").stdout.strip()
        q["rungs"][rid]["commit"] = sha
        qp.write_text(json.dumps(q, indent=2, ensure_ascii=False))
        g("add", ".factory/queue_state.json")
        g("commit", "-qm", f"{rid}: pin sha")
    elif mode == "kernel_dirt":
        # lands the rung properly but leaves an UNCOMMITTED kernel-path edit
        (repo / "app.py").write_text("print('uncommitted kernel dirt')\\n")
        q["rungs"][rid].update(status="LANDED", claimed_by="fake-builder",
                               claimed_at="t", landed_at="t", commit="PENDING")
        qp.write_text(json.dumps(q, indent=2, ensure_ascii=False))
        (repo / f".factory/receipts/{rid}_RECEIPT.md").write_text(
            "# RECEIPT\\n\\n## What PASS proves\\nfake\\n"
            "## Commands and outputs\\n```bash\\n$ true\\n# ok\\n```\\n"
            "## What this does NOT prove\\n- uncommitted kernel dirt\\n")
        g("add", ".factory/queue_state.json",
          f".factory/receipts/{rid}_RECEIPT.md")
        g("commit", "-qm", f"{rid}: land with uncommitted kernel dirt")
        sha = g("rev-parse", "HEAD").stdout.strip()
        q["rungs"][rid]["commit"] = sha
        qp.write_text(json.dumps(q, indent=2, ensure_ascii=False))
        g("add", ".factory/queue_state.json")
        g("commit", "-qm", f"{rid}: pin sha")
    elif mode == "kernel_edit_in_scope":
        (repo / "sub").mkdir(exist_ok=True)
        (repo / "sub" / "kern.py").write_text("# kernel in scope\\n")
        q["rungs"][rid].update(status="LANDED", claimed_by="fake-builder",
                               claimed_at="t", landed_at="t", commit="PENDING")
        qp.write_text(json.dumps(q, indent=2, ensure_ascii=False))
        (repo / f".factory/receipts/{rid}_RECEIPT.md").write_text(
            "# RECEIPT\\n\\n## What PASS proves\\nfake\\n"
            "## Commands and outputs\\n```bash\\n$ true\\n# ok\\n```\\n"
            "## What this does NOT prove\\n- in-scope kernel edit\\n")
        g("add", "sub/kern.py", ".factory/queue_state.json",
          f".factory/receipts/{rid}_RECEIPT.md")
        g("commit", "-qm", f"{rid}: in-scope kernel edit")
        sha = g("rev-parse", "HEAD").stdout.strip()
        q["rungs"][rid]["commit"] = sha
        qp.write_text(json.dumps(q, indent=2, ensure_ascii=False))
        g("add", ".factory/queue_state.json")
        g("commit", "-qm", f"{rid}: pin sha")
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
    # Because the post-check failed, tick.py demoted t1 from LANDED -> IN_PROGRESS
    # (preserving claimed_by) and recorded rung_demoted so the next tick retries t1
    # instead of stranding it as WAKE no_actionable_ticket.
    assert any("rung_demoted" in r and r["rung_demoted"]["rung"] == "t1" for r in recs)
    q = json.loads((repo / ".factory" / "queue_state.json").read_text())
    assert q["rungs"]["t1"]["status"] == "IN_PROGRESS"
    assert q["rungs"]["t1"]["claimed_by"] == "fake-builder"
    code2, msg2 = tick.run_tick(repo)
    assert code2 == tick.EXIT_VERIFY_RED
    assert "FAIL rung t1" in msg2


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
    # Rung was automatically demoted from LANDED -> IN_PROGRESS so next tick retries
    q = json.loads((repo / ".factory" / "queue_state.json").read_text())
    assert q["rungs"]["t1"]["status"] == "IN_PROGRESS"
    assert q["rungs"]["t1"]["claimed_by"] == "fake-builder"


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


def test_kernel_guard_ignores_pre_existing_kernel_dirt(repo):
    # co-tenant lanes: dirt under kernel_paths that PREDATES the tick (the
    # incumbent's ambient bookkeeping) must not be attributed to this tick
    setup_builder(repo, "land")
    cfg_p = repo / ".factory" / "config.json"
    cfg = json.loads(cfg_p.read_text())
    cfg["kernel_paths"] = ["app.py"]
    cfg_p.write_text(json.dumps(cfg, indent=2))
    (repo / "app.py").write_text("print('incumbent ambient dirt')\n")
    code1, msg1 = tick.run_tick(repo)
    assert code1 == 0, msg1
    assert "RECURSION GUARD" not in msg1
    # second tick: suppressed / no_actionable, still no guard problem
    code2, msg2 = tick.run_tick(repo)
    assert code2 == 0 and "RECURSION GUARD" not in msg2


def test_kernel_guard_flags_new_working_tree_kernel_dirt(repo):
    # a builder that dirties a kernel surface WITHOUT committing is still
    # caught — the working-tree DELTA (not absolute dirt) is the signal
    setup_builder(repo, "kernel_dirt")
    cfg_p = repo / ".factory" / "config.json"
    cfg = json.loads(cfg_p.read_text())
    cfg["kernel_paths"] = ["app.py"]
    cfg_p.write_text(json.dumps(cfg, indent=2))
    code1, msg1 = tick.run_tick(repo)
    assert code1 == tick.EXIT_BUILDER_FAILED, msg1
    assert "RECURSION GUARD" in msg1


def test_kernel_guard_ignores_out_of_scope_kernel_commit(repo):
    # co-tenant: a builder-commit touching a kernel path OUTSIDE the
    # lane's watch scope (incumbent bookkeeping landing mid-tick) must
    # not be attributed to this lane
    setup_builder(repo, "kernel_edit")
    cfg_p = repo / ".factory" / "config.json"
    cfg = json.loads(cfg_p.read_text())
    cfg["kernel_paths"] = ["app.py"]
    cfg["digest"] = {"watch_paths": ["sub"]}
    cfg_p.write_text(json.dumps(cfg, indent=2))
    (repo / "sub").mkdir(exist_ok=True)
    (repo / "sub" / "keep.txt").write_text("x\n")
    import subprocess as sp
    sp.run(["git", "-C", str(repo), "add", "sub/keep.txt"], check=True)
    sp.run(["git", "-C", str(repo), "commit", "-qm", "scope seed"],
           check=True)
    code1, msg1 = tick.run_tick(repo)
    assert code1 == 0, msg1
    assert "RECURSION GUARD" not in msg1


def test_kernel_guard_flags_in_scope_kernel_commit(repo):
    # pin: kernel commits INSIDE the lane's watch scope stay guarded
    setup_builder(repo, "kernel_edit_in_scope")
    cfg_p = repo / ".factory" / "config.json"
    cfg = json.loads(cfg_p.read_text())
    cfg["kernel_paths"] = ["sub/kern.py"]
    cfg["digest"] = {"watch_paths": ["sub"]}
    cfg_p.write_text(json.dumps(cfg, indent=2))
    code1, msg1 = tick.run_tick(repo)
    assert code1 == tick.EXIT_BUILDER_FAILED, msg1
    assert "RECURSION GUARD" in msg1


def test_recursion_guard_blocks_unauthorized_kernel_edit_and_allows_with_go(repo):
    from software_factory import gate
    setup_builder(repo, "kernel_edit")
    cfg_p = repo / ".factory" / "config.json"
    cfg = json.loads(cfg_p.read_text())
    cfg["kernel_paths"] = ["app.py"]
    cfg_p.write_text(json.dumps(cfg, indent=2))

    # 1. Without a fired kind="kernel_edit" GO, modifying app.py fails the tick
    # and demotes t1 from LANDED -> IN_PROGRESS automatically
    code, msg = tick.run_tick(repo)
    assert code == tick.EXIT_BUILDER_FAILED
    assert "RECURSION GUARD" in msg
    assert "app.py" in msg
    q = json.loads((repo / ".factory" / "queue_state.json").read_text())
    assert q["rungs"]["t1"]["status"] == "IN_PROGRESS"
    assert any("rung_demoted" in r for r in decision_log.read_all(repo))

    (repo / "app.py").write_text("print('v1')\n")
    git(repo, "add", "app.py", ".factory/queue_state.json")
    git(repo, "commit", "-qm", "revert unauthorized kernel edit")

    # 2. Operator arms and fires kind="kernel_edit" GO -> tick resumes t1 and succeeds
    gate.arm(repo, "kernel_edit", "GO kernel — app.py", ["true"])
    gcode, _ = gate.fire(repo, "GO kernel — app.py")
    assert gcode == 0
    code2, msg2 = tick.run_tick(repo)
    assert code2 == tick.EXIT_OK, msg2
    assert msg2.startswith("WAKE")


def test_prompt_template_contains_all_required_receipt_sections():
    from pathlib import Path
    from software_factory.common import REQUIRED_RECEIPT_SECTIONS
    from software_factory.templates import PROMPT_TEMPLATE, RECEIPT_TEMPLATE

    repo_root = Path(__file__).resolve().parents[1]
    file_prompt = (repo_root / "templates" / "PROMPT_TEMPLATE.md").read_text(encoding="utf-8")
    file_receipt = (repo_root / "templates" / "RECEIPT_TEMPLATE.md").read_text(encoding="utf-8")

    for sec in REQUIRED_RECEIPT_SECTIONS:
        assert sec in PROMPT_TEMPLATE, f"PROMPT_TEMPLATE missing required heading {sec!r}"
        assert sec in file_prompt, f"templates/PROMPT_TEMPLATE.md missing required heading {sec!r}"
        assert sec in RECEIPT_TEMPLATE, f"RECEIPT_TEMPLATE missing required heading {sec!r}"
        assert sec in file_receipt, f"templates/RECEIPT_TEMPLATE.md missing required heading {sec!r}"
