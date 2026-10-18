# TICKET — r4: decision_log compaction guard

## Charter
`- Rung r4` (v0.4.0). `.factory/decision_log.jsonl` is append-only and grows unbounded; every tick appends a full record (wake, builder, verify, problems). On a long-lived lane this becomes the largest file in `.factory/` and every `read_all` scan pays for it.

## Goal
Add `factory log compact [--keep N]` (default N=2000): entries beyond the newest N move to `.factory/decision_log.archive.jsonl` (one-time rename-append, newest-first preserved), and `un_abortedgos` learns to scan archive + live log so GO-spend accounting survives compaction. Emit a `log_compacted` decision_log record documenting kept/archived counts. The observer must report `log_archive=yes/no` (bucketed, stable).

## Constraints
- Gate spend must NEVER be lost: any `go_fired`/`gate_armed`/abort records in the archive window still count via `un_abortedgos`.
- Compact must refuse to run while a tick holds `.factory/tick.lock` (exit 8) — take the same flock.
- RED-first in the claim commit (rule 0); receipt with paired commands/outputs; both required sections.
