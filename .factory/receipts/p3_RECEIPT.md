# RECEIPT — p3: factory dispatch conflict-aware multi-lane parallel scheduler

## What PASS proves
`pool.plan_dispatch` selects conflict-free rungs across all discovered pool
lanes in discovery order: it seeds `in_flight_files` from every lane's
`IN_PROGRESS` `files`, resumes a claimed rung regardless of conflicts, emits
`dispatch_skipped: <lane> reason=parked|file_conflict|max_parallel` lines,
skips a lane entirely when its HEAD `OPEN` rung overlaps in-flight work
(because `tick.py` is kernel-frozen and calls `next_actionable(q)` without
`in_flight_files`), stays silent on idle lanes, and registers each selected
rung's `files` into `in_flight` mid-pass so one pass can never double-book a
touch surface. `pool.dispatch` + `factory dispatch` run the selected lanes'
ticks concurrently on a `ThreadPoolExecutor` (per-lane `.factory/tick.lock`
keeps lanes mutually exclusive), support `--dry-run` (zero writes),
`--max-parallel`, `--builder-timeout`, `--verify-timeout`, and return 0 only
when every dispatched tick exited 0. RED was shown first: all 11 dispatch
tests fail at the claim commit `8aef078` (plan_dispatch/dispatch absent).

## Commands and outputs (paired in the same fence)
```bash
# RED leg — dispatch tests at the claim commit (plan_dispatch/dispatch missing)
$ git worktree add /tmp/p3_red_check 8aef078
$ cd /tmp/p3_red_check && /usr/bin/python3.12 -m pytest tests/test_pool.py -k dispatch -q
FAILED tests/test_pool.py::test_plan_dispatch_skips_lane_whose_head_open_conflicts
FAILED tests/test_pool.py::test_plan_dispatch_selects_two_nonconflicting_lanes
11 failed, 8 deselected in 0.92s

# GREEN — full suite at the work commit 6d2086bcaa443ffa937190b1e8964a0328ae0d87
$ /usr/bin/python3.12 -m pytest tests/
................                                                         [100%]
160 passed in 46.85s

# Live two-lane pool (/tmp/p3_demo.sh): laneA + laneB, same fake land builder
# [1] both lanes OPEN t1 files=shared.py — dry-run conflicts
$ factory dispatch --repo repoA --dry-run
dispatch_skipped: laneB reason=file_conflict
would_dispatch: laneA rung=t1 files=shared.py
dispatched=0

# [2] non-conflicting lanes, capped at one concurrent tick (real run)
$ factory dispatch --repo repoA --max-parallel 1
dispatch_skipped: laneB reason=max_parallel
dispatched_lane: laneA rung=t1 exit=0 msg=WAKE rung t1: builder ok, verify skipped, head 25a5fee3ce13 -> 74dc8f2fb948
dispatched=1

# [3] fresh non-conflicting rungs on both lanes — true parallel dispatch
$ factory dispatch --repo repoA
dispatched_lane: laneA rung=t2 exit=0 msg=WAKE rung t2: builder ok, verify skipped, head 74dc8f2fb948 -> cdc21f230bf0
dispatched_lane: laneB rung=t1 exit=0 msg=WAKE rung t1: builder ok, verify skipped, head 25a5fee3ce13 -> 0b7ce5de88bc
dispatched=2

# [4] end-state: every dispatched rung actually LANDED on its own lane
repoA {'t1': 'LANDED', 't2': 'LANDED'}
laneB {'t1': 'LANDED', 't2': 'OPEN'}
```

## What this does NOT prove (proof-limiting section — required)
- `tick.py` is untouched: a lane whose HEAD `OPEN` rung conflicts is skipped
  whole — dispatch never teaches a lane to run its second, conflict-free
  `OPEN` rung past a conflicting head. That needs a kernel edit (out of scope
  here by design).
- No shared verify worker pool: each dispatched tick runs its own verify
  inline (`p4`, requires a `kernel_edit` GO).
- The 11-test RED leg proves the gate can fail; it does not prove every
  scheduling edge (e.g. unreadable queue_state lanes, config-declared lanes)
  is exercised by a dedicated case — those paths are covered only by p1's
  discovery tests.
- Parallelism is thread-level concurrency across lanes; no wall-clock
  speedup was measured against a serialized baseline.
- The live demo used a stub builder (`land` mode); it proves scheduling and
  lock discipline, not real builder/verify work inside the ticks.
