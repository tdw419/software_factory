"""GO-gated disruptive operations.

The live lane's hard rule: a disruptive operation (scanout takeover, bulk
deletion, worktree removal) runs only when the OPERATOR types an exact
blessed phrase, and the authorization covers exactly what was enumerated —
never an adjacency. Mechanics distilled from gate_b_go.sh:

- arm: stage {kind, phrase, op} in pending_gate.json (nothing runs).
- fire: the typed phrase must match the armed phrase BYTE-EXACTLY — no
  strip, no case-fold, no unicode normalization. (An em dash U+2014 vs
  ASCII hyphen mismatch is the live lane's canonical near-miss.)
- preflight: an un-aborted GO of the same kind blocks re-fire.
- abort: pairs with the GO's ts so it can be re-armed later; both sides
  land in decision_log.jsonl — spend accounting is the point.
"""

import shlex
import subprocess
from pathlib import Path

from . import decision_log, queue_state
from .common import dump_json, load_json, now_iso, sh, sha16


class GateError(Exception):
    pass


def _pending_path(repo) -> Path:
    return queue_state.factory_dir(repo) / "pending_gate.json"


def arm(repo, kind: str, phrase: str, op_argv, expects: str = "",
        actor: str = "operator") -> dict:
    if not kind or not phrase:
        raise GateError("arm needs both a kind and a non-empty phrase")
    if not op_argv:
        raise GateError("arm needs the operation to authorize (argv)")
    existing = pending(repo)
    if existing is not None:
        raise GateError(
            f"gate already armed ({format_pending(existing)}); "
            f"abort or fire it before arming another"
        )
    p = {
        "kind": kind,
        "phrase": phrase,
        "phrase_sha16": sha16(phrase),
        "op": list(op_argv),
        "expects": expects,
        "armed_ts": now_iso(),
    }
    dump_json(_pending_path(repo), p)
    decision_log.append(repo, {
        "actor": actor,
        "gate_armed": {
            "kind": kind,
            "phrase_sha16": p["phrase_sha16"],
            "op": p["op"],
            "expects": expects,
        },
        "ts": p["armed_ts"],
    })
    return p


def pending(repo):
    p = _pending_path(repo)
    return load_json(p) if p.exists() else None


def disarm(repo):
    p = _pending_path(repo)
    if p.exists():
        p.unlink()


def fire(repo, typed: str, actor: str = "operator", timeout: int = 600,
         dry_run: bool = False):
    """Fire the armed gate. Returns (exit_code, record).

    Exit codes: 0 ok, 2 nothing armed, 3 refused (phrase or spend-block),
    124 timeout, op's exit code otherwise.
    """
    g = pending(repo)
    if g is None:
        return 2, {"gate_error": "nothing armed"}

    kind = g["kind"]
    # BYTE-EXACT match — deliberately no .strip(), no normalization.
    if typed != g["phrase"]:
        rec = decision_log.append(repo, {
            "actor": actor,
            "gate_refused": {"kind": kind, "reason": "phrase_mismatch",
                             "typed_sha16": sha16(typed)},
        })
        return 3, rec

    blockers = decision_log.un_abortedgos(repo, kind)
    if blockers:
        rec = decision_log.append(repo, {
            "actor": actor,
            "gate_refused": {"kind": kind,
                             "reason": "un-aborted GO already spent",
                             "blocking_ts": [b["ts"] for b in blockers]},
        })
        return 3, rec

    if dry_run:
        return 0, {"gate_preflight": "ok", "op": g["op"], "kind": kind}

    go_ts = now_iso()
    decision_log.append(repo, {
        "actor": actor,
        f"{kind}_go": g["phrase"],
        "op": g["op"],
        "ts": go_ts,
    })
    try:
        r = sh(g["op"], timeout=timeout)
        outcome = {"exit": r.returncode,
                   "stdout_tail": r.stdout[-2000:],
                   "stderr_tail": r.stderr[-2000:]}
    except subprocess.TimeoutExpired as e:
        out_str = (e.stdout.decode("utf-8", errors="replace")
                   if isinstance(e.stdout, bytes) else (e.stdout or ""))
        err_str = (e.stderr.decode("utf-8", errors="replace")
                   if isinstance(e.stderr, bytes) else (e.stderr or ""))
        outcome = {"exit": 124,
                   "timeout": timeout,
                   "stdout_tail": out_str[-2000:],
                   "stderr_tail": err_str[-2000:]}
    rec = decision_log.append(repo, {
        "actor": actor,
        f"{kind}_result": outcome,
        "go_ts": go_ts,
    })
    disarm(repo)
    return outcome["exit"], rec


def abort(repo, kind: str, reason: str, actor: str = "operator"):
    """Abort the newest un-aborted GO of kind and/or disarm an armed gate.

    Aborting an ARMED-BUT-UNSPENT gate is legal (cancel before firing) and
    leaves no GO to pair with — a disarm record is written instead.
    """
    g = pending(repo)
    blockers = decision_log.un_abortedgos(repo, kind)
    armed = g is not None and g["kind"] == kind
    if not blockers and not armed:
        raise GateError(f"nothing to abort: no un-aborted GO and no armed gate for '{kind}'")
    payload = ({f"{kind}_go_aborted": blockers[-1]["ts"]}
               if blockers else {"gate_disarmed": kind})
    rec = decision_log.append(repo, {"actor": actor, "reason": reason, **payload})
    if armed:
        disarm(repo)
    return rec


def format_pending(g) -> str:
    if g is None:
        return "nothing armed"
    return (f"kind={g['kind']} phrase_sha16={g['phrase_sha16']} "
            f"op={shlex.join(g['op'])} armed={g['armed_ts']}")
