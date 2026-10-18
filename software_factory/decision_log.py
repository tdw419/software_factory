"""decision_log.jsonl — append-only operator/lane decision record.

Live-lane conventions preserved:
- One JSON object per line, raw UTF-8 (ensure_ascii=False — the \\u2014
  escape broke the GO matcher once; never again).
- GO/abort pairing: a GO record for kind K carries key "K_go"; an abort
  record carries "K_go_aborted" whose value is the GO record's "ts".
  A GO is spend-blocking unless an abort names its ts (aborted GOs are
  free to re-arm — gate_b_go.sh preflight logic).
- The file is append-only. Agents never rewrite it; only this module
  appends, atomically, with fsync. The ONE sanctioned rewrite is
  compact() — it moves entries beyond the newest N to the archive file
  while holding the same tick.lock a tick holds, so it can never race an
  appending tick. GO/abort pairing survives compaction: un_abortedgos
  scans archive + live, because an abort may land in the live log long
  after its GO was archived (and vice versa).
"""

import fcntl
import json
import os
from pathlib import Path

from . import queue_state
from .common import atomic_write_text, now_iso

#: Companion archive file — older entries land here on compact().
ARCHIVE_NAME = "decision_log.archive.jsonl"

#: Default retention for compact(): keep the newest 2000 entries live.
DEFAULT_KEEP = 2000


def log_path(repo) -> Path:
    return queue_state.factory_dir(repo) / "decision_log.jsonl"


def archive_path(repo) -> Path:
    return queue_state.factory_dir(repo) / ARCHIVE_NAME


def append(repo, record: dict) -> dict:
    """Append one record; ts injected if absent. Returns the stored record."""
    rec = dict(record)
    rec.setdefault("ts", now_iso())
    line = json.dumps(rec, ensure_ascii=False)
    p = log_path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())
    return rec


def read_all(repo):
    p = log_path(repo)
    if not p.exists():
        return []
    out = []
    for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not ln.strip():
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError as e:
            raise ValueError(f"decision_log line {i} is not valid JSON: {e}") from e
    return out


def read_archived(repo):
    """Parse the archive file. Same strictness as read_all (malformed = raise)."""
    p = archive_path(repo)
    if not p.exists():
        return []
    out = []
    for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not ln.strip():
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError as e:
            raise ValueError(f"decision_log archive line {i} is not valid JSON: {e}") from e
    return out


def un_abortedgos(repo, kind: str):
    """GO records for kind with no abort naming their ts (spend-blocking).

    Single pass over live log + archive: abort records pair with GO
    records by ts value, not by file order or file membership, so either
    side may sit in the archive after a compact(). Collect both kinds in
    one scan, then subtract. GO records are deduped by ts because the
    crash window in compact() (archived first, live rewritten second)
    can briefly leave a GO in both files — duplicates must not inflate
    spend accounting.
    """
    gos, aborted, seen_ts = [], set(), set()
    go_key, abort_key = f"{kind}_go", f"{kind}_go_aborted"
    for r in read_all(repo) + read_archived(repo):
        if abort_key in r:
            aborted.add(r[abort_key])
        if go_key in r:
            ts = r.get("ts")
            if ts in seen_ts:
                continue
            seen_ts.add(ts)
            gos.append(r)
    return [g for g in gos if g.get("ts") not in aborted]


#: tick.LOCK_NAME — restated here because importing tick from this module
#: would be circular (tick imports decision_log). compact() must take the
#: SAME flock a running tick holds (rule: never race the appender).
_TICK_LOCK_NAME = "tick.lock"


def compact(repo, keep: int = DEFAULT_KEEP, actor: str = "lane") -> tuple:
    """Move entries beyond the newest `keep` to the archive file.

    Returns (exit_code, summary). Exit codes: 0 ok (compacted or nothing
    to do), 2 bad keep, 8 tick.lock held by another process (refused).
    Order is preserved oldest-first on both sides of the split; the
    archive append happens BEFORE the live rewrite, so a crash between
    the two leaves duplicate entries (harmless — un_abortedgos dedupes
    by ts) instead of lost ones.
    """
    repo = Path(repo)
    if keep < 1:
        return 2, {"compact_error": f"keep must be >= 1 (got {keep})"}
    fdir = queue_state.factory_dir(repo)
    fdir.mkdir(parents=True, exist_ok=True)
    lock_fd = open(fdir / _TICK_LOCK_NAME, "a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 8, {"compact_error": "refused: a factory tick holds tick.lock"}
        return _compact_locked(repo, fdir, keep, actor)
    finally:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_fd.close()


def _compact_locked(repo, fdir, keep, actor) -> tuple:
    p = log_path(repo)
    if not p.exists():
        return 0, {"kept": 0, "archived": 0}
    raw = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    total = len(raw)
    if total <= keep:
        return 0, {"kept": total, "archived": 0}
    # validate BEFORE touching either file — never corrupt the audit trail
    for i, ln in enumerate(raw, 1):
        try:
            json.loads(ln)
        except json.JSONDecodeError as e:
            raise ValueError(f"decision_log line {i} is not valid JSON: {e}") from e
    archived_lines, kept_lines = raw[:-keep], raw[-keep:]
    with open(archive_path(repo), "a", encoding="utf-8") as f:
        for ln in archived_lines:
            f.write(ln + "\n")
        f.flush()
        os.fsync(f.fileno())
    atomic_write_text(p, "\n".join(kept_lines) + "\n")
    summary = {"kept": len(kept_lines), "archived": len(archived_lines),
               "keep": keep, "archive": ARCHIVE_NAME}
    append(repo, {"actor": actor, "log_compacted": summary})
    return 0, summary


def mark_aborted(repo, kind: str, go_ts: str, reason: str, actor: str = "operator") -> dict:
    return append(repo, {
        "actor": actor,
        f"{kind}_go_aborted": go_ts,
        "reason": reason,
    })
