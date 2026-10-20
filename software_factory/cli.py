"""factory — command line interface."""

import argparse
import shlex
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct-file run: python3 .../cli.py --help
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "software_factory"

from . import __version__, decision_log, diagnose, digest, gate, human_gate, observer, pool, queue_state, tick
from .common import (atomic_write_text, dump_json, git, now_iso,
                     validate_receipt)
from .templates import (DEFAULT_CONFIG, OBSERVER_PROMPT_TEMPLATE, PROMPT_TEMPLATE,
                        RECEIPT_TEMPLATE, TICKET_TEMPLATE)


def _repo(args) -> Path:
    return Path(args.repo).resolve()


def _load_cfg_or_none(repo):
    p = queue_state.factory_dir(repo) / "config.json"
    return tick.load_config(repo) if p.exists() else None


# ---------- commands ----------

def cmd_init(args):
    repo = _repo(args)
    fdir = queue_state.factory_dir(repo)
    if queue_state.queue_path(repo).exists() and not args.force:
        print(f"already initialized at {fdir} (use --force to re-init)")
        return 1
    fdir.mkdir(parents=True, exist_ok=True)
    for sub in ("tickets", "receipts", "runs", "asks"):
        (fdir / sub).mkdir(exist_ok=True)

    head = git(repo, "rev-parse", "HEAD").stdout.strip()[:12]
    q = queue_state.new_queue(args.lane, charter=args.charter, head=head)
    queue_state.save(repo, q)

    cfg = {**DEFAULT_CONFIG,
           "lane": args.lane,
           "verify": {**DEFAULT_CONFIG["verify"], "cmd": args.verify_cmd or ""},
           "builder": {**DEFAULT_CONFIG["builder"], "cmd": args.builder_cmd or ""}}
    dump_json(fdir / "config.json", cfg)

    atomic_write_text(fdir / "decision_log.jsonl", "")
    atomic_write_text(fdir / "tickets" / "_TEMPLATE.md",
                      TICKET_TEMPLATE.format(rung_id="<id>", title="<title>"))
    atomic_write_text(fdir / "receipts" / "_TEMPLATE.md",
                      RECEIPT_TEMPLATE.format(rung_id="<id>", title="<title>"))
    atomic_write_text(fdir / "templates" / "PROMPT_TEMPLATE.md", PROMPT_TEMPLATE)
    atomic_write_text(fdir / "templates" / "OBSERVER_PROMPT.md", OBSERVER_PROMPT_TEMPLATE)
    atomic_write_text(fdir / ".gitignore", "runs/\npending_gate.json\ntick.lock\n")

    print(f"initialized lane '{args.lane}' at {fdir}")
    print(f"  head at creation: {head or '(no commits yet)'}")
    print("next: drop a ticket in .factory/tickets/, register it with "
          "'factory ticket add', then wire 'factory tick' to your scheduler")
    return 0


def cmd_status(args):
    repo = _repo(args)
    q = queue_state.load(repo)
    print(f"lane:    {q['lane']}")
    print(f"charter: {q.get('charter') or '(none)'}")
    print(f"rules:   {len(q['rules'])}")
    print("rungs:")
    for rid, r in q["rungs"].items():
        extra = f" commit={r['commit']}" if r.get("commit") else ""
        claim = f" claimed_by={r['claimed_by']}" if r.get("claimed_by") else ""
        print(f"  {rid:12s} {r['status']:12s}{claim} {r['title']}{extra}")
    st = tick.load_state(repo)
    print(f"ticks:   {st.get('ticks_total', 0)} total, {st.get('wakes_total', 0)} wakes, "
          f"{st.get('suppressed_total', 0)} suppressed"
          + ("  [PARKED]" if st.get("parked") else ""))
    asks = human_gate.list_asks(repo)
    pending_asks = [p for p, s in asks if s.upper() == "PENDING"]
    if pending_asks:
        print(f"asks:    {len(pending_asks)} PENDING (factory ask list)")
    g = gate.pending(repo)
    if g:
        print(f"gate:    ARMED {gate.format_pending(g)}")
    return 0


def cmd_digest(args):
    repo = _repo(args)
    cfg = _load_cfg_or_none(repo)
    ladder = cfg["digest"].get("ladder") if cfg else None
    fp = digest.compute(repo, ladder=(ladder or None))
    print("\n".join(fp.as_lines()))
    print(f"fingerprint={fp.stable}")
    return 0


