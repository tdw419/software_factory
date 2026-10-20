"""factory pool — multi-lane registry + conflict-aware dispatch (p3).

The factory's unit of parallelism is the lane, each in its own git worktree
or watch_paths-scoped subtree under its own .factory/tick.lock. This module:

- discovers lanes: `git worktree list --porcelain` order, then .factory/
  config.json `pool.lanes`, then caller-supplied extra paths — deduped by
  resolved path, kept only when .factory/queue_state.json is a regular file;
- inspects each lane (queue_state.json, state.json, config.json reads +
  `git rev-parse` + observer.observe());
- prints stable lines (same discipline as the observer: no timestamps) with
  a trailing `lanes=N active=A parked=P` summary;
- plans (plan_dispatch) and runs (dispatch) conflict-free lane ticks across
  the pool: a lane whose head OPEN rung overlaps another active lane's
  declared `files` is skipped (tick.py is kernel-frozen and would run the
  conflicting head rung), while claimed IN_PROGRESS rungs are resumed
  regardless. Dispatch runs tick.run_tick concurrently on a ThreadPoolExecutor
  and relies on each lane's own .factory/tick.lock for mutual exclusion.

Stdlib only.
"""

import concurrent.futures
import json
from pathlib import Path

from . import observer, queue_state, tick
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


# ---------- p3: conflict-aware multi-lane parallel dispatch ----------

def _lane_q(lane_repo):
    return _load_json_or_none(queue_state.queue_path(lane_repo))


def _lane_name(q, lane_repo) -> str:
    if isinstance(q, dict) and isinstance(q.get("lane"), str) and q["lane"]:
        return q["lane"]
    return str(lane_repo)


def plan_dispatch(repo, extra_paths=(), max_parallel=None) -> tuple:
    """Select conflict-free rungs across the pool. Read-only.

    Returns (selected, skipped): `selected` is a list of dicts
    {lane, repo, rung, resuming, files} in pool order; `skipped` is a list
    of `dispatch_skipped: <lane> reason=<why>` lines in pool order.

    in_flight_files is seeded with the union of every lane's IN_PROGRESS
    `files`, then extended as each lane is selected, so a single pass can
    never double-book an overlapping touch surface. A claimed IN_PROGRESS
    rung is resumed regardless of conflicts (it already owns its work). A
    lane whose HEAD OPEN rung conflicts is skipped entirely: tick.py is
    kernel-frozen and calls next_actionable(q) without in_flight_files, so
    launching a tick there would run the conflicting rung.
    """
    lanes = discover(repo, extra_paths=extra_paths)
    selected = []
    skipped = []

    in_flight = []
    for lp in lanes:
        q = _lane_q(lp)
        if not isinstance(q, dict):
            continue
        for r in (q.get("rungs") or {}).values():
            if isinstance(r, dict) and r.get("status") == "IN_PROGRESS":
                in_flight.extend(r.get("files") or [])

    for lp in lanes:
        q = _lane_q(lp)
        name = _lane_name(q, lp)
        if not isinstance(q, dict):
            skipped.append(f"dispatch_skipped: {name} reason=unreadable")
            continue
        st = _load_json_or_none(queue_state.factory_dir(lp) / "state.json")
        if isinstance(st, dict) and st.get("parked"):
            skipped.append(f"dispatch_skipped: {name} reason=parked")
            continue

        rungs = q.get("rungs") or {}
        resume_rid = next(
            (rid for rid, r in rungs.items()
             if isinstance(r, dict) and r.get("status") == "IN_PROGRESS"
             and r.get("claimed_by")),
            None)
        open_rids = [rid for rid, r in rungs.items()
                     if isinstance(r, dict) and r.get("status") == "OPEN"]
        if resume_rid is not None:
            rid, resuming = resume_rid, True
        elif open_rids:
            rid, resuming = queue_state.next_actionable(
                q, in_flight_files=in_flight)
            if rid is None:
                # every OPEN rung on this lane overlaps in-flight work
                skipped.append(
                    f"dispatch_skipped: {name} reason=file_conflict")
                continue
            if rid != open_rids[0]:
                # head OPEN rung conflicts — run_tick (kernel-frozen) would
                # still pick it; the lane waits until the conflict clears
                skipped.append(
                    f"dispatch_skipped: {name} reason=file_conflict")
                continue
        else:
            continue  # idle lane: nothing OPEN, nothing claimed — silent

        if max_parallel is not None and len(selected) >= max_parallel:
            skipped.append(
                f"dispatch_skipped: {name} reason=max_parallel")
            continue
        files = list((rungs[rid].get("files") or []))
        in_flight.extend(files)  # same-pass lanes cannot double-book these
        selected.append({"lane": name, "repo": lp, "rung": rid,
                         "resuming": resuming, "files": files})
    return selected, skipped


def dispatch(repo, extra_paths=(), dry_run=False, max_parallel=None,
             builder_timeout=None, verify_timeout=None) -> int:
    """Plan, then run the selected lane ticks concurrently. Returns exit code.

    dry_run prints `would_dispatch:` lines + `dispatched=0` and performs zero
    writes. A real run dispatches tick.run_tick on a ThreadPoolExecutor (one
    lane's .factory/tick.lock keeps lanes mutually exclusive), prints
    `dispatched_lane:` lines in pool order + `dispatched=<N>`, and returns 0
    only when every dispatched tick exited 0 (else the first non-zero code).
    """
    repo = Path(repo)
    selected, skipped = plan_dispatch(repo, extra_paths=extra_paths,
                                      max_parallel=max_parallel)
    lines = list(skipped)

    if dry_run:
        for s in selected:
            files = ",".join(s["files"]) if s["files"] else "none"
            lines.append(
                f"would_dispatch: {s['lane']} rung={s['rung']} files={files}")
        lines.append("dispatched=0")
        print("\n".join(lines))
        return 0

    results = {}
    if selected:
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(selected)) as ex:
            futs = {
                ex.submit(tick.run_tick, s["repo"],
                          builder_timeout=builder_timeout,
                          verify_timeout=verify_timeout): s
                for s in selected
            }
            for fut, s in futs.items():
                results[id(s)] = fut.result()

    first_bad = 0
    for s in selected:
        code, msg = results[id(s)]
        lines.append(
            f"dispatched_lane: {s['lane']} rung={s['rung']} exit={code} "
            f"msg={msg}")
        if code != 0 and first_bad == 0:
            first_bad = code
    lines.append(f"dispatched={len(selected)}")
    print("\n".join(lines))
    return first_bad
