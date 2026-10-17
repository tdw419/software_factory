"""QUEUE_STATE.json — the lane's rung ladder, rules, and claims.

Generalized from the geometry_os compositor lane's QUEUE_STATE.json: a lane
name, charter pointer, per-rung status dicts, infra_notes, and the lane
rules list. Live lane stored rungs as top-level keys (rung0..rung5); the
product nests them under "rungs" so rung ids are data, not schema.
"""

from pathlib import Path

from .common import dump_json, factory_dir, load_json, now_iso

STATUSES = ("DRAFT", "OPEN", "IN_PROGRESS", "LANDED", "BLOCKED")

#: The 10 general lane rules, distilled verbatim-in-spirit from the live
#: lane's 11 (its rule 9 — z_order ties — is domain-specific and lives in
#: that lane; see templates/LANE_RULES.md for the annotated mapping).
DEFAULT_RULES = [
    "one ticket at a time; claim by setting claimed_by + updating queue_state.json in the same commit as the work",
    "RED-first gates: the negative leg must be shown RED before the fix is trusted",
    "receipt per ticket; the receipt states what PASS does NOT prove",
    "dependency pins frozen unless a ticket explicitly upgrades them with a receipt",
    "never absorb pre-existing failures into a ticket's gate; count and name them once, then exclude explicitly",
    "WAKE DISCIPLINE: every tick ENDS with a commit, even a decisions-only one (append an infra_notes line if nothing else landed) — a tick that commits nothing leaves the digest unchanged, the next tick is silently suppressed, and the lane dies at its first idle tick",
    "PACKAGE INSTALLS (operator pre-approval): on a measured missing-dependency wall, record an ASK entry (exact packages + measured reason) in the same commit and proceed — additive installs only, nothing touching repo/git state; non-additive or uncertain needs: record the ask and end the tick",
    "COMMIT PER SUB-STEP: the iteration cap can arrive before 'the end' — never hold finished sub-steps in the tree; commit each as it completes (work + queue/log updates together) so any cap or stall loses at most the current sub-step",
    "GATE TIMEOUTS: every gate command runs under an explicit timeout below the scheduler's kill threshold; a suite that genuinely needs longer runs backgrounded with a polled log file",
    "COMMIT SCOPE: enumerate exact paths per commit; never 'git add -A' or bare 'git add .'; out-of-scope dirty files only in a separate commit naming provenance",
]


class QueueError(Exception):
    pass


def queue_path(repo) -> Path:
    return factory_dir(repo) / "queue_state.json"


def new_queue(lane: str, charter: str = "", head: str = "") -> dict:
    return {
        "lane": lane,
        "charter": charter,
        "created": now_iso(),
        "repo_head_at_lane_creation": head,
        "rungs": {},
        "infra_notes": [],
        "rules": list(DEFAULT_RULES),
    }


def load(repo) -> dict:
    p = queue_path(repo)
    if not p.exists():
        raise QueueError(f"no queue at {p} — run 'factory init' first")
    q = load_json(p)
    validate(q)
    return q


def validate(q: dict) -> None:
    if not isinstance(q.get("lane"), str) or not q["lane"]:
        raise QueueError("queue_state: 'lane' must be a non-empty string")
    rules = q.get("rules")
    if not isinstance(rules, list) or not all(isinstance(r, str) for r in rules):
        raise QueueError("queue_state: 'rules' must be a list of strings")
    rungs = q.get("rungs")
    if not isinstance(rungs, dict):
        raise QueueError("queue_state: 'rungs' must be an object")
    for rid, r in rungs.items():
        st = r.get("status")
        if st not in STATUSES:
            raise QueueError(f"rung '{rid}' has invalid status {st!r} (want {STATUSES})")


def save(repo, q: dict) -> None:
    validate(q)
    dump_json(queue_path(repo), q)


def next_actionable(q: dict):
    """Return (rung_id, resuming) for the first OPEN (or claimed IN_PROGRESS)
    rung in insertion order, or (None, False)."""
    for rid, r in q.get("rungs", {}).items():
        if r.get("status") == "OPEN":
            return rid, False
        if r.get("status") == "IN_PROGRESS" and r.get("claimed_by"):
            return rid, True
    return None, False


def register_rung(q: dict, rid: str, title: str, ticket: str,
                  receipt: str = "", status: str = "OPEN") -> None:
    if rid in q["rungs"]:
        raise QueueError(f"rung '{rid}' already exists")
    if status not in STATUSES:
        raise QueueError(f"bad status {status!r}")
    q["rungs"][rid] = {
        "status": status,
        "title": title,
        "ticket": ticket,
        "receipt": receipt,
        "claimed_by": None,
        "opened": now_iso(),
        "claimed_at": None,
        "landed_at": None,
        "commit": None,
    }
