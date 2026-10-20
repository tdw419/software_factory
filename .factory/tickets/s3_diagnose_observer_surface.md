# TICKET — s3: observer surfaces self_drafts=N

## Charter
`s2` shipped `factory diagnose --draft`, the product's first self-writing
feature: it autonomously registers `DRAFT` rungs with `origin == "self"`,
gated by the `max_active_drafts` circuit breaker. The human-veto-at-DRAFT
checkpoint (self-drafts accumulate, operator reviews, flips `OPEN` or adds a
`covers` entry to veto) only works if the veto-holder can *see* drafts
accumulating. Today that requires hand-reading `queue_state.json` — the
observer, the lane's one instrument meant to be read on a cron cadence
(`factory observe`), says nothing about self-origin rungs at all. Writes
(`--draft`) have shipped ahead of their visibility instrumentation; this rung
closes that gap before v0.8.0 ships both together.

## Goal
`observer.observe()` emits a new deterministic line:

    self_drafts=<N>

where `N` is the count of rungs in `queue_state.json` with `origin == "self"`
and `status in ("DRAFT", "OPEN", "IN_PROGRESS")` — the exact same population
`diagnose.py`'s `max_active_drafts` breaker counts, so the two numbers can
never silently disagree. Emit the line unconditionally (not gated on any
config flag) immediately after the existing `receipts_missing=...` /
`receipts_incomplete=...` block, so a lane with zero self-drafts reads
`self_drafts=0` rather than omitting the line — a human scanning the 20-minute
cron readout should never have to distinguish "no self-drafts" from
"this build predates self_drafts" by absence.

## Constraints
- observer.py ONLY. Do not touch `diagnose.py`'s breaker logic itself — s3
  reads the same population `s2` already counts, it does not change what
  counts.
- Must not require `digest.ladder` or any other optional config block to be
  present; `self_drafts` is computed purely from `queue_state.json`'s rungs,
  same input `receipts_missing` already reads.
- Legacy lanes (no rung ever has `origin` set) must report `self_drafts=0`,
  not `missing` or an error — absence of the field on every rung is the
  common case today and must read as zero, not a failure.
- RED-first in the claim commit (rule 0); receipt with paired
  commands/outputs; both required sections (`## What PASS proves`,
  `## What this does NOT prove`).

## Stages
- probe: read `observe()`'s rung-iteration loop (where `rung_<id>_status`
  and `receipts_missing` are built) and `diagnose.py`'s `max_active_drafts`
  counting logic, to reuse the identical origin/status predicate.
- RED: a queue with 2 self-origin DRAFT/OPEN rungs and 1 self-origin LANDED
  rung must report `self_drafts=2`; a queue with zero `origin` fields must
  report `self_drafts=0`; a queue with a self-origin rung in a terminal
  state outside DRAFT/OPEN/IN_PROGRESS must not count it.
- GREEN: minimal addition inside `observe()`.
- receipt: `.factory/receipts/s3_RECEIPT.md` with both required sections.

## What this does NOT prove
- Does not implement the optional weekly cap (`max 3 self-drafts/week`) from
  the original self-diagnosis design note — that cap was flagged as
  non-blocking and can ride as its own rung or wait for the s4 gate.
- Does not change `--draft`'s behavior in any way; this is read-only
  instrumentation of state `s2` already writes.
- Does not evaluate whether any individual self-drafted rung is a *good*
  idea — that judgment remains the human veto at `DRAFT -> OPEN`, which this
  rung only makes easier to exercise promptly.
