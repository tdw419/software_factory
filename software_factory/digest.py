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
from pathlib import Path

from . import queue_state
from .common import (DEFAULT_ALLOWLIST, git, git_root, is_under_allowlist,
                     resolve_allowlist, scoped_dirty_rows, sha16)


class Fingerprint:
    def __init__(self, parts: dict, degraded: bool = False):
        self.parts = parts
        self.degraded = degraded

    @property
    def stable(self) -> str:
        if self.degraded:
            return "DEGRADED"
        return sha16(json.dumps(self.parts, sort_keys=True))

    def as_lines(self):
        if self.degraded:
            return ["state=DEGRADED (git unreadable; tick suppressed, no dispatch)"]
        return [f"{k}={v}" for k, v in self.parts.items()]


def _under_allowlist(path: str, allowlist) -> bool:
    return is_under_allowlist(path, allowlist)


def compute(repo, allowlist=None, ladder=None) -> Fingerprint:
    """Build the stable fingerprint for repo.

    ladder: optional {"path": relpath, "line_prefix": "- Rung"} — status lines
    of a ladder/roadmap file hash in so ladder edits wake the lane even when
    QUEUE_STATE is untouched.
    """
    repo = Path(repo)
    allowlist = resolve_allowlist(repo, allowlist)
    parts = {}

    root = git_root(repo)
    if root is None:
        return Fingerprint({}, degraded=True)
    r = git(repo, "rev-parse", "HEAD")
    if r.returncode != 0:
        return Fingerprint({}, degraded=True)
    parts["HEAD"] = r.stdout.strip()[:12]

    fdir = queue_state.factory_dir(repo)
    q = queue_state.queue_path(repo)
    parts["QUEUE"] = sha16(q.read_text(encoding="utf-8")) if q.exists() else "MISSING"

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

    ok, rows = scoped_dirty_rows(repo, allowlist=allowlist)
    if not ok:
        return Fingerprint({}, degraded=True)
    parts["TREE"] = sha16("\n".join(rows)) if rows else "CLEAN"

    if ladder and ladder.get("path"):
        lp = repo / ladder["path"]
        if lp.exists():
            prefix = ladder.get("line_prefix", "- Rung")
            lines = [ln for ln in lp.read_text(encoding="utf-8").splitlines()
                     if ln.startswith(prefix)]
            parts["LADDER"] = sha16("\n".join(lines))
        else:
            parts["LADDER"] = "MISSING"

    return Fingerprint(parts)
