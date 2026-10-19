# TICKET — s1: factory diagnose (read-only self-diagnosis counter)

## Charter
`factory diagnose` — a deterministic pattern counter over the lane's own
decision history, printing findings on stdout. Same trust tier as the
observer: pure function, zero LLM calls, no writes to the repo.

- Scans `decision_log.read_all(repo)` + `decision_log.read_archived(repo)`
  deduped by ts — compaction-proof: `factory log compact --keep N` must not
  erase evidence that diagnose counts.
- Emits findings with deterministic signature keys
  (`failure_class:<pattern>`, `violation:<kind>`, `stall`, `parked`):
  per-class counts over a sliding window vs thresholds from
  `diagnose.thresholds` in config; absent config = fixed defaults and
  byte-stable output.
- Deduplicates against `queue_state.json`: a signature already covered by a
  rung in DRAFT/OPEN/IN_PROGRESS is skipped; a signature whose cited rung
  went LANDED after the last cited record ts may re-fire (recurrence after
  a purported fix is a new finding).
- stdout: one `finding: <signature> count=<n> evidence=<record-ids>` line
  per finding, then `findings=<n>`; zero findings prints `findings=0`.

## Constraints
- No file writes anywhere in the lane (s2 adds --draft with citations).
- kernel_paths untouched; thresholds absent-config behavior byte-stable.
- evidence=<record-ids> must cite real decision_log record identities.

## What this does NOT prove
- Does not draft tickets, flip anything OPEN, or judge code quality.
- Default thresholds are guesses until s2 evidence tunes them.
- Cannot see cron-layer or builder-side failures that never reach the log.
