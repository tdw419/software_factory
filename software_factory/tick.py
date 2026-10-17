"""The tick loop: change-gated wake → dispatch → verify → record.

Semantics distilled from the live lane (including its failure history):

- Unchanged fingerprint → SUPPRESSED no-op tick (cheap; this is the normal
  steady state — parked is not stalled).
- DEGRADED fingerprint (git unreadable) → suppressed, NEVER dispatched.
- Builder fails / gate RED → last_fingerprint is NOT advanced, so the next
  tick retries; after 3 consecutive failures the lane PARKS itself
  (exit 6) instead of hot-looping — the cron-doctor retry/pause ladder.
- WAKE DISCIPLINE is enforced by DETECTION, not trust: if the builder
  returned 0 but committed nothing and left the tree dirty, the tick says
  so loudly and exits non-zero.
- Every wake appends a decision_log record — the tick history is the audit.
"""

import fcntl
import shlex
import subprocess
from pathlib import Path

from . import adapters, decision_log, digest, queue_state
from .common import atomic_write_text, dump_json, git, load_json, now_iso, sh, validate_receipt
from .templates import DEFAULT_CONFIG, PROMPT_TEMPLATE

STATE_NAME = "state.json"
LOCK_NAME = "tick.lock"
PARK_AFTER_FAILURES = 3

EXIT_OK = 0
EXIT_VERIFY_RED = 4
EXIT_BUILDER_FAILED = 5
EXIT_PARKED = 6
EXIT_DEGRADED = 7
EXIT_LOCKED = 8


def state_path(repo) -> Path:
    return queue_state.factory_dir(repo) / STATE_NAME


def lock_path(repo) -> Path:
    return queue_state.factory_dir(repo) / LOCK_NAME


def load_state(repo) -> dict:
    p = state_path(repo)
    if p.exists():
        return load_json(p)
    return {"last_fingerprint": None, "ticks_total": 0, "suppressed_total": 0,
            "wakes_total": 0, "consecutive_failures": 0,
            "transient_failures": 0, "parked": False,
            "last_tick_ts": None}


def save_state(repo, state) -> None:
    state["last_tick_ts"] = now_iso()
    dump_json(state_path(repo), state)


def load_config(repo) -> dict:
    p = queue_state.factory_dir(repo) / "config.json"
    if not p.exists():
        raise FileNotFoundError(f"no config at {p} — run 'factory init'")
    cfg = load_json(p)
    merged = {**DEFAULT_CONFIG, **cfg}
    for k in ("builder", "verify", "digest", "observer"):
        merged[k] = {**DEFAULT_CONFIG.get(k, {}), **cfg.get(k, {})}
    return merged


def _head(repo):
    r = git(repo, "rev-parse", "HEAD")
    return r.stdout.strip()[:12] if r.returncode == 0 else "UNREADABLE"


