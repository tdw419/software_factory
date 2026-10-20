# RECEIPT — p1: factory pool (read-only multi-lane registry)

## What PASS proves
`software_factory/pool.py` discovers every lane in the pool deterministically
and read-only: `git worktree list --porcelain` in git's emitted order, then
`.factory/config.json` `pool.lanes` (relative paths resolved against the
repo), then caller/CLI `extra_paths` — deduplicated by `Path(p).resolve()`
preserving first-seen order, keeping only directories whose
`.factory/queue_state.json` is a regular file (bare product worktrees such as
`main` skip cleanly). `pool.inspect_lane()` returns the six-field readout
(`lane`/`worktree`/`branch`/`state`/`active_rung`/`heartbeat`): lane from
queue_state.json (`UNREADABLE` on corrupt JSON), branch from
`git rev-parse --abbrev-ref HEAD` (`UNREADABLE` on git error), state
classified PARKED > IN_PROGRESS > OPEN > IDLE (parked read from
`.factory/state.json`), `active_rung` from `queue_state.next_actionable`
(`"none"` when None), heartbeat taken verbatim from `observer.observe()` on
that lane with the lane's own `observer.stale_secs` /
`observer.heartbeat_stale_after_min` config engaged. `pool.findings()` /
`pool.run()` print one stable line per lane plus the trailing
`lanes=N active=A parked=P` summary, and the whole surface performs ZERO
writes (verified below by mtime_ns+size snapshot diff over `.factory/`, and
over the test tree in-suite, `.git` internals excluded because `git status`'
opportunistic index stat-cache refresh is git-native, not a factory write).
CLI: `factory pool [--paths <csv>]`.

## Commands and outputs (paired in the same fence)
```bash
$ timeout 170 /usr/bin/python3.12 -m pytest tests/test_pool.py -q
# RED (commit 0752d0e, before the fix — suite claimed p1 in the same commit):
# ImportError: cannot import name 'pool' from 'software_factory'
# ERROR tests/test_pool.py — Interrupted: 1 error during collection

$ timeout 170 /usr/bin/python3.12 -m pytest tests/test_pool.py -q
# GREEN (commit 1ea1db8, after the fix):
# ........                                                                 [100%]
# 8 passed — worktree discovery + non-lane skip, pool.lanes/--paths dedup by
# resolved path, IDLE/OPEN/IN_PROGRESS/PARKED + corrupt-queue UNREADABLE,
# active_rung (claimed IN_PROGRESS resume leg), heartbeat propagation
# (STALE via config threshold, NO_RUNS legacy vocabulary, byte-equal to
# observer.observe()), findings line format + summary counts, zero-write
# snapshot diff, CLI `factory pool` + `--paths`, and a
# python3.12 -m software_factory.cli subprocess leg

$ timeout 170 /usr/bin/python3.12 -m pytest tests/ -q
# full suite: 134 passed, 0 failed (pre-existing failures absorbed: none)

$ timeout 60 python3 -m software_factory.cli --repo . pool
# live lane:
# lane: sf-next state=IN_PROGRESS active=p1 heartbeat=OK branch=next worktree=/home/jericho/projects/zion/projects/sf_next
# lanes=1 active=1 parked=0

$ python3 - (snapshot .factory/ mtime_ns+size before/after live `factory pool`)
# exit 0
# zero-write: OK
```

## What this does NOT prove (proof-limiting section — required)
- Does not filter conflicting rungs across lanes — p2 adds `--files` and
  symmetric overlap filtering; `findings()` only reports per-lane state.
- Does not dispatch ticks across lanes — p3 adds `factory dispatch`; nothing
  here invokes the builder or takes any `tick.lock`.
- Does not prove concurrent-lane readout under live contention (the live pool
  currently has one lane); multi-lane legs are proven by synthetic fixtures
  (worktree lane2 + plain-dir lane3), not by two simultaneously-ticking lanes.
- Zero-write is proven for paths the factory owns (working tree + `.factory/`)
  plus in-suite whole-tree diff excluding `.git`; `git status` inside
  `observer.observe()` may opportunistically refresh git's own index stat
  cache, which is git-native behavior outside this module's control.
- Does not validate `pool.lanes` entries beyond path resolution: a configured
  path that is not a lane directory is silently skipped (by design), with no
  warning surfaced.
