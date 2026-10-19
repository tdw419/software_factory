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
    lines = _lines(repo, cfg={"thresholds": {"failure_class": 1}})
    sigs = {ln.split(" ", 2)[1].rsplit(" ", 2)[0]
            for ln in _finding_lines(lines) if ln.startswith("finding: failure_class:")}
    assert sigs == {
        "failure_class:recursion_guard", "failure_class:builder_exit",
        "failure_class:verify_timeout", "failure_class:wake_discipline",
        "failure_class:queue_discipline",
    }
    # 5 failure classes + stall (5-trailing-failure streak >= default 3)
    assert lines[-1] == "findings=6"


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
    arch = repo / ".factory" / "decision_log.archive.jsonl"
    arch.write_text(raw + "\n", encoding="utf-8")
    # threshold 1: if the duplicate were counted twice, count would be 2
    lines = _lines(repo, cfg={"thresholds": {"failure_class": 1}})
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
    lines = _lines(repo)
    # the failure_class count survives the reset (history), the stall streak
    # does not (a successful tick happened after the failures)
    assert lines == [
        "finding: failure_class:builder_exit count=3 evidence="
        + lines[0].split("evidence=")[1],
        "findings=1",
    ]
    assert not any(ln.startswith("finding: stall ") for ln in lines)


def test_parked_finding_from_state(repo):
    init_lane(repo)
    (repo / ".factory" / "state.json").write_text(json.dumps(
        {"parked": True, "consecutive_failures": 3}))
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


# ---------- s2: builder_timeout bucket, CLI --covers, diagnose --draft ----------

def test_builder_timeout_classifies_builder_timeout():
    # s1 gap: "builder TIMEOUT after <N>s" fell through to the first-word
    # fallback and classified as failure_class:builder
    assert diagnose.classify_problem("builder TIMEOUT after 1500s") == "builder_timeout"
    assert diagnose.failure_classes("builder TIMEOUT after 1500s") == ["builder_timeout"]
    # the pre-existing buckets keep their classifications
    assert diagnose.classify_problem("builder exit 1") == "builder_exit"
    assert diagnose.classify_problem("verify gate TIMEOUT (rule 8)") == "verify_timeout"


def test_ticket_add_and_set_covers(repo):
    init_lane(repo)
    t = repo / ".factory" / "tickets" / "t1.md"
    t.write_text("# T1\n\n## Goal\nx\n\n## Stages\ny\n\n## Constraints\nz\n")
    rc = main(["--repo", str(repo), "ticket", "add", "--id", "t1",
               "--title", "fix receipts", "--ticket", ".factory/tickets/t1.md",
               "--covers", "failure_class:receipt,violation:kernel_edit"])
    assert rc == 0
    q = queue_state.load(repo)
    assert q["rungs"]["t1"]["covers"] == [
        "failure_class:receipt", "violation:kernel_edit"]
    # set: comma-separated, empty items stripped
    rc = main(["--repo", str(repo), "ticket", "set", "t1",
               "--covers", "failure_class:receipt,,stall"])
    assert rc == 0
    q = queue_state.load(repo)
    assert q["rungs"]["t1"]["covers"] == ["failure_class:receipt", "stall"]


