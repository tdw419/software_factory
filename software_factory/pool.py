"""factory pool — READ-ONLY multi-lane registry.

The factory's unit of parallelism is the lane, each in its own git worktree
or watch_paths-scoped subtree under its own .factory/tick.lock. Before
cross-lane conflict filtering (p2) or concurrent dispatch (p3), the operator
and scheduler need a deterministic view of the whole pool. This module:

- discovers lanes: `git worktree list --porcelain` order, then .factory/
  config.json `pool.lanes`, then caller-supplied extra paths — deduped by
  resolved path, kept only when .factory/queue_state.json is a regular file;
- inspects each lane without writing anything (queue_state.json, state.json,
  config.json reads + `git rev-parse` + observer.observe());
- prints stable lines (same discipline as the observer: no timestamps) with
  a trailing `lanes=N active=A parked=P` summary.

Zero writes, ever. Stdlib only.
"""

import json
from pathlib import Path

from . import observer, queue_state
from .common import git, load_json

#: A directory counts as a lane only if its queue is a REGULAR file
#: (symlinks to nowhere / directories named queue_state.json don't count).
_LANE_MARKER = (".factory", "queue_state.json")


def _is_lane(path: Path) -> bool:
    return (path.joinpath(*_LANE_MARKER)).is_file()


def discover(repo, extra_paths=()) -> list:
    """Return resolved lane directories in deterministic discovery order.

    Order: git worktrees (git's emitted order), then config pool.lanes,
    then extra_paths. Duplicates collapse on Path.resolve(); candidates
    without .factory/queue_state.json (e.g. bare product worktrees such as
    `main`) are skipped cleanly.
    """
    repo = Path(repo)
    candidates = []
    r = git(repo, "worktree", "list", "--porcelain")
    for ln in r.stdout.splitlines():
        if ln.startswith("worktree "):
            candidates.append(ln[len("worktree "):].strip())

    cfg_path = queue_state.factory_dir(repo) / "config.json"
    if cfg_path.is_file():
        try:
            pool_cfg = (load_json(cfg_path) or {}).get("pool") or {}
        except (json.JSONDecodeError, OSError):
            pool_cfg = {}
        for p in pool_cfg.get("lanes") or []:
            pp = Path(p)
            candidates.append(str(pp if pp.is_absolute() else repo / pp))

    for p in extra_paths or ():
        pp = Path(p)
        candidates.append(str(pp if pp.is_absolute() else repo / pp))

    seen = set()
    out = []
    for c in candidates:
        rp = Path(c).resolve()
        if rp in seen or not _is_lane(rp):
            continue
        seen.add(rp)
        out.append(rp)
    return out


def _load_json_or_none(path: Path):
    try:
        return load_json(path)
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def inspect_lane(lane_repo) -> dict:
    """Read-only per-lane readout. Never raises for lane faults."""
    lane_repo = Path(lane_repo)
    fdir = queue_state.factory_dir(lane_repo)

    q = _load_json_or_none(fdir / "queue_state.json")
    lane = "UNREADABLE"
    rungs = {}
    if isinstance(q, dict):
        if isinstance(q.get("lane"), str) and q["lane"]:
            lane = q["lane"]
        rungs = q.get("rungs") or {}

    r = git(lane_repo, "rev-parse", "--abbrev-ref", "HEAD")
    branch = r.stdout.strip() if r.returncode == 0 else "UNREADABLE"

    st = _load_json_or_none(fdir / "state.json")
    parked = bool(isinstance(st, dict) and st.get("parked"))
    statuses = [rg.get("status") for rg in rungs.values()
                if isinstance(rg, dict)]
    if parked:
        state = "PARKED"
    elif "IN_PROGRESS" in statuses:
        state = "IN_PROGRESS"
    elif "OPEN" in statuses:
        state = "OPEN"
    else:
        state = "IDLE"

    rid, _resuming = queue_state.next_actionable({"rungs": rungs})
    active_rung = rid if rid is not None else "none"

    # heartbeat: the observer's own readout on this lane, with the lane's
    # observer config engaged exactly as cmd_observe would engage it.
    obs = {}
    cfg = _load_json_or_none(fdir / "config.json")
    if isinstance(cfg, dict):
        obs = cfg.get("observer") or {}
    lines = observer.observe(
        lane_repo,
        stale_secs=obs.get("stale_secs", 5400),
        watch_rules=obs.get("watch_rules", ()),
        heartbeat_stale_after_min=obs.get("heartbeat_stale_after_min"))
    heartbeat = "NO_RUNS"
    for ln in lines:
        if ln.startswith("tick_heartbeat="):
            heartbeat = ln.split("=", 1)[1]
            break

    return {
        "lane": lane,
        "worktree": str(lane_repo.resolve()),
        "branch": branch,
        "state": state,
        "active_rung": active_rung,
        "heartbeat": heartbeat,
    }


def findings(repo, extra_paths=()) -> list:
    """Stable output lines: one per lane + the trailing summary. Read-only."""
    lines = []
    states = []
    for lp in discover(repo, extra_paths=extra_paths):
        info = inspect_lane(lp)
        states.append(info["state"])
        lines.append(
            f"lane: {info['lane']} state={info['state']}"
            f" active={info['active_rung']} heartbeat={info['heartbeat']}"
            f" branch={info['branch']} worktree={info['worktree']}")
    active = sum(1 for s in states if s in ("IN_PROGRESS", "OPEN"))
    parked = sum(1 for s in states if s == "PARKED")
    lines.append(f"lanes={len(states)} active={active} parked={parked}")
    return lines


def run(repo, extra_paths=()) -> list:
    lines = findings(repo, extra_paths=extra_paths)
    print("\n".join(lines))
    return lines
