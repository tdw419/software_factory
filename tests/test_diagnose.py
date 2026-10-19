"""s1 — factory diagnose: read-only self-diagnosis counter over the decision log."""

import json

from conftest import init_lane

from software_factory import decision_log, diagnose, queue_state
from software_factory.cli import main


def _append(repo, **rec):
    r = decision_log.append(repo, rec)
    return r["ts"]


def _tick_failed(rung="t1", problem="receipt incomplete (missing sections)", **kw):
    body = {"rung": rung, "problem": problem, "verify": "pass",
            "transient": False, "head_before": "aa", "head_after": "bb"}
    body.update(kw)
    return {"actor": "factory-tick", "tick_failed": body}


def _lines(repo, cfg=None):
    return diagnose.run(repo, cfg=cfg)


def _finding_lines(lines):
    return [ln for ln in lines if ln.startswith("finding: ")]


def test_no_findings_on_quiet_log(repo):
    init_lane(repo)
    assert _lines(repo) == ["findings=0"]


def test_failure_class_fires_at_default_threshold(repo):
    init_lane(repo)
    ts_a = _append(repo, **_tick_failed(problem="receipt incomplete (x)"))
    ts_b = _append(repo, **_tick_failed(problem="receipt missing: .factory/receipts/t1_RECEIPT.md"))
    lines = _lines(repo)
    assert lines == [
        f"finding: failure_class:receipt count=2 evidence={ts_a},{ts_b}",
        "findings=1",
    ]


def test_below_threshold_is_silent(repo):
    init_lane(repo)
    _append(repo, **_tick_failed(problem="verify gate RED"))
    assert _lines(repo) == ["findings=0"]


def test_failure_class_patterns_are_deterministic(repo):
    init_lane(repo)
    for problem in ("RECURSION GUARD: kernel surfaces modified (tick.py)",
                    "builder exit 1", "verify gate TIMEOUT (wedge risk — rule 8)",
                    "WAKE DISCIPLINE: builder returned 0 but committed nothing",
                    "QUEUE DISCIPLINE: rung left IN_PROGRESS with no claimed_by"):
        _append(repo, **_tick_failed(problem=problem))
    lines = _lines(repo)
    sigs = {ln.split(" ", 2)[1].rsplit(" ", 2)[0]
            for ln in _finding_lines(lines)}
    assert sigs == {
        "failure_class:recursion_guard", "failure_class:builder_exit",
        "failure_class:verify_timeout", "failure_class:wake_discipline",
        "failure_class:queue_discipline",
    }
    assert lines[-1] == "findings=5"


def test_archive_evidence_survives_compaction(repo):
    init_lane(repo)
    ts_a = _append(repo, **_tick_failed(problem="receipt incomplete (x)"))
    code, summary = decision_log.compact(repo, keep=1)
    assert code == 0, summary
    ts_b = _append(repo, **_tick_failed(problem="receipt incomplete (x)"))
    lines = _lines(repo)
    assert lines == [
        f"finding: failure_class:receipt count=2 evidence={ts_a},{ts_b}",
        "findings=1",
    ]


def test_duplicate_ts_counts_once(repo):
    # crash-window duplication: the same record briefly in archive AND live
    init_lane(repo)
    ts = _append(repo, **_tick_failed(problem="receipt incomplete (x)"))
    raw = (repo / ".factory" / "decision_log.jsonl").read_text(
        encoding="utf-8").splitlines()[-1]
    with open(repo / ".factory" / ".archive_seed", "w") as f:
        f.write(raw + "\n")
    arch = repo / ".factory" / "decision_log.archive.jsonl"
    arch.write_text(raw + "\n", encoding="utf-8")
    (repo / ".factory" / ".archive_seed").unlink()
    lines = _lines(repo)
    assert lines == [
        f"finding: failure_class:receipt count=1 evidence={ts}",
        "findings=1",
    ]


def test_gate_refused_is_violation(repo):
    init_lane(repo)
    ts = _append(repo, actor="factory-tick",
                 gate_refused={"kind": "kernel_edit", "reason": "phrase_mismatch"})
    lines = _lines(repo)
    assert lines == [
        f"finding: violation:kernel_edit count=1 evidence={ts}",
        "findings=1",
    ]


def test_rung_demoted_recursion_guard_is_kernel_edit_violation(repo):
    init_lane(repo)
    ts = _append(repo, actor="factory-tick", rung_demoted={
        "rung": "t1", "from": "LANDED", "to": "IN_PROGRESS",
        "reason": "RECURSION GUARD: kernel surfaces modified (tick.py) without "
                  "an un-aborted kind='kernel_edit' GO in decision_log"})
    lines = _lines(repo)
    assert lines == [
        f"finding: violation:kernel_edit count=1 evidence={ts}",
        "findings=1",
    ]


