"""decision_log.jsonl — append-only operator/lane decision record.

Live-lane conventions preserved:
- One JSON object per line, raw UTF-8 (ensure_ascii=False — the \\u2014
  escape broke the GO matcher once; never again).
- GO/abort pairing: a GO record for kind K carries key "K_go"; an abort
  record carries "K_go_aborted" whose value is the GO record's "ts".
  A GO is spend-blocking unless an abort names its ts (aborted GOs are
  free to re-arm — gate_b_go.sh preflight logic).
- The file is append-only. Agents never rewrite it; only this module
  appends, atomically, with fsync.
"""

import json
import os
from pathlib import Path

from . import queue_state
from .common import atomic_write_text, now_iso


def log_path(repo) -> Path:
    return queue_state.factory_dir(repo) / "decision_log.jsonl"


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


def un_abortedgos(repo, kind: str):
    """GO records for kind with no abort naming their ts (spend-blocking)."""
    gos, aborted = [], set()
    for r in read_all(repo):
        if f"{kind}_go_aborted" in r:
            aborted.add(r[f"{kind}_go_aborted"])
    for r in read_all(repo):
        if f"{kind}_go" in r and r.get("ts") not in aborted:
            gos.append(r)
    return gos


def mark_aborted(repo, kind: str, go_ts: str, reason: str, actor: str = "operator") -> dict:
    return append(repo, {
        "actor": actor,
        f"{kind}_go_aborted": go_ts,
        "reason": reason,
    })
