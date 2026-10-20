"""p1 — factory pool: read-only multi-lane registry (discovery + readout)."""

import json
import os
import subprocess
from pathlib import Path

from conftest import git, init_lane

from software_factory import pool
from software_factory.cli import main


# ---------- helpers ----------

def _worktree_lane(repo, name):
    """A linked git worktree with a real .factory (factory init inside it)."""
    wt = repo.parent / name
    git(repo, "worktree", "add", "-q", str(wt), "-b", name)
    assert main(["--repo", str(wt), "init", "--lane", name]) == 0
    return wt


def _bare_worktree(repo, name):
    """A linked worktree with NO .factory (a plain product worktree)."""
    wt = repo.parent / name
    git(repo, "worktree", "add", "-q", str(wt), "-b", name)
    return wt


def _plain_lane(repo, name, queue=None, state=None, observer_cfg=None):
    """A plain directory carrying .factory/ files but not a git worktree."""
    d = repo.parent / name
    (d / ".factory").mkdir(parents=True)
    q = queue if queue is not None else {"lane": name, "rules": ["r"], "rungs": {}}
    (d / ".factory" / "queue_state.json").write_text(json.dumps(q))
    if state is not None:
        (d / ".factory" / "state.json").write_text(json.dumps(state))
    cfg = {"observer": {"stale_secs": 5400}}
    if observer_cfg is not None:
        cfg["observer"] = observer_cfg
    (d / ".factory" / "config.json").write_text(json.dumps(cfg))
    return d


def _rung(rid, status, claimed_by=None):
    r = {"status": status, "title": rid, "ticket": f"{rid}.md",
         "receipt": "", "claimed_by": claimed_by, "opened": "2026-01-01T00:00:00+00:00",
         "claimed_at": None, "landed_at": None, "commit": None}
    return {rid: r}


