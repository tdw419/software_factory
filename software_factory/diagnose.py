"""factory diagnose — read-only self-diagnosis counter over the lane's own
decision history. Same trust tier as the observer: pure function, zero LLM
calls, NO WRITES to the repo (s2 adds --draft with citations).

Evidence source: decision_log.read_all + read_archived, deduped by ts —
compaction-proof (`factory log compact --keep N` must not erase evidence
diagnose counts; the archive is scanned too).

Signatures (deterministic):
- failure_class:<pattern>  — every tick_failed record's `problem` text is
  classified into a fixed pattern bucket (rules below); per-class count
  over a sliding window (last `window` records) vs threshold.
- violation:<kind>         — gate_refused records (kind from the payload)
  and rung_demoted records whose reason names the RECURSION GUARD
  (kind='kernel_edit' is the GO that would have authorized it).
- stall                    — the trailing streak of non-transient
  tick_failed records with no successful `tick` record after them
  (the log-level mirror of state.json:consecutive_failures).
- parked                   — state.json:parked is true; evidence cites the
  trailing failure streak (the failures that led to the park).

Queue dedup: a rung may declare `covers: [<signature>, ...]` in
queue_state.json. A signature covered by a rung in DRAFT/OPEN/IN_PROGRESS
is skipped; a signature covered by a LANDED rung re-fires when the newest
cited evidence ts postdates that rung's landed_at (recurrence after a
purported fix is a new finding).

Config: `diagnose.thresholds` / `diagnose.window` in config.json; absent
config = the fixed DEFAULT_* values and byte-stable output (findings sorted
by signature, evidence ts in log order).
"""

import json
import re
from datetime import datetime

from . import decision_log, queue_state

#: Sliding window = the newest N deduped records are counted.
DEFAULT_WINDOW = 50

#: Fixed defaults when config.json / diagnose.thresholds is absent.
DEFAULT_THRESHOLDS = {"failure_class": 2, "violation": 1, "stall": 3, "parked": 1}

#: problem-text classification rules — first match wins, all literals come
#: from tick.py's problems vocabulary (never re-derive free text).
_PROBLEM_RULES = (
    ("RECURSION GUARD", "recursion_guard"),
    ("WAKE DISCIPLINE", "wake_discipline"),
    ("QUEUE DISCIPLINE", "queue_discipline"),
    ("verify gate TIMEOUT", "verify_timeout"),
    ("verify gate RED", "verify_red"),
    ("builder exit", "builder_exit"),
    ("receipt", "receipt"),
)

#: Rung statuses whose `covers` suppress a signature outright.
COVERING_STATUSES = ("DRAFT", "OPEN", "IN_PROGRESS")


def classify_problem(problem: str) -> str:
    """Map one problem string to its pattern bucket. Deterministic."""
    for literal, pattern in _PROBLEM_RULES:
        if literal in problem:
            return pattern
    first = problem.split(":", 1)[0].split(None, 1)[0] if problem.strip() else "unknown"
    return re.sub(r"[^a-z0-9]+", "_", first.lower()).strip("_") or "unknown"


def failure_classes(problem: str) -> list:
    """All pattern buckets a tick_failed.problem contributes to.

    tick joins multiple problems with '; ' — split before classifying so a
    multi-cause failure counts once per cause, never twice for one cause.
    """
    out = []
    for part in (problem or "").split("; "):
        p = classify_problem(part)
        if p not in out:
            out.append(p)
    return out or ["unknown"]


def _records(repo) -> list:
    """Live + archived records deduped by ts (crash-window duplicates in both
    files after compact() must count once). Oldest first."""
    seen, out = set(), []
    for r in decision_log.read_archived(repo) + decision_log.read_all(repo):
        ts = r.get("ts")
        if not ts or ts in seen:
            continue
        seen.add(ts)
        out.append(r)
    return out


def _state(repo) -> dict:
    try:
        return json.loads((queue_state.factory_dir(repo) / "state.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _ts_key(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None  # unparseable ts — cannot be ordered, cannot prove coverage


def _threshold_for(thresholds: dict, signature: str):
    if signature in thresholds:
        return thresholds[signature]
    return thresholds.get(signature.split(":", 1)[0], 1)


def _covered(repo, signature: str, evidence_ts: list) -> bool:
    """True when a queue rung's covers entry suppresses this signature."""
    if not evidence_ts:
        return False
    try:
        q = queue_state.load(repo)
    except Exception:
        return False
    keys = [_ts_key(t) for t in evidence_ts]
    newest = max((k for k in keys if k is not None), default=None)
    for r in q.get("rungs", {}).values():
        covers = r.get("covers") or []
        if not isinstance(covers, (list, tuple)) or signature not in covers:
            continue
        status = r.get("status")
        if status in COVERING_STATUSES:
            return True
        if status == "LANDED":
            landed = _ts_key(r.get("landed_at"))
            # fix landed at/after the newest evidence -> it is covered;
            # evidence newer than the fix -> recurrence, a NEW finding
            if landed is not None and newest is not None and landed >= newest:
                return True
    return False


def findings(repo, cfg=None) -> list:
    """Return finding lines (sorted by signature) + the trailing
    findings=<n> line. Read-only; never raises for lane faults."""
    cfg = cfg or {}
    thresholds = dict(DEFAULT_THRESHOLDS)
    thresholds.update(cfg.get("thresholds") or {})
    try:
        window = int(cfg.get("window", DEFAULT_WINDOW))
    except (TypeError, ValueError):
        window = DEFAULT_WINDOW

    recs = _records(repo)
    if window > 0:
        recs = recs[-window:]

    classes, violations, streak = {}, {}, []
    for r in recs:
        ts = r["ts"]
        if "tick_failed" in r:
            tf = r.get("tick_failed") or {}
            if not tf.get("transient"):
                streak.append(ts)
            for pat in failure_classes(tf.get("problem", "")):
                classes.setdefault(pat, []).append(ts)
        elif "tick" in r:
            streak = []  # a successful tick resets the consecutive-failure streak
        if "gate_refused" in r:
            kind = (r.get("gate_refused") or {}).get("kind") or "unknown"
            violations.setdefault(str(kind), []).append(ts)
        if "rung_demoted" in r:
            if "RECURSION GUARD" in ((r.get("rung_demoted") or {}).get("reason") or ""):
                violations.setdefault("kernel_edit", []).append(ts)

    out = []  # (signature, count, evidence_ts)
    for pat, tss in sorted(classes.items()):
        sig = f"failure_class:{pat}"
        if len(tss) >= _threshold_for(thresholds, sig) and not _covered(repo, sig, tss):
            out.append((sig, len(tss), tss))
    for kind, tss in sorted(violations.items()):
        sig = f"violation:{kind}"
        if len(tss) >= _threshold_for(thresholds, sig) and not _covered(repo, sig, tss):
            out.append((sig, len(tss), tss))
    if len(streak) >= thresholds.get("stall", DEFAULT_THRESHOLDS["stall"]) \
            and not _covered(repo, "stall", streak):
        out.append(("stall", len(streak), streak))
    if _state(repo).get("parked") and not _covered(repo, "parked", streak):
        out.append(("parked", 1, streak))  # parked is a STATE: count is 1

    lines = [f"finding: {sig} count={count} evidence={','.join(tss)}"
             for sig, count, tss in sorted(out)]
    lines.append(f"findings={len(out)}")
    return lines


def run(repo, cfg=None) -> list:
    """Print the findings and return the lines (observer.run convention)."""
    lines = findings(repo, cfg=cfg)
    print("\n".join(lines))
    return lines
