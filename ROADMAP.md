# software_factory — v0.3.0 Self-Hosting Ladder

This repository's `next` worktree (`../sf_next`) self-hosts v0.3.0 development
under the `sf-next` lane. The digest hashes lines starting with `- Rung` so
status edits on this ladder wake the lane even when `queue_state.json` is
untouched.

## Governance & Kernel-Freeze Contract

- **Sovereign main**: All autonomous ticks run in `../sf_next` (`next` branch).
  Merge-back to `main` is manual by the operator after reading receipts.
- **Pinned oracle**: Verification runs `/usr/bin/python3.12 -m pytest tests/ -q`
  (the system `python3` is 3.14 without `pytest`).
- **Recursion guard (Rule 10)**: The builder must NEVER autonomously modify
  `gate.py` GO-spend accounting or `tick.py` lock/park/verify-gate logic
  without an armed and operator-fired GO gate (`kind="kernel_edit"`).

## Ladder

- Rung r1 [LANDED]: Single-pass `decision_log.un_abortedgos` + corrupt-line resilience (`.factory/tickets/r1_decision_log_single_pass.md`)
- Rung r2 [LANDED]: CLI `factory receipt validate <path>` subcommand + paired-fence check (`.factory/tickets/r2_receipt_validate_cli.md`)
- Rung r3 [LANDED]: `ROADMAP.md` supply-row status check in observer (`.factory/tickets/r3_ladder_sync.md`)

### v0.4.0 — seeded by operator 2026-10-18 (DRAFT; open via `factory ticket set <id> --status OPEN`)

- Rung r4 [LANDED]: decision_log compaction guard — `factory log compact --keep N`, archive + GO-spend survival (`.factory/tickets/r4_log_compaction.md`)
- Rung r5 [LANDED]: tick heartbeat staleness threshold — `tick_heartbeat=STALE` when `observer.heartbeat_stale_after_min` exceeded (`.factory/tickets/r5_heartbeat_stale.md`)
- Rung r6 [LANDED]: allowlist glob patterns via fnmatch, exact/prefix semantics preserved (`.factory/tickets/r6_allowlist_globs.md`)
