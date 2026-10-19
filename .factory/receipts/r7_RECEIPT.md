# RECEIPT — r7: heartbeat counts every persisted tick (observer-only)

## What PASS proves
With `observer.heartbeat_stale_after_min` armed, `observer.observe()` now
derives tick freshness from the NEWEST of its two persisted sources — the
latest `.factory/runs/` mtime and the parsed `.factory/state.json:last_tick_ts`
(written by `tick.finish() -> save_state()` on every finishing tick:
suppressed, degraded, and WAKE no_actionable; only PARKED and dry_run skip
it). A WAKE no_actionable (state written, no runs marker) therefore reports
`tick_heartbeat=OK` instead of a falsely STALE heartbeat. A missing or
unparseable `state.json` drops out of the max, leaving the pre-r7 runs-only
behavior, and when the config key is ABSENT the observer never reads
state.json at all — the r5 legacy vocabulary (OK/STALL/NO_RUNS, and
`missing` under an armed threshold with no source) is byte-identical. The
change is observer-only; `software_factory/tick.py` (kernel path) is
untouched (git show below names observer.py alone).

## Commands and outputs (paired in the same fence)
```bash
$ timeout 150 /usr/bin/python3.12 -m pytest tests/test_observer.py -q -k "state_ts or unparseable_state"
# RED (commit 97d09d4, before the fix):
# FAILED tests/test_observer.py::test_heartbeat_fresh_state_ts_no_runs_dir - As...
# FAILED tests/test_observer.py::test_heartbeat_fresh_state_ts_overrides_stale_runs
# (the two new-source legs fail; the missing/unparseable-state legs pass —
#  they pin the unchanged-behavior contract)

$ git show --stat --oneline 975dbf8 | head -4
# 975dbf8 r7 GREEN: armed heartbeat freshness = max(runs/ mtime, parsed state.json:last_tick_ts); missing/unparseable state drops out of the max; legacy no-config path untouched (runs mtimes only, NO_RUNS/STALL/OK vocabulary)
#  software_factory/observer.py | 45 +++++++++++++++++++++++++++++------------
#  1 file changed, 33 insertions(+), 12 deletions(-)

$ timeout 150 /usr/bin/python3.12 -m pytest tests/ -q
# ........................................................................ [ 72%]
# ...........................                                              [100%]
# 99 passed (full gate suite, including the r5 byte-stability legs
# test_heartbeat_config_absent_byte_stable and
# test_heartbeat_no_runs_legacy_vocabulary_unchanged, both still passing)

$ git status --porcelain | wc -l
# 0
```

## What this does NOT prove (proof-limiting section — required)
- Does not detect cron-layer silent no-ops (a scheduler leg completing "ok"
  without executing its command) any faster than the STALE threshold fires —
  that is wiring, not lane code (proven by the 2026-10-18 dead-air window,
  16:30 -> 18:16 CDT, caught by STALL at 18:16).
- PARKED and dry_run ticks still write nothing (kernel-guarded file); r7
  does not and cannot give them a heartbeat — the max only sees sources
  that were persisted.
- Does not measure dispatch quality — a heartbeat is liveness, not health.
- The two sources are read in one max() expression but remain unnamed
  separately in the output tuple; the observer still cannot distinguish
  "last tick ran" from "last tick dispatched a builder" at a glance — the
  constraint was honored by NOT merging them into a new overloaded field,
  not by adding a second categorical line (no such line was chartered).
- `last_tick_ts` is trusted as written by `tick.save_state()`; a future
  kernel change that stops persisting it on the no_actionable path would
  silently revert this rung's benefit (observer-side only, by design).
- Legacy (config-absent) output was verified by the existing r5 test legs,
  not by a byte-diff of observer stdout against a pre-r7 binary capture.