def cmd_tick(args):
    repo = _repo(args)
    code, msg = tick.run_tick(repo, force=args.force, dry_run=args.dry_run,
                              builder_timeout=args.builder_timeout,
                              verify_timeout=args.verify_timeout)
    print(msg)
    return code


def _covers_list(raw):
    """Parse a --covers comma-separated string into a signature list
    (None when the flag is absent; empty items stripped)."""
    if raw is None:
        return None
    return [s.strip() for s in raw.split(",") if s.strip()]


def cmd_ticket(args):
    repo = _repo(args)
    if args.sub == "add":
        p = Path(args.ticket)
        if not p.is_absolute():
            p = repo / p
        if not p.exists():
            print(f"ticket file missing: {p}")
            return 1
        q = queue_state.load(repo)
        queue_state.register_rung(q, args.id, args.title,
                                  str(p.relative_to(repo)) if p.is_relative_to(repo) else str(p),
                                  receipt=args.receipt or f".factory/receipts/{args.id}_RECEIPT.md",
                                  status=args.status, covers=_covers_list(args.covers),
                                  files=_covers_list(args.files))
        queue_state.save(repo, q)
        print(f"registered rung {args.id} ({args.status}): {args.title}")
        return 0
    if args.sub == "set":
        q = queue_state.load(repo)
        try:
            _, changes = queue_state.update_rung(
                q, args.id, status=args.status, commit=args.commit,
                receipt=args.receipt, claimed_by=args.claimed_by, title=args.title,
                covers=_covers_list(args.covers), files=_covers_list(args.files))
        except queue_state.QueueError as e:
            print(f"ticket set: {e}")
            return 1
        if changes:
            queue_state.save(repo, q)
            decision_log.append(repo, {
                "actor": "operator", "rung_updated": {"rung": args.id, **changes},
            })
        print(f"updated rung {args.id}: {changes if changes else 'no changes'}")
        return 0
    if args.sub == "validate":
        p = Path(args.ticket)
        text = p.read_text(encoding="utf-8")
        missing = [s for s in ("## Goal", "## Stages", "## Constraints") if s not in text]
        if missing:
            print(f"{p}: missing sections {missing}")
            return 1
        print(f"{p}: ok")
        return 0
    print("unknown ticket subcommand")
    return 2


def cmd_receipt(args):
    repo = _repo(args)
    p = Path(args.receipt)
    if not p.is_absolute():
        p = repo / p
    problems = validate_receipt(p)
    if problems:
        print(f"{p}: invalid ({', '.join(problems)})")
        return 1
    print(f"{p}: ok")
    return 0


def cmd_log(args):
    repo = _repo(args)
    recs = decision_log.read_all(repo)
    if args.tail:
        recs = recs[-args.tail:]
    for r in recs:
        print(json_dumps(r))
    return 0


def cmd_log_compact(args):
    repo = _repo(args)
    code, summary = decision_log.compact(repo, keep=args.keep)
    print(json_dumps(summary))
    return code


def cmd_diagnose(args):
    repo = _repo(args)
    cfg = _load_cfg_or_none(repo)
    diagnose.run(repo, cfg=(cfg or {}).get("diagnose"), draft=args.draft)
    return 0


def json_dumps(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)


def cmd_gate(args):
    repo = _repo(args)
    if args.sub == "arm":
        # multi-token op after '--' is already argv; single quoted string is a cmdline
        op = args.op if len(args.op) > 1 else shlex.split(args.op[0])
        g = gate.arm(repo, args.kind, args.phrase, op, expects=args.expects or "")
        print("armed: " + gate.format_pending(g))
        return 0
    if args.sub == "fire":
        code, rec = gate.fire(repo, args.phrase, actor=args.actor,
                              timeout=args.timeout, dry_run=args.dry_run)
        print(json_dumps(rec) if code not in (0,) or "gate_preflight" in rec else "fired ok")
        if code == 0 and "gate_preflight" not in rec:
            print("op exit 0")
        return code
    if args.sub == "abort":
        try:
            rec = gate.abort(repo, args.kind, args.reason, actor=args.actor)
        except gate.GateError as e:
            print(f"refused: {e}")
            return 3
        print("aborted: " + json_dumps(rec))
        return 0
    if args.sub == "status":
        print(gate.format_pending(gate.pending(repo)))
        return 0
    return 2


