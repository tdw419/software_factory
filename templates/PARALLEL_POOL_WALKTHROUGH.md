# Parallel Lane Pool & Conflict-Aware Dispatch Walkthrough

This walkthrough shows how to run multiple `software_factory` builder lanes in
parallel against one project, using the v0.9.0 scaling primitives:

- **p1** — `factory pool`: discover and read out a multi-worktree lane fleet.
- **p2** — `--files` conflict metadata: per-rung expected-touch paths with
  symmetric prefix/glob overlap matching (`files_overlap`).
- **p3** — `factory dispatch`: conflict-aware parallel dispatch across the
  fleet, with per-lane `tick.lock` and fleet-level `in_flight_files`
  partitioning working together.

All commands run from a lane repo root (where `software_factory/` lives).
Paths in `--paths` are comma-separated and may be repo-relative.

## 1. Worktree Fleet Setup

Each lane is a linked git worktree on its own branch, initialized with its own
`.factory/` state. `factory init` inside a linked worktree creates the lane's
queue/config without touching the primary tree.

```bash
# from the primary repo root (e.g. ~/projects/zion/projects/sf_next)
git worktree add ../sf_lane2 -b lane2
cd ../sf_lane2
factory init
cd -   # back to the primary lane

# repeat per lane:
git worktree add ../sf_lane3 -b lane3
cd ../sf_lane3 && factory init && cd -
```

Rules of thumb:

- One branch per lane (`lane2`, `lane3`, ...) so lane commits never interleave.
- Run `factory init` once per lane; it creates `.factory/queue_state.json`,
  `.factory/config.json`, and `.factory/decision_log.jsonl` local to the
  worktree.
- Never point two lanes at the same worktree path — `discover()` keys lanes
  by path.

Verify the fleet is visible before going further:

```bash
git worktree list
# /home/jericho/projects/zion/projects/sf_next  <sha> [next]
# /home/jericho/projects/zion/projects/sf_lane2 <sha> [lane2]
```

## 2. Pool Discovery (p1)

`factory pool` inspects every lane in the fleet: it reads each lane's
`queue_state.json`, `state.json`, and `config.json`, runs `git rev-parse`,
and asks the observer for a heartbeat. Output is stable (no timestamps),
one line per lane plus a trailing summary:

```bash
factory pool --paths ../sf_next,../sf_lane2
```

```text
lane: sf_next state=IN_PROGRESS active=fp2 heartbeat=<age>s branch=next worktree=/home/jericho/projects/zion/projects/sf_next
lane: sf_lane2 state=OPEN active=fp3 heartbeat=NO_RUNS branch=lane2 worktree=/home/jericho/projects/zion/projects/sf_lane2
lanes=2 active=2 parked=0
```

Readout format, per lane:

```
lane: <name> state=<state> active=<rung|-> heartbeat=<age|NO_RUNS> branch=<branch> worktree=<abs path>
```

and the trailing summary line:

```
lanes=<N> active=<A> parked=<P>
```

where `N` is lanes discovered, `A` counts lanes whose queue state is
`IN_PROGRESS` or `OPEN`, and `P` counts `PARKED` lanes. A lane on a branch
that has no upstream, or a worktree that fails to resolve, is skipped
cleanly rather than crashing the readout.

## 3. Declaring File Scope (p2)

Every rung carries a `files` list: the paths/globs it expects to touch.
Operators set it at ticket creation or amend it later — both accept a
comma-separated list:

```bash
factory ticket add --id fp2 --title "Fix gate message" \
  --ticket .factory/tickets/fp2.md --files software_factory/gate.py,tests/test_gate.py

factory ticket set fp2 --files software_factory/gate.py   # narrow the scope
```

Conflict detection is `files_overlap(files_a, files_b)` in
`software_factory/queue_state.py` — a **symmetric** expected-touch overlap
check:

- Empty/`None` on either side means *no declared touch surface* — never a
  conflict. An undeclared rung cannot be filtered on paths it didn't claim.
- Each entry is normalized (`./` stripped, trailing `/` stripped), then
  compared through the allowlist matcher's exact-match, directory-prefix,
  and `fnmatch` glob rules, in both directions.
- Exact or prefix overlap conflicts both ways:
  `software_factory` vs `software_factory/observer.py` → conflict.
- Path boundaries are respected: `foo` vs `foobar.py` → **no** conflict
  (prefix comparison stops at the `/`).

```python
from software_factory.queue_state import files_overlap
files_overlap(["templates/*"], ["templates/PARALLEL_POOL_WALKTHROUGH.md"])  # True
files_overlap(["foo"], ["foobar.py"])                                       # False
files_overlap([], ["anything"])                                             # False
```

Declare `files` as precisely as you can: over-broad globs (`templates/*`)
serialize every rung under that directory; precise paths let unrelated rungs
run concurrently.

## 4. Conflict-Aware Parallel Dispatch (p3)

`factory dispatch` plans and runs ticks across the whole pool in one shot:

```bash
# plan only — prints would_dispatch / dispatch_skipped lines, zero writes
factory dispatch --paths ../sf_next,../sf_lane2 --max-parallel 2 --dry-run

# live dispatch, at most 2 lanes ticking concurrently
factory dispatch --paths ../sf_next,../sf_lane2 --max-parallel 2
```

The planner seeds `in_flight_files` with the union of every lane's
IN_PROGRESS `files`, then extends it as each lane is selected. For each lane
in pool order:

- a claimed IN_PROGRESS rung is **resumed regardless of conflicts** (it
  already owns its work);
- an OPEN rung overlapping in-flight files is skipped;
- if the **head** OPEN rung conflicts, the whole lane is skipped with

  ```text
  dispatch_skipped: sf_lane2 reason=file_conflict
  ```

  Head-only skipping is deliberate: `tick.py` is kernel-frozen and calls
  `next_actionable(q)` *without* in-flight files, so launching a tick on a
  conflicted lane would run the conflicting rung anyway. The lane waits
  until the conflict clears, then dispatch picks it up.
- lanes beyond `--max-parallel` are skipped with `reason=max_parallel`;
  parked/unreadable lanes with `reason=parked` / `reason=unreadable`.

Dry-run output shape:

```text
dispatch_skipped: sf_lane2 reason=file_conflict
would_dispatch: sf_next rung=fp2 files=software_factory/gate.py
dispatched=0
```

### Why per-lane lock + fleet-level partitioning work together

Two mechanisms guard the same invariant — *a file is touched by at most one
running tick* — at different scopes:

- **Per-lane `tick.lock`**: a single lane can only run one tick at a time.
  This is the serialization point *within* a lane. Without it, two
  dispatches aimed at the same lane would both call `tick` and race on
  `queue_state.json`.
- **Fleet-level `in_flight_files`**: the planner's running union of every
  selected/resumed rung's `files`. It prevents *cross-lane* double-booking
  within a single dispatch pass: once lane A selects a rung touching
  `templates/*`, lane B's overlapping OPEN rung is excluded from
  consideration in the same pass.

Neither is sufficient alone. The per-lane lock knows nothing about other
lanes; the in-flight partition is only computed at plan time, so it cannot
stop a *second, later* dispatch from colliding with an already-running tick.
Together: the lock makes each lane's tick atomic, and the partition makes a
single dispatch pass conflict-free across lanes — plus head-OPEN skipping
guarantees the kernel-frozen `tick` never picks a rung the planner already
rejected.
