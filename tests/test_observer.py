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
    (repo / ".factory" / "receipts" / "t1_RECEIPT.md").write_text(
        "# RECEIPT\n\n## What PASS proves\nok\n\n"
        "## Commands and outputs\n```bash\n$ true\n# ok\n```\n\n"
        "## What this does NOT prove\n- limit\n"
    )
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


def test_empty_or_unset_receipt_path_detected_as_missing(repo):
    healthy_lane(repo)
    q = queue_state.load(repo)
    q["rungs"]["t1"]["receipt"] = ""
    queue_state.save(repo, q)
    d = dict(ln.split("=", 1) for ln in observer.observe(repo))
    assert d["receipts_missing"] == "t1"


def test_observer_allowlist_respects_path_boundary(repo):
    healthy_lane(repo)
    allow = [".factory/runs/"]
    # Allowed churn directory stays CLEAN
    (repo / ".factory" / "runs").mkdir(exist_ok=True)
    (repo / ".factory" / "runs" / "m1").write_text("ok\n")
    d = dict(ln.split("=", 1) for ln in observer.observe(repo, churn_allowlist=allow))
    assert d["tree"] == "CLEAN"
    # Sibling prefix outside allowlist is flagged DIRTY
    (repo / ".factory" / "runs_backup").mkdir(exist_ok=True)
    (repo / ".factory" / "runs_backup" / "x").write_text("dirty\n")
    d2 = dict(ln.split("=", 1) for ln in observer.observe(repo, churn_allowlist=allow))
    assert d2["tree"].startswith("DIRTY")


def test_incomplete_receipt_detected_by_observer(repo):
    healthy_lane(repo)
    (repo / ".factory" / "receipts" / "t1_RECEIPT.md").write_text("# RECEIPT\nsloppy prose only\n")
    d = dict(ln.split("=", 1) for ln in observer.observe(repo))
    assert d["receipts_missing"] == "none"
    assert d["receipts_incomplete"] == "t1"


def test_observer_and_digest_share_config_allowlist_resolution(repo):
    from software_factory import digest
    healthy_lane(repo)
    cfg_path = repo / ".factory" / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["digest"]["churn_allowlist"].append("scratch/")
    cfg_path.write_text(json.dumps(cfg, indent=2))
    git(repo, "add", ".factory/config.json")
    git(repo, "commit", "-qm", "allowlist scratch/")

    (repo / "scratch").mkdir()
    (repo / "scratch" / "temp.log").write_text("churn\n")

    # Neither caller passes allowlist explicitly; both resolve from config.json
    obs_d = dict(ln.split("=", 1) for ln in observer.observe(repo))
    fp = digest.compute(repo)
    assert obs_d["tree"] == "CLEAN"
    assert fp.parts["TREE"] == "CLEAN"


def test_observer_surfaces_armed_gate(repo):
    from software_factory import gate
    healthy_lane(repo)
    gate.arm(repo, "demo", "GO demo", ["true"])
    lines = observer.observe(repo)
    d = dict(ln.split("=", 1) for ln in lines)
    assert d["gate_armed"] == "demo"
    assert d["gate_armed_stale"] == "no"
    gate.disarm(repo)
    lines = observer.observe(repo)
    assert not any(ln.startswith("gate_armed") for ln in lines)


def test_observer_flags_stale_and_unreadable_gate(repo):
    healthy_lane(repo)
    pg = repo / ".factory" / "pending_gate.json"
    pg.write_text(json.dumps({"kind": "demo", "armed_ts": "2020-01-01T00:00:00+00:00"}))
    d = dict(ln.split("=", 1) for ln in observer.observe(repo))
    assert d["gate_armed_stale"] == "yes"
    pg.write_text("{not json")
    d = dict(ln.split("=", 1) for ln in observer.observe(repo))
    assert d["gate_armed"] == "UNREADABLE"


def test_observer_surfaces_kernel_guard_violation_and_authorization(repo):
    from software_factory import gate
    healthy_lane(repo)
    cfg_p = repo / ".factory" / "config.json"
    cfg = json.loads(cfg_p.read_text())
    cfg["kernel_paths"] = ["app.py"]
    cfg_p.write_text(json.dumps(cfg, indent=2))

    # Clean untouched kernel -> OK
    d0 = dict(ln.split("=", 1) for ln in observer.observe(repo))
    assert d0["kernel_guard"] == "OK"

    # Dirty kernel without GO -> VIOLATION(app.py)
    (repo / "app.py").write_text("print('unauthorized')\n")
    d1 = dict(ln.split("=", 1) for ln in observer.observe(repo))
    assert d1["kernel_guard"] == "VIOLATION(app.py)"

    # Fired kernel_edit GO -> AUTHORIZED(app.py)
    gate.arm(repo, "kernel_edit", "GO kernel — app.py", ["true"])
    gate.fire(repo, "GO kernel — app.py")
    d2 = dict(ln.split("=", 1) for ln in observer.observe(repo))
    assert d2["kernel_guard"] == "AUTHORIZED(app.py)"
