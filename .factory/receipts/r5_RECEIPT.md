# RECEIPT — r5: tick heartbeat staleness threshold

## What PASS proves
`observe()` accepts `heartbeat_stale_after_min`; when the caller passes it
(from `observer.heartbeat_stale_after_min` in `.factory/config.json`, wired
through `cli.cmd_observe`), the `tick_heartbeat` line becomes categorical
`OK|STALE|missing` — STALE when the newest `.factory/runs` mtime is older
than now minus the threshold, `missing` when the runs dir is empty/unreadable.
When the key is absent the legacy vocabulary (`OK/STALL/NO_RUNS`) and values
are byte-identical to pre-r5 behavior. STALE/missing are state changes, so
the change-gated cron observer leg wakes the agent on them. No timestamps
are emitted (categorical only), verified by the existing no-colon test.

## Commands and outputs (paired in the same fence)
```bash
$ git -C /home/jericho/projects/zion/projects/sf_next log --oneline -3
# 1e16dfb feat(r5): heartbeat staleness threshold — observer.heartbeat_stale_after_min engages tick_heartbeat=OK|STALE|missing (categorical, no timestamps); absent param keeps legacy OK/STALL/NO_RUNS byte-identical; cli.cmd_observe wires it from config
# 7684cf4 claim(r5) + RED: heartbeat staleness tests — 3 legs fail (observe() has no heartbeat_stale_after_min param: TypeError), byte-stability + legacy-vocab legs pass; claims r5 IN_PROGRESS per rule 0
# f06a6ae chore(bookkeeping): pre-existing factory churn — operator opened r5 (DRAFT->OPEN, decision_log 20:31:26Z) + factory-tick counters from r4 landing (19:55:30Z); provenance per rule 9

$ timeout 165 /usr/bin/python3.12 -m pytest tests/ -q --tb=no   # RED run, at claim commit 7684cf4, heartbeat legs only
# FAILED tests/test_observer.py::test_heartbeat_missing_when_no_runs_and_threshold_set - TypeError: observe() got an unexpected keyword argument 'heartbeat_stale_after_min'
# FAILED tests/test_observer.py::test_heartbeat_ok_when_within_threshold - TypeError: ...
# FAILED tests/test_observer.py::test_heartbeat_stale_when_threshold_exceeded - TypeError: ...
# (byte-stability and legacy-vocabulary legs passed RED: the negative leg is shown before the fix)

$ timeout 165 /usr/bin/python3.12 -m pytest tests/ -q --tb=no   # GREEN, at fix commit 1e16dfb
# ........................................................................ [ 97%]
# ..                                                                       [100%]
# exit=0  (74 collected per --collect-only: test_cli 8, test_digest 9, test_gate 8,
#  test_log_compact 7, test_observer 22, test_state 6, test_tick_e2e 14 — 74/74 pass)

$ cd /tmp/r5demo && touch -d "1 hour ago" .factory/runs/.keep && factory observe | grep tick_heartbeat   # CLI, config WITHOUT the key
# tick_heartbeat=OK            (legacy behavior byte-identical)

$ python3 -c "import json; c=json.load(open('.factory/config.json')); c['observer']['heartbeat_stale_after_min']=5; json.dump(c,open('.factory/config.json','w'),indent=2)"
$ factory observe | grep tick_heartbeat   # same 1h-old runs, threshold=5min
# tick_heartbeat=STALE

$ rm .factory/runs/.keep && factory observe | grep tick_heartbeat
# tick_heartbeat=missing

$ git -C /home/jericho/projects/zion/projects/sf_next diff 34bd57c..1e16dfb --stat -- software_factory/gate.py software_factory/tick.py
# (empty — recursion guard rule 10: no kernel surfaces touched)
```

## What this does NOT prove (proof-limiting section — required)
- Not proved that the cron observer leg actually wakes on STALE in
  production — that depends on the scheduler's change-gating wiring, which
  is outside this repo; only that STALE is emitted as a state change.
- Not proved for lanes with no `.factory/runs` directory at creation-time —
  `missing` covers empty/unreadable via the same OSError path, but a lane
  where the runs dir is deleted mid-flight was not separately tested.
- Not proved against a real two-week-old stall: staleness was simulated with
  backdated mtimes (os.utime / touch -d), not a live long-running lane.
- The threshold is only honored when the operator adds the config key; no
  lane in this repo currently sets `observer.heartbeat_stale_after_min`, so
  live observer output is unchanged until then (by design, byte-stability).
- PASS does not prove the legacy STALL/NO_RUNS branches are dead code — they
  remain the default path and are covered by the pre-existing suite only in
  the NO_RUNS case.
