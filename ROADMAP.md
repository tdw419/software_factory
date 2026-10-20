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

### v0.5.0 — seeded by operator 2026-10-18 (DRAFT; open via `factory ticket set <id> --status OPEN`)

- Rung r7 [LANDED]: observer heartbeat counts every persisted tick — freshness = max(runs/ mtime, `state.json:last_tick_ts`), observer-only (tick.py is a kernel path) (`.factory/tickets/r7_suppressed_tick_persistence.md`)

### v0.7.0 — seeded by operator 2026-10-19 (DRAFT; open via `factory ticket set <id> --status OPEN`)

- Rung s1 [LANDED]: `factory diagnose` read-only — mechanical failure-class counter over live + archived decision log (ts-deduped), signature-key findings, queue-dedup with recurrence re-fire (`.factory/tickets/s1_diagnose.md`)
- Rung s2 [LANDED] (c57fc78f74a4): `factory diagnose --draft` + `builder_timeout` bucket + CLI `--covers` — evidence-cited DRAFT tickets (`origin="self"`, `max_active_drafts` cap, ladder sync, non-kernel constraint) (`.factory/tickets/s2_diagnose_draft.md`)
- Rung s3 [LANDED] (e8c4dfa3cce8): observer surfaces `self_drafts=N` — same origin="self"+DRAFT/OPEN/IN_PROGRESS population `diagnose.py`'s breaker counts (COVERING_STATUSES imported, not re-typed), read-only, unconditional, legacy lanes report 0 (`.factory/tickets/s3_diagnose_observer_surface.md`)

### v0.9.0 — parallel lane scaling seeded by operator 2026-10-20 (DRAFT; open via `factory ticket set <id> --status OPEN`)

- Rung p1 [LANDED] (1ea1db8cb2ff): `factory pool` read-only multi-lane registry — discovers worktree + configured lanes, reports state/active/heartbeat/branch/worktree (`observer` trust tier, zero writes) (`.factory/tickets/p1_lane_pool.md`)
- Rung p2 [LANDED] (8d8fea3364c9): rung conflict metadata (`--files`) + symmetric path/glob overlap filter (`files_overlap`, `next_actionable(q, in_flight_files=...)`, zero kernel edits) (`.factory/tickets/p2_conflict_files.md`)
- Rung p3 [LANDED] (6d2086bcaa44): `factory dispatch` conflict-aware multi-lane parallel scheduler — `plan_dispatch` (in_flight seeding, resume-claimed, parked/file_conflict/max_parallel skips, head-OPEN lane skip) + concurrent `ThreadPoolExecutor` ticks, `--dry-run`, `--max-parallel`, zero kernel edits (`.factory/tickets/p3_parallel_dispatch.md`)

### v0.9.0 field pilot — seeded by operator 2026-10-20

- Rung fp1 [IN_PROGRESS]: `templates/PARALLEL_POOL_WALKTHROUGH.md` multi-lane operator walkthrough (`.factory/tickets/fp1_parallel_pool_walkthrough.md`)