def _snapshot(root):
    """(path, type, mtime_ns, size) for every file AND directory under root."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for n in dirnames + filenames:
            p = Path(dirpath) / n
            st = p.stat()
            out[str(p)] = (st.st_mtime_ns, st.st_size)
    return out


# ---------- 1. worktree discovery ----------

def test_discover_worktrees_skip_non_lanes(repo):
    init_lane(repo)
    lane2 = _worktree_lane(repo, "lane2")
    bare = _bare_worktree(repo, "barewt")  # product worktree, no .factory
    lanes = pool.discover(repo)
    assert lanes[0] == repo.resolve()          # git's emitted order: main first
    assert lane2.resolve() in lanes
    assert bare.resolve() not in lanes
    assert all((l / ".factory" / "queue_state.json").is_file() for l in lanes)


def test_discover_config_lanes_and_extra_paths_dedup(repo):
    init_lane(repo)
    lane3 = _plain_lane(repo, "lane3")
    cfgp = repo / ".factory" / "config.json"
    cfg = json.loads(cfgp.read_text())
    cfg["pool"] = {"lanes": ["../lane3"]}      # relative: resolved against repo
    cfgp.write_text(json.dumps(cfg))
    lanes = pool.discover(repo, extra_paths=[
        str(lane3),                            # absolute dup of the config entry
        os.path.join("..", "proj", "lane3"),   # ..-laden dup, same resolve()
    ])
    assert lanes == [repo.resolve(), lane3.resolve()]


# ---------- 2. per-lane readout ----------

def test_state_classification_and_active_rung(repo):
    init_lane(repo)
    idle = _plain_lane(repo, "idle")
    open_lane = _plain_lane(repo, "openl", queue={
        "lane": "openl", "rules": [], "rungs": {**_rung("p9", "OPEN"),
                                                **_rung("p8", "LANDED")}})
    inprog = _plain_lane(repo, "inprogl", queue={
        "lane": "inprogl", "rules": [], "rungs": {**_rung("p7", "OPEN"),
                                                  **_rung("p6", "IN_PROGRESS",
                                                          claimed_by="hermes-cli")}})
    parked = _plain_lane(repo, "parkedl", queue={
        "lane": "parkedl", "rules": [], "rungs": _rung("p5", "OPEN")},
        state={"parked": True})
    corrupt = repo.parent / "corruptl"
    (corrupt / ".factory").mkdir(parents=True)
    (corrupt / ".factory" / "queue_state.json").write_text("{not json")

    lanes = {Path(p).name: pool.inspect_lane(p)
             for p in pool.discover(repo, extra_paths=[idle, open_lane, inprog,
                                                       parked, corrupt])}
    assert lanes["idle"]["state"] == "IDLE"
    assert lanes["idle"]["active_rung"] == "none"
    assert lanes["openl"]["state"] == "OPEN"
    assert lanes["openl"]["active_rung"] == "p9"
    assert lanes["inprogl"]["state"] == "IN_PROGRESS"
    assert lanes["inprogl"]["active_rung"] == "p6"   # claimed IN_PROGRESS wins
    assert lanes["parkedl"]["state"] == "PARKED"     # parked beats OPEN
    assert lanes["corruptl"]["lane"] == "UNREADABLE"
    assert lanes["corruptl"]["state"] == "IDLE"      # no readable rungs -> IDLE
    for name, info in lanes.items():
        assert info["worktree"] == str((repo.parent / name).resolve())
        assert set(info) == {"lane", "worktree", "branch", "state",
                             "active_rung", "heartbeat"}


def test_branch_readout(repo):
    init_lane(repo)
    lane2 = _worktree_lane(repo, "lane2")
    info = pool.inspect_lane(lane2)
    assert info["branch"] == "lane2"


def test_heartbeat_propagation(repo):
    stale_lane = _plain_lane(
        repo, "stalel",
        observer_cfg={"stale_secs": 5400, "heartbeat_stale_after_min": 10},
        state={"parked": False, "last_tick_ts": "2020-01-01T00:00:00+00:00"})
    runs = stale_lane / ".factory" / "runs"
    runs.mkdir()
    f = runs / "run1.json"
    f.write_text("{}")
    old = 1_000_000_000.0  # ~2001, far beyond the 10-minute threshold
    os.utime(f, (old, old))
    no_cfg = _plain_lane(repo, "nocfgl", observer_cfg={"stale_secs": 5400})
    (no_cfg / ".factory" / "runs").mkdir()

    stale_info = pool.inspect_lane(stale_lane)
    no_cfg_info = pool.inspect_lane(no_cfg)
    assert stale_info["heartbeat"] == "STALE"
    # no heartbeat_stale_after_min in config -> legacy vocabulary
    assert no_cfg_info["heartbeat"] == "NO_RUNS"
    # and it matches observer.observe() on the same lane, byte for byte
    from software_factory import observer
    for lane, info in ((stale_lane, stale_info), (no_cfg, no_cfg_info)):
        lines = observer.observe(lane, stale_secs=5400,
                                 heartbeat_stale_after_min=None
                                 if lane == no_cfg else 10)
        hb = [l.split("=", 1)[1] for l in lines if l.startswith("tick_heartbeat=")]
        assert info["heartbeat"] == hb[0]


# ---------- 3. stable output, summary, zero-write, CLI ----------

def test_findings_lines_and_summary(repo):
    init_lane(repo)
    _plain_lane(repo, "lane3", queue={
        "lane": "lane3", "rules": [], "rungs": _rung("q1", "OPEN")})
    lines = pool.findings(repo)
    lane_lines = [l for l in lines if l.startswith("lane: ")]
    assert len(lane_lines) == 2
    for l in lane_lines:
        # lane: <lane> state=<s> active=<a> heartbeat=<h> branch=<b> worktree=<w>
        head, rest = l.split(" state=", 1)
        assert head.startswith("lane: ")
        for field in ("active=", "heartbeat=", "branch=", "worktree="):
            assert f" {field}" in l
    assert lines[-1] == "lanes=2 active=1 parked=0"


def test_zero_write_and_cli(repo, capsys):
    init_lane(repo)
    lane3 = _plain_lane(repo, "lane3", queue={
        "lane": "lane3", "rules": [], "rungs": _rung("q1", "OPEN")},
        state={"parked": True})
    before = _snapshot(repo.parent)
    assert main(["--repo", str(repo), "pool"]) == 0
    assert main(["--repo", str(repo), "pool", "--paths", f"{lane3},{lane3}"]) == 0
    assert _snapshot(repo.parent) == before      # ZERO writes, incl. mtimes
    out = capsys.readouterr().out
    body = [l for l in out.splitlines() if l.startswith("lane: ")]
    assert len(body) == 4                        # 2 lanes x 2 invocations
    assert any("state=PARKED" in l for l in body)
    summaries = [l for l in out.splitlines() if l.startswith("lanes=")]
    assert summaries[-1] == "lanes=2 active=0 parked=1"


def test_pool_via_python_dash_m(repo, capsys):
    init_lane(repo)
    r = subprocess.run(
        ["/usr/bin/python3.12", "-m", "software_factory.cli",
         "--repo", str(repo), "pool"],
        capture_output=True, text=True, cwd=str(repo.parent))
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("lane: ")
    assert "lanes=" in r.stdout
