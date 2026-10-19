# TICKET — r7: suppressed-tick heartbeat persistence

## Charter
r5's `tick_heartbeat=OK|STALE|missing` reads `.factory/state.json`'s last-tick
timestamp, but a SUPPRESSED tick (no-op fingerprint match) writes nothing —
only a dispatched (WAKE) tick updates the timestamp today. That means
`tick_heartbeat` actually measures "time since last builder dispatch," not
"is the tick leg alive." A tick leg that silently dies (cron job removed,
process crash, permission error before reaching the lock) is indistinguishable
lane-side from a lane that's simply quiet because there's no work — both read
whatever the last WAKE happened to write, forever.

## Goal
Every tick invocation — SUPPRESSED, WAKE, or FAIL — persists a `last_tick_ts`
to `.factory/state.json` before returning, independent of whether work was
dispatched. `observer.heartbeat_stale_after_min` (from r5) then measures
tick-leg liveness, not dispatch recency: a tick leg that stops firing goes
STALE within the threshold even if the lane has had no actionable work the
whole time.

## Constraints
- Write `last_tick_ts` under the same `tick.lock` flock the tick already
  holds — no new lock surface.
- Byte-stability regression: a lane with `observer.heartbeat_stale_after_min`
  unset must keep emitting exactly today's `tick_heartbeat=OK|missing`
  vocabulary (this rung only changes what feeds the STALE threshold calc,
  not the legacy no-threshold output).
- Do not conflate "last tick ran" with "last tick dispatched a builder" in
  any user-facing observer line — if both are useful, they must be two
  distinct, separately named fields, not an overload of one.
- RED-first in the claim commit (rule 0); receipt with paired commands/
  outputs; both required sections (`## What PASS proves`,
  `## What this does NOT prove`).
- Non-kernel: this touches `tick.py`'s *state bookkeeping*, not its lock/
  park/verify-gate logic — stay out of the paths the kernel guard watches,
  or if truly unavoidable, flag it explicitly rather than silently crossing.
