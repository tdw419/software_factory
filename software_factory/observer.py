"""Mechanical observer — the SECOND CHECKER.

Port of the live lane's compositor_observer_monitor.py, generalized:

- stdout is a STABLE state tuple (no timestamps) — feed it to any
  change-gated cron: unchanged output = silent tick, changed = wake.
- optional --log-dir: appends timestamped snapshots only on change, with a
  .last sidecar (the watchdog logging pattern).
- commit handles are CLASSIFIED (PROSE / MISSING / RESOLVED / BROKEN) —
  the live lane's c2 check that catches "this commit" prose placeholders.
- named rules are located by CONTENT, never by index.
- never writes the repo. Ever.
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import decision_log, queue_state
from .common import (atomic_write_text, git, in_watch_scope,
                     resolve_kernel_paths, resolve_ladder, resolve_watch_paths,
                     scoped_dirty_rows, sha12, touched_kernel_paths,
                     validate_receipt)


def _classify_handle(repo, handle: str) -> str:
    if not handle:
        return "MISSING"
    if handle.startswith("this commit") or " " in handle:
        return "PROSE"
    r = git(repo, "cat-file", "-e", f"{handle}^{{commit}}")
    return "RESOLVED" if r.returncode == 0 else "BROKEN"


#: A ladder line is `- Rung <id> [<STATUS>]: ...` (line prefix configurable).
_LADDER_LINE = re.compile(r"^\S+\s+\[([^\]]+)\]")


def _ladder_statuses(repo, ladder: dict) -> dict:
    """Map rung id -> status from the configured ladder file. Read-only."""
    lp = repo / ladder["path"]
    if not lp.is_file():
        return {}
    prefix = ladder.get("line_prefix", "- Rung")
    out = {}
    for ln in lp.read_text(encoding="utf-8").splitlines():
        if not ln.startswith(prefix):
            continue
        rest = ln[len(prefix):].strip()
        m = _LADDER_LINE.match(rest)
        if m:
            out[rest.split(None, 1)[0]] = m.group(1)
    return out


def observe(repo, stale_secs=5400, watch_rules=(), churn_allowlist=None,
            heartbeat_stale_after_min=None) -> list:
    """Return the stable state lines. Read-only; never raises for lane faults."""
    repo = Path(repo)
    lines = []
    q = None
    try:
        q = queue_state.load(repo)
        lines.append("queue_parse=OK")
    except Exception as e:
        lines.append(f"queue_parse=FAILED {type(e).__name__}")

    if q is not None:
        rules = q.get("rules", [])
        lines.append(f"rules_count={len(rules)}")
        lines.append(f"rules_sha={sha12(chr(10).join(rules))}")
        for w in watch_rules:
            key = "watch_" + sha12(w)
            lines.append(f"{key}={'OK' if any(w in r for r in rules) else 'GONE'}")
        landed_commits = []
        for rid, r in q.get("rungs", {}).items():
            st = r.get("status", "?")
            lines.append(f"rung_{rid}_status={st}")
            if st == "LANDED":
                cls = _classify_handle(repo, r.get("commit") or "")
                lines.append(f"rung_{rid}_handle={cls}")
                landed_commits.append((rid, (r.get("receipt") or "").strip()))
        missing = []
        incomplete = []
        for rid, rp in landed_commits:
            if not rp or not (repo / rp).is_file():
                missing.append(rid)
            elif validate_receipt(repo / rp):
                incomplete.append(rid)
        lines.append("receipts_missing=" + (",".join(missing) if missing else "none"))
        if incomplete:
            lines.append("receipts_incomplete=" + ",".join(incomplete))

        # ladder drift: rung statuses in the ROADMAP/ladder file vs queue_state.
        # Only compare rungs present in BOTH; unconfigured or missing ladder
        # file emits nothing (the line itself only exists when checkable).
        ladder = resolve_ladder(repo)
        if ladder.get("path"):
            ladder_st = _ladder_statuses(repo, ladder)
            drift = sorted(
                rid for rid, st in ladder_st.items()
                if rid in q.get("rungs", {})
                and q["rungs"][rid].get("status") != st
            )
            lines.append("ladder_drift=" + (",".join(drift) if drift else "none"))

        kpaths = resolve_kernel_paths(repo)
        if kpaths:
            base_head = q.get("repo_head_at_lane_creation") or ""
            _wp = resolve_watch_paths(repo)
            ktouched = [p for p in touched_kernel_paths(
                            repo, base_head, "HEAD",
                            include_working_tree=False,
                            kernel_paths=kpaths)
                        if in_watch_scope(p, _wp)]
            if not ktouched:
                lines.append("kernel_guard=OK")
            elif decision_log.un_abortedgos(repo, "kernel_edit"):
                lines.append("kernel_guard=AUTHORIZED(" + ",".join(ktouched) + ")")
            else:
                lines.append("kernel_guard=VIOLATION(" + ",".join(ktouched) + ")")

    # an armed gate that never fires is invisible to every other surface;
    # surface it as stable lines (staleness bucketed to yes/no so stdout
    # stays identical between ticks until the threshold is actually crossed)
    gp = queue_state.factory_dir(repo) / "pending_gate.json"
    if gp.is_file():
        try:
            g = json.loads(gp.read_text(encoding="utf-8"))
            lines.append(f"gate_armed={g.get('kind', '?')}")
            try:
                armed = datetime.fromisoformat(g["armed_ts"])
                age = (datetime.now(timezone.utc) - armed).total_seconds()
                lines.append("gate_armed_stale=" + ("yes" if age > stale_secs else "no"))
            except (KeyError, ValueError):
                pass
        except (json.JSONDecodeError, OSError):
            lines.append("gate_armed=UNREADABLE")

    ok, rows = scoped_dirty_rows(repo, allowlist=churn_allowlist)
    if ok:
        lines.append(f"tree={'DIRTY(%d)' % len(rows) if rows else 'CLEAN'}")
    else:
        lines.append("tree=UNREADABLE")

    # log compaction surface: bucketed existence of the archive file, so
    # the line is stable between ticks until a compact() actually runs
    lines.append("log_archive="
                 + ("yes" if (queue_state.factory_dir(repo)
                              / decision_log.ARCHIVE_NAME).is_file() else "no"))

    runs = queue_state.factory_dir(repo) / "runs"
    if heartbeat_stale_after_min is not None:
        # config engaged: categorical OK|STALE against now-minus-threshold
        # (STALE is a state change -> the cron observer leg wakes the agent).
        # STALE means "no successful tick execution in N minutes": every
        # finishing tick persists state.json:last_tick_ts (suppressed,
        # degraded, WAKE no_actionable — tick.finish() -> save_state(); only
        # PARKED and dry_run skip it), so freshness is the NEWEST of both
        # persisted sources. A missing/unparseable state.json simply drops
        # out of the max (runs mtime alone, the pre-r7 behavior).
        sources = []
        try:
            sources.append(max(os.path.getmtime(os.path.join(runs, f))
                               for f in os.listdir(runs)))
        except (OSError, ValueError):
            pass
        try:
            s = json.loads((queue_state.factory_dir(repo) / "state.json")
                           .read_text(encoding="utf-8"))
            sources.append(
                datetime.fromisoformat(s["last_tick_ts"]).timestamp())
        except (OSError, ValueError, TypeError, KeyError):
            pass
        if not sources:
            lines.append("tick_heartbeat=missing")
        else:
            stale = time.time() - max(sources) > heartbeat_stale_after_min * 60
            lines.append("tick_heartbeat=" + ("STALE" if stale else "OK"))
    else:
        # config absent: legacy vocabulary, byte-identical behavior (runs
        # mtimes only — state.json is never consulted on this path)
        try:
            mt = max(os.path.getmtime(os.path.join(runs, f))
                     for f in os.listdir(runs))
            lines.append("tick_heartbeat="
                         + ("STALL" if time.time() - mt > stale_secs else "OK"))
        except (OSError, ValueError):
            lines.append("tick_heartbeat=NO_RUNS")

    return lines


def run(repo, log_dir=None, stale_secs=5400, watch_rules=(), churn_allowlist=None,
        heartbeat_stale_after_min=None) -> list:
    lines = observe(repo, stale_secs=stale_secs, watch_rules=watch_rules,
                    churn_allowlist=churn_allowlist,
                    heartbeat_stale_after_min=heartbeat_stale_after_min)
    print("\n".join(lines))
    if log_dir:
        state = "\n".join(lines)
        last = Path(log_dir) / ".observer_last"
        prev = last.read_text(encoding="utf-8") if last.exists() else ""
        if state != prev:
            log_dir = Path(log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            with open(log_dir / "observer.log", "a", encoding="utf-8") as f:
                f.write(f"=== {stamp} ===\n{state}\n\n")
            atomic_write_text(last, state)
    return lines
