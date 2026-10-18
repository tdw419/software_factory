# TICKET — r5: tick heartbeat staleness threshold

## Charter
`- Rung r5` (v0.4.0). `observe()` emits `tick_heartbeat=OK/missing` from `.factory/state.json`'s last tick timestamp, but "OK" is unbounded — a lane whose tick leg silently died two weeks ago still reads OK forever. A heartbeat cannot distinguish "did not fire" from "fired and died before writing"; a threshold makes the distinction mechanical.

## Goal
Add `observer.heartbeat_stale_after_min` to config (absent = current behavior, preserving byte-stability for existing lanes). When set, `observe()` emits `tick_heartbeat=OK|STALE|missing` by comparing the last tick timestamp against now minus the threshold. STALE is a state change, so the cron observer leg wakes the agent on it — that is the point.

## Constraints
- No timestamps in observer output beyond the existing bucketing rule (STALE is categorical, not a duration).
- Config absent → output byte-identical to today (regression-test this).
- RED-first in the claim commit (rule 0); receipt with paired commands/outputs; both required sections.
