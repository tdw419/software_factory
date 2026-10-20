# RECEIPT — p5: builder tier label + ticket difficulty field

## What PASS proves
`builder.tier` (`.factory/config.json`, free-form string) and rung
`difficulty` (free-form, advisory) are pure visibility metadata with a
byte-stable absence contract. `observer.observe()` emits `builder=<tier>`
immediately after `tick_heartbeat=...` when the lane config carries a
non-empty stripped `builder.tier`, and `rung_<rid>_difficulty=<d>`
immediately after that rung's `status=`/`handle=` lines when the rung
carries a non-empty `difficulty`; absent/empty/whitespace values emit
nothing (verified live on this lane: zero new tokens, pool output
unchanged). `queue_state.register_rung`/`update_rung` store a stripped
difficulty (whitespace-only clears it) and record it in the
`rung_registered`/`rung_updated` decision_log payloads;
`factory ticket add/set --difficulty` wires it from the CLI following the
p2 `--files` / s2 `--covers` pattern; `pool.inspect_lane` returns
`difficulty` (active/head rung) + `builder_tier`, and `pool.findings`
appends `difficulty=<d>` after `active=` and `tier=<t>` after `heartbeat=`
only when truthy. RED was shown first: 7 of the 9 p5 tests fail at the
claim commit `b9c5f09` (the 2 passing are the byte-stability legs, which
pass trivially pre-change because the tokens are never emitted).

## Commands and outputs (paired in the same fence)
```bash
# RED leg — p5 tests at the claim commit b9c5f09 (implementation absent)
$ git worktree add /tmp/p5_red b9c5f09 && cd /tmp/p5_red
$ /usr/bin/python3.12 -m pytest -p no:warnings -k 'tier or difficulty'
FAILED tests/test_state.py::test_register_rung_stores_stripped_nonempty_difficulty
FAILED tests/test_cli.py::test_cli_ticket_difficulty_flag_and_decision_log
7 failed, 2 passed, 161 deselected in 0.55s
$ cd /home/jericho/projects/zion/projects/sf_next && git worktree remove --force /tmp/p5_red

# GREEN — full suite at the work commit 380688dc5ae3d82ea018233dc687512b71892f3e
$ timeout 170 /usr/bin/python3.12 -m pytest -p no:warnings
170 passed in 59.83s

# GREEN — the 9 p5 tests alone
$ timeout 170 /usr/bin/python3.12 -m pytest -p no:warnings -k 'tier or difficulty'
9 passed, 161 deselected in 7.58s

# Live probe (/tmp/p5_probe.py, stdlib + software_factory only)
# A: THIS lane, no builder.tier config, p5 has no difficulty -> byte-stable
$ /usr/bin/python3.12 /tmp/p5_probe.py
A1 builder= lines on live lane: []
A2 _difficulty= lines on live lane: []
A3 pool findings (live lane):
    lane: sf-next state=IN_PROGRESS active=p5 heartbeat=OK branch=next worktree=/home/jericho/projects/zion/projects/sf_next
    lane: sf-pilot2 state=IDLE active=none heartbeat=STALE branch=pilot2 worktree=/home/jericho/projects/zion/projects/sf_pilot2
    lanes=2 active=1 parked=0
A4 inspect_lane difficulty/builder_tier: None None
# B: fixture lane, builder.tier="local", t9 LANDED difficulty=mechanical,
#    d9 OPEN difficulty=fuzzy -> tokens in the specified positions
B1 fixture tier/difficulty observer lines:
    rung_t9_status=LANDED
    rung_t9_handle=BROKEN
    rung_t9_difficulty=mechanical
    rung_d9_status=OPEN
    rung_d9_difficulty=fuzzy
    tick_heartbeat=OK
    builder=local
B2 inspect_lane: {'difficulty': 'fuzzy', 'builder_tier': 'local'}
# C: tier set to whitespace, d9 difficulty emptied -> both tokens vanish
#    (t9's mechanical difficulty remains, correctly still set)
C1 after emptying tier+difficulty, residual tokens: ['rung_t9_difficulty=mechanical']
fixture cleaned
```

## What this does NOT prove (proof-limiting section — required)
- Does NOT prove a local model (qwen2.5-coder or any other) can pass this
  product's verify gate + rule-0 claim discipline on a real rung. That is
  a live builder trial with its own receipt; this rung ships the labels
  and routing guidance only, and README says local-tier lanes stay
  lower-trust until such a trial lands.
- Does NOT implement difficulty-based routing or load balancing:
  `factory dispatch`'s greedy conflict-free assignment is unchanged and
  never reads `difficulty`; which lane a rung opens in remains the
  operator's supply-time decision.
- `builder.tier` and `difficulty` are unvalidated free-form labels — PASS
  proves placement/omission of the tokens, not that any consumer
  interprets their vocabulary (`"local"` vs `"cloud"`,
  `"mechanical"` vs `"fuzzy"` are conventions, not enforced values).
- `difficulty` on a non-active rung surfaces in `observer.observe()` (all
  rungs) but `pool.inspect_lane` reports only the active/head rung's
  difficulty; per-rung difficulty for non-active rungs has no pool view.
- No local builder was exercised end-to-end (not even via `run_shell`);
  the fixture probe mutates config/queue_state JSON only and never
  invokes a builder or the verify gate.