def test_open_rung_covering_signature_skips(repo):
    init_lane(repo)
    _append(repo, **_tick_failed(problem="receipt incomplete (x)"))
    _append(repo, **_tick_failed(problem="receipt incomplete (x)"))
    q = queue_state.load(repo)
    queue_state.register_rung(q, "t1", "fix receipts", ".factory/tickets/t1.md")
    q["rungs"]["t1"].update(status="OPEN", covers=["failure_class:receipt"])
    queue_state.save(repo, q)
    assert _lines(repo) == ["findings=0"]


def test_landed_rung_recurrence_refires(repo):
    init_lane(repo)
    ts_a = _append(repo, **_tick_failed(problem="receipt incomplete (x)"))
    _append(repo, **_tick_failed(problem="receipt incomplete (x)"))
    q = queue_state.load(repo)
    queue_state.register_rung(q, "t1", "fix receipts", ".factory/tickets/t1.md")
    # fix purportedly landed BEFORE the newest evidence -> recurrence re-fires
    q["rungs"]["t1"].update(status="LANDED", covers=["failure_class:receipt"],
                            landed_at="2000-01-01T00:00:00.000000+00:00")
    queue_state.save(repo, q)
    lines = _lines(repo)
    # recurrence: the newest evidence postdates the purported fix, so it fires
    assert lines[0].startswith("finding: failure_class:receipt count=2 ")
    assert f"evidence={ts_a}," in lines[0]
    assert ts_a != lines[0].split(",")[1]  # second evidence ts is the newer record
    assert lines[-1] == "findings=1"


def test_landed_rung_landed_after_evidence_skips(repo):
    init_lane(repo)
    ts = _append(repo, **_tick_failed(problem="receipt incomplete (x)"))
    _append(repo, **_tick_failed(problem="receipt incomplete (x)"))
    q = queue_state.load(repo)
    queue_state.register_rung(q, "t1", "fix receipts", ".factory/tickets/t1.md")
    q["rungs"]["t1"].update(status="LANDED", covers=["failure_class:receipt"],
                            landed_at="2099-01-01T00:00:00.000000+00:00")
    queue_state.save(repo, q)
    assert _lines(repo) == ["findings=0"]


def test_stall_streak_of_consecutive_failures(repo):
    init_lane(repo)
    tss = [_append(repo, **_tick_failed(problem="builder exit 1")) for _ in range(3)]
    lines = _lines(repo)
    assert f"finding: stall count=3 evidence={','.join(tss)}" in lines
    assert lines[-1] == "findings=2"  # stall + failure_class:builder_exit


def test_stall_resets_on_successful_tick(repo):
    init_lane(repo)
    for _ in range(3):
        _append(repo, **_tick_failed(problem="builder exit 1"))
    _append(repo, actor="factory-tick",
            tick={"rung": "t1", "wake": "change", "resuming": False,
                  "builder_exit": 0, "verify": "pass", "head_before": "aa",
                  "head_after": "bb", "receipt": ".factory/receipts/t1.md",
                  "rung_status": "LANDED"})
    assert _lines(repo) == ["findings=0"]


def test_parked_finding_from_state(repo):
    init_lane(repo)
    st = json.loads((repo / ".factory" / "state.json").read_text())
    st["parked"] = True
    st["consecutive_failures"] = 3
    (repo / ".factory" / "state.json").write_text(json.dumps(st))
    lines = _lines(repo)
    assert "finding: parked count=1 evidence=" in lines
    assert lines[-1] == "findings=1"


def test_config_thresholds_respected(repo):
    init_lane(repo)
    _append(repo, **_tick_failed(problem="receipt incomplete (x)"))
    lines = _lines(repo, cfg={"thresholds": {"failure_class": 1}})
    assert len(_finding_lines(lines)) == 1
    assert lines[-1] == "findings=1"


def test_config_window_limits_evidence(repo):
    init_lane(repo)
    ts_a = _append(repo, **_tick_failed(problem="receipt incomplete (x)"))
    ts_b = _append(repo, **_tick_failed(problem="receipt incomplete (x)"))
    lines = _lines(repo, cfg={"window": 1, "thresholds": {"failure_class": 1}})
    assert lines == [
        f"finding: failure_class:receipt count=1 evidence={ts_b}",
        "findings=1",
    ]
    assert ts_a not in lines[0]


def test_absent_config_is_byte_stable(repo):
    init_lane(repo)
    (repo / ".factory" / "config.json").unlink()
    a = _lines(repo)
    b = _lines(repo)
    assert a == b
    assert a == ["findings=0"]


def test_cli_diagnose(repo, capsys):
    init_lane(repo)
    rc = main(["--repo", str(repo), "diagnose"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.endswith("findings=0\n")