def cmd_ask(args):
    repo = _repo(args)
    if args.sub == "create":
        p = human_gate.create(repo, args.subject, args.question,
                              options=args.options or "", actor=args.actor)
        print(f"created {p}")
        return 0
    if args.sub == "answer":
        try:
            p = human_gate.answer(repo, args.ask, args.answer, actor=args.actor)
        except human_gate.AskError as e:
            print(f"ask answer: {e}")
            return 1
        print(f"answered {p}")
        return 0
    if args.sub == "list":
        for p, s in human_gate.list_asks(repo):
            print(f"{s:10s} {p}")
        return 0
    return 2


def cmd_pool(args):
    repo = _repo(args)
    extra = _covers_list(getattr(args, "paths", None)) or ()
    pool.run(repo, extra_paths=extra)
    return 0


def cmd_dispatch(args):
    repo = _repo(args)
    extra = _covers_list(getattr(args, "paths", None)) or ()
    return pool.dispatch(repo, extra_paths=extra, dry_run=args.dry_run,
                         max_parallel=args.max_parallel,
                         builder_timeout=args.builder_timeout,
                         verify_timeout=args.verify_timeout)


def cmd_observe(args):
    repo = _repo(args)
    cfg = _load_cfg_or_none(repo)
    obs = cfg["observer"] if cfg else {}
    observer.run(repo, log_dir=args.log_dir,
                 stale_secs=args.stale_secs or obs.get("stale_secs", 5400),
                 watch_rules=obs.get("watch_rules", ()),
                 heartbeat_stale_after_min=obs.get("heartbeat_stale_after_min"))
    return 0


def cmd_version(args):
    print(f"factory {__version__}")
    return 0


# ---------- parser ----------

