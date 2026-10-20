# RECEIPT — s3: observer surfaces self_drafts=N

## What PASS proves
`observer.observe()` emits `self_drafts=<N>` unconditionally on every run,
positioned immediately after the `receipts_missing=` / `receipts_incomplete=`
block. `N` counts rungs in `queue_state.json` with `origin == "self"` and
`status in ("DRAFT", "OPEN", "IN_PROGRESS")` — the identical predicate
`diagnose.py`'s `max_active_drafts` breaker counts, imported directly
(`COVERING_STATUSES`) rather than re-typed, so the observer readout and the
breaker cannot silently diverge. The line is computed purely from the rungs
dict `receipts_missing` already reads: no `digest.ladder` or any other
optional config block is required, and a legacy lane where no rung has an
`origin` field reads `self_drafts=0` (not missing, not an error). The
implementation is observer-only read-only instrumentation; `diagnose.py`'s
breaker logic is untouched.

## Commands and outputs (paired in the same fence)
```bash
$ timeout 120 /usr/bin/python3.12 -m pytest tests/test_observer.py -k self_drafts -q
# RED (commit 5b0c559, before the fix):
# FAILED tests/test_observer.py::test_self_drafts_counts_only_active_self_origin_rungs
# FAILED tests/test_observer.py::test_self_drafts_ignores_terminal_self_origin_rung
# FAILED tests/test_observer.py::test_self_drafts_legacy_lane_reports_zero - KeyError: 'self_drafts'
# 3 failed — the line did not exist; all three legs RED

$ timeout 170 /usr/bin/python3.12 -m pytest tests/ 2>&1 | grep -E "passed" | tail -1
# GREEN (commit e8c4dfa, after the fix):
# 126 passed in 7.89s

$ timeout 60 /usr/bin/python3.12 -m software_factory.cli --repo . observe | grep -n "self_drafts\|receipts"
# live lane, real queue (all rungs pre-date origin="self" -> legacy case):
# 25:receipts_missing=none
# 26:self_drafts=0
```

## What this does NOT prove (proof-limiting section — required)
- Does not implement the optional weekly cap (`max 3 self-drafts/week`) from
  the original self-diagnosis design note — that cap was flagged as
  non-blocking and can ride as its own rung or wait for the s4 gate.
- Does not change `--draft`'s behavior in any way; this rung is read-only
  instrumentation of state s2 already writes. The breaker population itself
  is unchanged (no diagnose.py edits).
- Does not evaluate whether any individual self-drafted rung is a *good*
  idea — that judgment remains the human veto at `DRAFT -> OPEN`, which this
  rung only makes easier to exercise promptly.
- Does not prove a nonzero live reading: the lane currently has zero
  self-origin rungs, so the `self_drafts=N` for N>1 path is proven by the
  synthetic-fixture test only, not yet by live telemetry.
