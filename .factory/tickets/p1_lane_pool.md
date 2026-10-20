# TICKET — p1: factory pool (read-only multi-lane registry)

## Charter
The factory's unit of parallelism is the lane (each in its own git worktree or
`watch_paths`-scoped subtree, protected by its own `.factory/tick.lock`).
Before adding cross-lane conflict filtering (`p2`) or concurrent multi-lane
scheduling (`p3`), the operator and scheduler need a deterministic, read-only
registry of every lane in the pool — the same instrumentation-first pattern
that proved out in `s1 -> s2 -> s3`.

## Goal
1. Create `software_factory/pool.py` and wire `factory pool` into
   `software_factory/cli.py`.
2. **Discovery (`pool.discover(repo, extra_paths=())`)**:
   - Parse `git -C <repo> worktree list --porcelain` (`worktree <path>` lines)
     in git's emitted order.
   - Append any paths configured in `.factory/config.json` under
     `pool.lanes` (list of path strings; relative paths resolved against
     `repo`) and any `extra_paths` passed by the caller / CLI `--paths`
     (comma-separated path list).
   - Deduplicate by `Path(p).resolve()` while preserving discovery order, and
     keep only directories where `.factory/queue_state.json` is a regular file
     (so bare product worktrees such as `main` without `.factory/` are
     skipped cleanly).
3. **Per-lane readout (`pool.inspect_lane(lane_repo)`)**:
   - Read-only inspection returning a dict with:
     - `lane`: `queue_state.json["lane"]` (or `"UNREADABLE"` if corrupt)
     - `worktree`: `str(Path(lane_repo).resolve())`
     - `branch`: `git -C <lane_repo> rev-parse --abbrev-ref HEAD` stripped
       (or `"UNREADABLE"` on git error)
     - `state`: `"PARKED"` if `.factory/state.json` has `"parked": true`;
       else `"IN_PROGRESS"` if any rung in `queue_state.json` has
       `status == "IN_PROGRESS"`; else `"OPEN"` if any rung has
       `status == "OPEN"`; else `"IDLE"`
     - `active_rung`: `rid` from `queue_state.next_actionable(q)[0]`, or
       `"none"` when `None`
     - `heartbeat`: the `tick_heartbeat` value from `observer.observe()` on
       that lane (passing that lane's `observer.heartbeat_stale_after_min`
       and `observer.stale_secs` from its `.factory/config.json` if present)
4. **Stable output (`pool.findings` / `pool.run(repo, extra_paths=())` & CLI `factory pool [--paths <csv>]`)**:
   - Print one line per discovered lane:
     `lane: <lane> state=<state> active=<active_rung> heartbeat=<heartbeat> branch=<branch> worktree=<worktree>`
   - Print a trailing summary line:
     `lanes=<N> active=<count of lanes with state in (IN_PROGRESS, OPEN)> parked=<count of lanes with state == PARKED>`
   - Perform ZERO writes anywhere on disk.

## Stages
- Probe (disruption 0): inspect `observer.py`, `queue_state.py`, `cli.py`, and
  how worktrees are structured.
- RED: claim `p1` (`status="IN_PROGRESS"`, `claimed_by="hermes-cli"`) in the
  same commit as a new `tests/test_pool.py` suite that fails (e.g.
  `ImportError: cannot import name 'pool'`) covering:
  1. Worktree discovery via `git worktree add` (skipping worktrees without
     `.factory/queue_state.json`, including worktrees with `.factory/`).
  2. `pool.lanes` config + `--paths` discovery and deduplication by resolved
     path.
  3. State classification (`IDLE`, `OPEN`, `IN_PROGRESS`, `PARKED`),
     `active_rung`, and `heartbeat` propagation.
  4. Zero-write guarantee and CLI `factory pool` invocation.
- GREEN: implement `software_factory/pool.py` and wire `factory pool` in
  `software_factory/cli.py`; all tests pass.
- Receipt: write `.factory/receipts/p1_RECEIPT.md` with paired command/output
  fence and both required headings, mark `p1` `LANDED` with commit SHA, sync
  `ROADMAP.md`.

## Constraints
- Never modify `kernel_paths` (`software_factory/gate.py`,
  `software_factory/tick.py`).
- `factory pool` must be 100% read-only (zero files created or modified).
- Stdlib only (Python >= 3.10).

## What this does NOT prove
- Does not filter conflicting rungs across lanes (`p2` adds `--files` and
  overlap filtering).
- Does not dispatch ticks across multiple lanes (`p3` adds `factory dispatch`).