def build_parser():
    p = argparse.ArgumentParser(prog="factory",
                                description="standalone autonomous builder lane")
    p.add_argument("--repo", default=".", help="target repository (default: cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="scaffold .factory/ in the repo")
    sp.add_argument("--lane", required=True)
    sp.add_argument("--charter", default="")
    sp.add_argument("--verify-cmd", default="")
    sp.add_argument("--builder-cmd", default="")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_init)

    sp = sub.add_parser("status", help="queue + lane state summary")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("digest", help="print the change fingerprint")
    sp.set_defaults(fn=cmd_digest)

    sp = sub.add_parser("tick", help="one lane tick (change-gated)")
    sp.add_argument("--force", action="store_true", help="skip digest gate; also unparks")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--builder-timeout", type=int, default=None)
    sp.add_argument("--verify-timeout", type=int, default=None)
    sp.set_defaults(fn=cmd_tick)

    sp = sub.add_parser("ticket", help="register/validate tickets")
    tsub = sp.add_subparsers(dest="sub", required=True)
    sp2 = tsub.add_parser("add")
    sp2.add_argument("--id", required=True)
    sp2.add_argument("--title", required=True)
    sp2.add_argument("--ticket", required=True)
    sp2.add_argument("--receipt", default="")
    sp2.add_argument("--status", default="OPEN", choices=queue_state.STATUSES)
    sp2.add_argument("--covers", default=None,
                     help="comma-separated signature list (covers: [...] dedup)")
    sp2.add_argument("--files", default=None,
                     help="comma-separated expected-touch paths/globs (conflict metadata)")
    sp2.set_defaults(fn=cmd_ticket)
    sp3 = tsub.add_parser("validate")
    sp3.add_argument("ticket")
    sp3.set_defaults(fn=cmd_ticket)
    sp4 = tsub.add_parser("set", help="update rung lifecycle (status/commit/claim)")
    sp4.add_argument("id")
    sp4.add_argument("--status", default=None, choices=queue_state.STATUSES)
    sp4.add_argument("--commit", default=None,
                     help="bare sha handle (prose refused — observer classifies it PROSE)")
    sp4.add_argument("--receipt", default=None)
    sp4.add_argument("--claimed-by", default=None, dest="claimed_by")
    sp4.add_argument("--title", default=None)
    sp4.add_argument("--covers", default=None,
                     help="comma-separated signature list (covers: [...] dedup)")
    sp4.add_argument("--files", default=None,
                     help="comma-separated expected-touch paths/globs (conflict metadata)")
    sp4.set_defaults(fn=cmd_ticket)

    sp = sub.add_parser("receipt", help="validate receipts")
    rsub = sp.add_subparsers(dest="sub", required=True)
    sp2 = rsub.add_parser("validate")
    sp2.add_argument("receipt", help="receipt path (repo-relative or absolute)")
    sp2.set_defaults(fn=cmd_receipt)

    sp = sub.add_parser("log", help="show decision_log.jsonl")
    sp.add_argument("--tail", type=int, default=0)
    sp.set_defaults(fn=cmd_log)
    lsub = sp.add_subparsers(dest="sub")
    sp2 = lsub.add_parser("compact",
                          help="move entries beyond the newest N to the archive")
    sp2.add_argument("--keep", type=int, default=decision_log.DEFAULT_KEEP,
                     help="entries to keep live (default: %(default)s)")
    sp2.set_defaults(fn=cmd_log_compact)

    sp = sub.add_parser("diagnose",
                        help="read-only self-diagnosis counter over the decision log")
    sp.add_argument("--draft", action="store_true",
                    help="draft one DRAFT rung (origin=self) per uncovered finding; "
                         "the human gate at DRAFT -> OPEN stays sovereign")
    sp.set_defaults(fn=cmd_diagnose)

    sp = sub.add_parser("gate", help="GO-gated disruptive operations")
    gsub = sp.add_subparsers(dest="sub", required=True)
    sp2 = gsub.add_parser("arm")
    sp2.add_argument("--kind", required=True)
    sp2.add_argument("--phrase", required=True)
    sp2.add_argument("--expects", default="")
    sp2.add_argument("op", nargs="+",
                     help="op argv after '--', e.g. -- ./takeover.sh --target eDP-1")
    sp2.set_defaults(fn=cmd_gate)
    sp3 = gsub.add_parser("fire")
    sp3.add_argument("phrase")
    sp3.add_argument("--actor", default="operator")
    sp3.add_argument("--timeout", type=int, default=600)
    sp3.add_argument("--dry-run", action="store_true")
    sp3.set_defaults(fn=cmd_gate)
    sp4 = gsub.add_parser("abort")
    sp4.add_argument("--kind", required=True)
    sp4.add_argument("--reason", required=True)
    sp4.add_argument("--actor", default="operator")
    sp4.set_defaults(fn=cmd_gate)
    sp5 = gsub.add_parser("status")
    sp5.set_defaults(fn=cmd_gate)

    sp = sub.add_parser("ask", help="human-gate ASK queue")
    asub = sp.add_subparsers(dest="sub", required=True)
    sp2 = asub.add_parser("create")
    sp2.add_argument("--subject", required=True)
    sp2.add_argument("--question", required=True)
    sp2.add_argument("--options", default="")
    sp2.add_argument("--actor", default="lane")
    sp2.set_defaults(fn=cmd_ask)
    sp3 = asub.add_parser("list")
    sp3.set_defaults(fn=cmd_ask)
    sp4 = asub.add_parser("answer", help="answer a PENDING ask (status flip + decision log)")
    sp4.add_argument("ask", help="ask file, basename, or unique prefix")
    sp4.add_argument("--answer", required=True)
    sp4.add_argument("--actor", default="operator")
    sp4.set_defaults(fn=cmd_ask)

    sp = sub.add_parser("pool",
                        help="read-only registry of every lane in the pool")
    sp.add_argument("--paths", default=None,
                    help="comma-separated extra lane paths (repo-relative ok)")
    sp.set_defaults(fn=cmd_pool)

    sp = sub.add_parser("dispatch",
                        help="conflict-aware multi-lane parallel scheduler")
    sp.add_argument("--paths", default=None,
                    help="comma-separated extra lane paths (repo-relative ok)")
    sp.add_argument("--dry-run", action="store_true",
                    help="plan only: would_dispatch lines, zero writes")
    sp.add_argument("--max-parallel", type=int, default=None,
                    help="cap concurrent dispatches (default: unbounded)")
    sp.add_argument("--builder-timeout", type=int, default=None)
    sp.add_argument("--verify-timeout", type=int, default=None)
    sp.set_defaults(fn=cmd_dispatch)

    sp = sub.add_parser("observe", help="mechanical second-checker (stable output)")
    sp.add_argument("--log-dir", default=None)
    sp.add_argument("--stale-secs", type=int, default=None)
    sp.set_defaults(fn=cmd_observe)

    sp = sub.add_parser("version", help="print version")
    sp.set_defaults(fn=cmd_version)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except queue_state.QueueError as e:
        print(f"queue error: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except gate.GateError as e:
        print(f"gate error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