def test_diagnose_draft_creates_self_draft_rung(repo):
    init_lane(repo)
    cfg_path = repo / ".factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["digest"]["ladder"] = {"path": "ROADMAP.md", "line_prefix": "- Rung"}
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    (repo / "ROADMAP.md").write_text("# Roadmap\n\n- Rung x [LANDED]: prior\n",
                                     encoding="utf-8")
    ts_a = _append(repo, **_tick_failed(problem="builder TIMEOUT after 1500s",
                                        transient=True))
    ts_b = _append(repo, **_tick_failed(problem="builder TIMEOUT after 1500s",
                                        transient=True))
    lines = diagnose.run(repo, cfg={"max_active_drafts": 2}, draft=True)

    q = queue_state.load(repo)
    self_rungs = {rid: r for rid, r in q["rungs"].items()
                  if r.get("origin") == "self"}
    assert len(self_rungs) == 1
    rid, r = next(iter(self_rungs.items()))
    assert r["status"] == "DRAFT"
    assert r["covers"] == ["failure_class:builder_timeout"]
    ticket_rel = r["ticket"]
    text = (repo / ticket_rel).read_text(encoding="utf-8")
    for sec in ("## Goal", "## Stages", "## Constraints",
                "## What this does NOT prove"):
        assert sec in text, f"missing {sec}"
    assert "kernel_paths" in text  # explicit no-kernel-edit constraint
    assert "failure_class:builder_timeout" in text  # cites the signature
    assert "count=2" in text or "count: 2" in text  # cites the count
    assert ts_a in text and ts_b in text  # cites the exact evidence ts
    assert queue_state.validate_ticket(repo / ticket_rel) == []

    # ladder sync so observer keeps reporting ladder_drift=none
    ladder = (repo / "ROADMAP.md").read_text(encoding="utf-8")
    assert f"- Rung {rid} [DRAFT]:" in ladder
    assert ticket_rel in ladder

    # provenance in decision_log
    dd = [x["diagnose_drafted"] for x in decision_log.read_all(repo)
          if "diagnose_drafted" in x]
    assert len(dd) == 1
    assert dd[0]["rung"] == rid
    assert dd[0]["signature"] == "failure_class:builder_timeout"
    assert dd[0]["count"] == 2
    assert dd[0]["evidence"] == [ts_a, ts_b]

    # stdout: drafted line BEFORE findings=<n>; findings recomputed to 0
    assert lines[0] == (f"drafted: {rid} covers=failure_class:builder_timeout "
                        f"ticket={ticket_rel}")
    assert lines[-1] == "findings=0"

    # idempotence: immediate re-run (bare or --draft) sees the signature covered
    assert diagnose.run(repo) == ["findings=0"]
    assert diagnose.run(repo, draft=True) == ["findings=0"]
    q2 = queue_state.load(repo)
    assert sum(1 for x in q2["rungs"].values() if x.get("origin") == "self") == 1


def test_diagnose_draft_respects_active_cap(repo):
    init_lane(repo)
    for i in range(2):  # default max_active_drafts=2, cfg absent
        q = queue_state.load(repo)
        queue_state.register_rung(q, f"pre{i}", "prior self draft",
                                  ".factory/tickets/pre.md", status="DRAFT")
        q["rungs"][f"pre{i}"]["origin"] = "self"
        queue_state.save(repo, q)
    _append(repo, **_tick_failed(problem="receipt incomplete (x)"))
    _append(repo, **_tick_failed(problem="receipt incomplete (x)"))
    lines = diagnose.run(repo, draft=True)
    assert lines[0] == "draft_skipped=cap_reached"
    assert lines[-1] == "findings=1"  # nothing drafted -> finding still stands
    q = queue_state.load(repo)
    assert not [rid for rid in q["rungs"] if rid.startswith("auto_")]


def test_bare_diagnose_performs_zero_writes(repo):
    init_lane(repo)
    _append(repo, **_tick_failed(problem="builder TIMEOUT after 900s",
                                 transient=True))
    _append(repo, **_tick_failed(problem="builder TIMEOUT after 900s",
                                 transient=True))
    before = {str(p.relative_to(repo)): p.read_bytes()
              for p in sorted((repo / ".factory").rglob("*")) if p.is_file()}
    before["ROADMAP.md"] = b""
    lines = diagnose.run(repo)
    assert lines[-1] == "findings=1"
    after = {str(p.relative_to(repo)): p.read_bytes()
             for p in sorted((repo / ".factory").rglob("*")) if p.is_file()}
    after["ROADMAP.md"] = b""
    assert before == after
    assert not (repo / "ROADMAP.md").exists()


def test_cli_diagnose_draft(repo, capsys):
    init_lane(repo)
    _append(repo, **_tick_failed(problem="builder TIMEOUT after 1500s",
                                 transient=True))
    _append(repo, **_tick_failed(problem="builder TIMEOUT after 1500s",
                                 transient=True))
    rc = main(["--repo", str(repo), "diagnose", "--draft"])
    out = capsys.readouterr().out
    assert rc == 0
    out_lines = out.splitlines()
    drafted_idx = [i for i, ln in enumerate(out_lines)
                   if ln.startswith("drafted: auto_")]
    assert drafted_idx, out
    assert "findings=0" in out_lines
    assert drafted_idx[0] < out_lines.index("findings=0")  # drafted BEFORE findings