def run_tick(repo, force=False, dry_run=False, builder_timeout=None,
             verify_timeout=None) -> tuple:
    repo = Path(repo)
    cfg = load_config(repo)
    fdir = queue_state.factory_dir(repo)
    fdir.mkdir(parents=True, exist_ok=True)
    lp = lock_path(repo)
    lock_fd = open(lp, "a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return EXIT_LOCKED, "SUPPRESSED locked (another factory tick is currently running)"
        return _run_tick_locked(repo, cfg, fdir, force=force, dry_run=dry_run,
                                builder_timeout=builder_timeout,
                                verify_timeout=verify_timeout)
    finally:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_fd.close()


def _run_tick_locked(repo, cfg, fdir, force=False, dry_run=False,
                     builder_timeout=None, verify_timeout=None) -> tuple:
    state = load_state(repo)
    state["ticks_total"] += 1

    def finish(code, msg, st=None, suppressed=False):
        if st is not None:
            save_state(repo, st)
        return code, msg

    if state.get("parked"):
        if not force:
            return finish(EXIT_PARKED,
                          f"PARKED after {state['consecutive_failures']} consecutive failures "
                          f"— clear with 'factory tick --force' after fixing the cause")
        if not dry_run:
            state["parked"] = False
            state["consecutive_failures"] = 0
            state["transient_failures"] = 0

    fp = digest.compute(
        repo,
        allowlist=cfg["digest"].get("churn_allowlist"),
        ladder=cfg["digest"].get("ladder") or None,
    )

    if fp.degraded:
        state["suppressed_total"] += 1
        state["transient_failures"] = state.get("transient_failures", 0) + 1
        code = EXIT_DEGRADED if force else EXIT_OK
        return finish(code, "SUPPRESSED degraded (git unreadable; not dispatching on unknown state)",
                      state, suppressed=True)

    if not force and fp.stable == state.get("last_fingerprint"):
        state["suppressed_total"] += 1
        marker = fdir / "runs" / f"{now_iso().replace(':', '')}-suppressed"
        atomic_write_text(marker, fp.stable + "\n")
        return finish(EXIT_OK, "SUPPRESSED no_change", state, suppressed=True)

    q = queue_state.load(repo)
    rid, resuming = queue_state.next_actionable(q)

    if rid is None:
        state["last_fingerprint"] = fp.stable
        return finish(EXIT_OK, "WAKE no_actionable_ticket (digest moved; register or OPEN a rung)", state)

    # ---- dispatch ----
    run_dir = fdir / "runs" / f"{now_iso().replace(':', '')}-{rid}"
    run_dir.mkdir(parents=True, exist_ok=True)
    ticket_rel = q["rungs"][rid].get("ticket", "")
    ticket_body = ""
    tp = repo / ticket_rel if ticket_rel else None
    if tp and tp.exists():
        ticket_body = tp.read_text(encoding="utf-8")
    else:
        ticket_body = f"(ticket file missing: {ticket_rel})"

    prompt_path = run_dir / "prompt.md"
    receipt_rel = q["rungs"][rid].get("receipt") or f".factory/receipts/{rid}_RECEIPT.md"
    prompt = adapters.render_prompt(
        PROMPT_TEMPLATE, lane=q["lane"], rung_id=rid, repo=repo,
        ticket_body=ticket_body, rules=q["rules"], receipt_path=receipt_rel,
        resuming=resuming,
    )
    atomic_write_text(prompt_path, prompt)

    if dry_run:
        return finish(EXIT_OK, f"DRY-RUN: would dispatch rung {rid}; prompt at {prompt_path}")

    head_before = _head(repo)
    adapter_fn = adapters.get_adapter(cfg["builder"]["adapter"])
    b_timeout = builder_timeout or cfg["builder"]["timeout_s"]
    try:
        br = adapter_fn(repo, cfg["builder"].get("cmd", ""), prompt_path, run_dir, b_timeout)
    except subprocess.TimeoutExpired:
        code, msg, st = _record_failure(repo, state, rid, fp,
                                        f"builder TIMEOUT after {b_timeout}s", head_before,
                                        verify=None, exit_code=EXIT_BUILDER_FAILED,
                                        transient=True)
        return finish(code, msg, st)
    except adapters.AdapterError as e:
        code, msg, st = _record_failure(repo, state, rid, fp, str(e), head_before,
                                        verify=None, exit_code=EXIT_BUILDER_FAILED)
        return finish(code, msg, st)
    except Exception as e:
        code, msg, st = _record_failure(repo, state, rid, fp, f"builder raised {type(e).__name__}: {e}",
                                        head_before, verify=None, exit_code=EXIT_BUILDER_FAILED)
        return finish(code, msg, st)

    # ---- verify gate (explicit timeout, rule 8) ----
    v = cfg["verify"]
    verify_status = "skipped"
    verify_exit = None
    if v.get("cmd"):
        v_timeout = verify_timeout or v.get("timeout_s", 170)
        try:
            vr = sh(shlex.split(v["cmd"]), v_timeout, cwd=str(repo))
            verify_exit = vr.returncode
            verify_status = "pass" if vr.returncode == 0 else "RED"
        except subprocess.TimeoutExpired:  # noqa: F821
            verify_status = "TIMEOUT"
            verify_exit = -9
    elif v.get("required"):
        code, msg, st = _record_failure(repo, state, rid, fp,
                                        "verify.required=true but verify.cmd empty", head_before,
                                        verify="misconfigured", exit_code=EXIT_VERIFY_RED)
        return finish(code, msg, st)

    # ---- post-checks ----
    head_after = _head(repo)
    (run_dir / "result.txt").write_text(
        f"adapter_exit={br.returncode}\nverify={verify_status}\n"
        f"head_before={head_before}\nhead_after={head_after}\n"
        f"adapter_stdout_tail={br.stdout[-2000:]}\nadapter_stderr_tail={br.stderr[-2000:]}\n",
        encoding="utf-8",
    )

    problems = []
    if br.returncode != 0:
        problems.append(f"builder exit {br.returncode}")
    if verify_status == "RED":
        problems.append("verify gate RED")
    if verify_status == "TIMEOUT":
        problems.append("verify gate TIMEOUT (wedge risk — rule 8)")
    receipt_abs = repo / receipt_rel
    if not receipt_abs.is_file():
        problems.append(f"receipt missing: {receipt_rel}")
    else:
        missing_secs = validate_receipt(receipt_abs)
        if missing_secs:
            problems.append(f"receipt incomplete ({receipt_rel} missing sections: {', '.join(missing_secs)})")
    rq = queue_state.load(repo)
    rstatus = rq["rungs"][rid]["status"]
    if br.returncode == 0 and rstatus == "IN_PROGRESS" and head_after == head_before:
        problems.append("WAKE DISCIPLINE: builder returned 0 but committed nothing "
                        "(rule 5 — a tick must end with a commit)")

    if problems:
        code, msg, st = _record_failure(repo, state, rid, fp, "; ".join(problems),
                                        head_before, verify=verify_status,
                                        head_after=head_after,
                                        exit_code=EXIT_VERIFY_RED if verify_status == "RED" else EXIT_BUILDER_FAILED)
        return finish(code, msg, st)

    # ---- success: advance fingerprint so the next tick suppresses ----
    fp2 = digest.compute(repo, allowlist=cfg["digest"].get("churn_allowlist"),
                         ladder=cfg["digest"].get("ladder") or None)
    state["last_fingerprint"] = fp2.stable
    state["wakes_total"] += 1
    state["consecutive_failures"] = 0
    state["transient_failures"] = 0
    state["parked"] = False
    decision_log.append(repo, {
        "actor": "factory-tick", "tick": {
            "rung": rid, "wake": "forced" if force else "change",
            "resuming": resuming, "builder_exit": br.returncode,
            "verify": verify_status, "head_before": head_before,
            "head_after": head_after, "receipt": receipt_rel,
            "rung_status": rstatus,
        },
    })
    return finish(EXIT_OK,
                  f"WAKE rung {rid}: builder ok, verify {verify_status}, "
                  f"head {head_before} -> {head_after}", state)


def _record_failure(repo, state, rid, fp, problem, head_before,
                    verify=None, head_after=None, exit_code=EXIT_BUILDER_FAILED,
                    transient=False):
    if transient:
        state["transient_failures"] = state.get("transient_failures", 0) + 1
    else:
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
    decision_log.append(repo, {
        "actor": "factory-tick", "tick_failed": {
            "rung": rid, "problem": problem, "verify": verify,
            "transient": transient,
            "head_before": head_before, "head_after": head_after,
        },
    })
    if not transient and state["consecutive_failures"] >= PARK_AFTER_FAILURES:
        state["parked"] = True
        state["last_fingerprint"] = fp.stable  # stop retry-hot-looping
        return exit_code if exit_code else EXIT_BUILDER_FAILED, \
            f"FAIL rung {rid}: {problem} — PARKED after {state['consecutive_failures']} failures", state
    # fingerprint NOT advanced → next tick retries (self-healing)
    return exit_code, f"FAIL rung {rid}: {problem} (will retry next tick)", state
