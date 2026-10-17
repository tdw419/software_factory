"""Change fingerprint for change-gated ticks.

Distilled from the live geometry_os compositor lane monitor (rung1_monitor.py):

- HEAD is the primary wake signal; queue/tickets/ladder hash in too.
- Tree dirt participates EXCEPT paths on the churn allowlist — observers and
  the lane itself rewrite decision_log/state/runs forever, and a dirty-tree
  gate without an allowlist wakes the lane on its own heartbeat.
- .git state is never hashed: gc, reflog-expire and poller fetch chains must
  never wake the loop (the 2026-10-13 HEAD.lock race class).
- If git is transiently unreadable the fingerprint is DEGRADED; the tick
  must not dispatch a builder on unknown state (fetch-storm lesson).
"""

import hashlib
import json
import os
from pathlib import Path

from .common import git, git_root

#: Paths whose churn must never wake the lane. Directories match by prefix.
DEFAULT_ALLOWLIST = (
    ".factory/decision_log.jsonl",
    ".factory/state.json",
    ".factory/runs/",
    ".factory/asks/",
    ".factory/pending_gate.json",
)


def _sha16(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


class Fingerprint:
    def __init__(self, parts: dict, degraded: bool = False):
        self.parts = parts
        self.degraded = degraded

    @property
    def stable(self) -> str:
        if self.degraded:
            return "DEGRADED"
        return _sha16(json.dumps(self.parts, sort_keys=True))

    def as_lines(self):
        if self.degraded:
            return ["state=DEGRADED (git unreadable; tick suppressed, no dispatch)"]
        return [f"{k}={v}" for k, v in self.parts.items()]


def _under_allowlist(path: str, allowlist) -> bool:
    path = path.strip()
    for a in allowlist:
        a = a.rstrip("/")
        if path == a or path.startswith(a + "/") or path.startswith(a):
            return True
    return False


def compute(repo, allowlist=None, ladder=None) -> Fingerprint:
    """Build the stable fingerprint for repo.

    ladder: optional {"path": relpath, "line_prefix": "- Rung"} — status lines
    of a ladder/roadmap file hash in so ladder edits wake the lane even when
    QUEUE_STATE is untouched.
    """
    repo = Path(repo)
    allowlist = tuple(allowlist) if allowlist is not None else DEFAULT_ALLOWLIST
    parts = {}

    root = git_root(repo)
    if root is None:
        return Fingerprint({}, degraded=True)
    r = git(repo, "rev-parse", "HEAD")
    if r.returncode != 0:
        return Fingerprint({}, degraded=True)
    parts["HEAD"] = r.stdout.strip()[:12]

    fdir = repo / ".factory"
    q = fdir / "queue_state.json"
    parts["QUEUE"] = _sha16(q.read_text(encoding="utf-8")) if q.exists() else "MISSING"

    tdir = fdir / "tickets"
    if tdir.is_dir():
        h = hashlib.sha256()
        for p in sorted(tdir.glob("*.md")):
            h.update(p.name.encode("utf-8"))
            h.update(b"\0")
            h.update(p.read_bytes())
        parts["TICKETS"] = h.hexdigest()[:16]
    else:
        parts["TICKETS"] = "MISSING"

    st = git(root, "status", "--porcelain")
    if st.returncode != 0:
        return Fingerprint({}, degraded=True)
    # paths are relative to the git toplevel; scope them to the lane dir and
    # strip the prefix so allowlist matching stays lane-relative
    rel = os.path.relpath(repo, root)
    rows = []
    for ln in st.stdout.splitlines():
        if not ln.strip():
            continue
        p = ln[3:] if len(ln) > 3 else ln
        if rel != ".":
            prefix = rel + os.sep
            if not (p == rel or p.startswith(prefix)):
                continue  # outside the lane's subtree
            p = os.path.relpath(p, rel)
        if not _under_allowlist(p, allowlist):
            rows.append(ln)
    parts["TREE"] = _sha16("\n".join(rows)) if rows else "CLEAN"

    if ladder and ladder.get("path"):
        lp = repo / ladder["path"]
        if lp.exists():
            prefix = ladder.get("line_prefix", "- Rung")
            lines = [ln for ln in lp.read_text(encoding="utf-8").splitlines()
                     if ln.startswith(prefix)]
            parts["LADDER"] = _sha16("\n".join(lines))
        else:
            parts["LADDER"] = "MISSING"

    return Fingerprint(parts)
