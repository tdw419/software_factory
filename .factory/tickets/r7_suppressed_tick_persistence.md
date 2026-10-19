# TICKET — r7: heartbeat counts every persisted tick (observer-only)

## Charter
`observer.observe()` computes tick freshness from `.factory/runs/` mtimes
only. But `state.json:last_tick_ts` is persisted by EVERY finishing tick
(suppressed, degraded, WAKE no_actionable — `finish()` -> `save_state()`);
only PARKED and dry_run skip it. The signals disagree exactly when a
WAKE no_actionable fires (state written, no runs marker): the observer then
reports a heartbeat older than reality. STALE must mean "no successful tick
execution in N minutes", so freshness = max(latest runs/ mtime, parsed
`state.json:last_tick_ts`).

Supersedes the original charter of this ticket (2026-10-18), whose premise
was inverted: it claimed suppressed ticks write nothing and asked tick.py to
start writing them. save_state already persists last_tick_ts on
suppressed/degraded/no_actionable paths; the actual gap is observer-side.

## Constraints
- observer.py ONLY. `software_factory/tick.py` is a kernel path
  (kernel_paths is file-granular); do not touch it. No kernel_edit GO is
  needed or wanted for this rung.
- When `observer.heartbeat_stale_after_min` is ABSENT from config, observer
  output must stay byte-identical (legacy OK/STALL/NO_RUNS vocabulary —
  the r5 contract).
- Do not conflate "last tick ran" with "last tick dispatched a builder" in
  one overloaded field — if both are useful they stay separately named.
- RED-first in the claim commit (rule 0); receipt with paired
  commands/outputs; both required sections (`## What PASS proves`,
  `## What this does NOT prove`).

## Stages
- probe: read observe() heartbeat computation + the r5 test legs.
- RED: with `heartbeat_stale_after_min` armed, a fresh `last_tick_ts` plus
  stale runs/ mtimes must yield OK (fails today: reports STALE); a missing
  or unparseable state.json must leave behavior unchanged; legacy-vocab
  byte-stability legs keep passing.
- GREEN: minimal change inside observe().
- receipt: `.factory/receipts/r7_RECEIPT.md` with both required sections.

## What this does NOT prove
- Does not detect cron-layer silent no-ops (a scheduler leg completing "ok"
  without executing its command) any faster than the STALE threshold fires —
  that is wiring, not lane code (proven by the 2026-10-18 dead-air window,
  16:30 -> 18:16 CDT, caught by STALL at 18:16).
- PARKED and dry_run ticks still write nothing (kernel-guarded file).
- Does not measure dispatch quality — a heartbeat is liveness, not health.
