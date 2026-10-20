# TICKET — p3: factory dispatch (conflict-aware multi-lane parallel scheduler)

## Charter
With `p1` (`pool.discover`) and `p2` (`files` metadata + `files_overlap` +
`next_actionable(q, in_flight_files=...)`) in place, `p3` builds the
multi-lane scheduler (`factory dispatch`) that selects conflict-free rungs
across $K$ lanes in a pool and runs their ticks concurrently — with zero edits
to `tick.py` (`kernel_paths`).

## Goal
1. **Conflict-aware scheduling (`pool.plan_dispatch(repo, extra_paths=(), max_parallel=None)`)**:
   - Discover pool lanes via `pool.discover(repo, extra_paths=extra_paths)`.
   - Seed `in_flight_files` with the union of `r.get("files") or []` across
     all rungs with `status == "IN_PROGRESS"` in every discovered lane.
   - Iterate through discovered lanes in order:
     - If a lane is `PARKED`, emit `dispatch_skipped: <lane> reason=parked` and
       continue.
     - Load the lane's `queue_state.json`.
     - Check if the lane has a claimed `IN_PROGRESS` rung (`resuming=True`);
       if so, select it regardless of `in_flight_files`.
     - Otherwise, check if the lane has any `OPEN` rungs at all; if none,
       continue silently (idle lane).
     - If the lane has `OPEN` rungs, call
       `queue_state.next_actionable(q, in_flight_files=in_flight_files)`.
       - If it returns `(None, False)` (meaning every `OPEN` rung on this lane
         overlaps `in_flight_files`), emit
         `dispatch_skipped: <lane> reason=file_conflict` and continue.
       - If it returns `(rid, False)` where `rid` is NOT the first `OPEN` rung
         on that lane (i.e. an earlier `OPEN` rung on the same lane was
         skipped due to conflict), remember that `tick.run_tick(lane_repo)`
         calls `next_actionable(q)` without `in_flight_files` (since `tick.py`
         is kernel-frozen). Therefore, if the first `OPEN` rung on `lane`
         conflicts with `in_flight_files`, emit
         `dispatch_skipped: <lane> reason=file_conflict` (so `run_tick` can
         never be launched onto a lane whose head-of-queue `OPEN` rung
         conflicts with another active lane!).
     - When a lane is selected for `(rid, resuming)`:
       - If `max_parallel is not None` and `len(selected) >= max_parallel`,
         emit `dispatch_skipped: <lane> reason=max_parallel` and continue.
       - Add `q["rungs"][rid].get("files") or []` to `in_flight_files`
         immediately so subsequent lanes in the same pass cannot select an
         overlapping rung.
       - Append `(lane_info, rid, resuming, files)` to `selected`.
2. **Execution (`pool.dispatch(repo, extra_paths=(), dry_run=False, max_parallel=None, builder_timeout=None, verify_timeout=None)`) & CLI `factory dispatch`**:
   - Wire `factory dispatch [--paths <csv>] [--dry-run] [--max-parallel <N>] [--builder-timeout <S>] [--verify-timeout <S>]` in `cli.py`.
   - When `dry_run=True`:
     - Print any `dispatch_skipped:` lines, then for each selected lane print:
       `would_dispatch: <lane> rung=<rid> files=<comma-joined-files-or-none>`
     - Print trailing `dispatched=0` and perform ZERO writes.
   - When `dry_run=False`:
     - Dispatch `tick.run_tick(lane_repo, builder_timeout=..., verify_timeout=...)`
       concurrently across all `selected` lanes using
       `concurrent.futures.ThreadPoolExecutor`.
     - Collect results in pool order and print any `dispatch_skipped:` lines,
       then per dispatched lane:
       `dispatched_lane: <lane> rung=<rid> exit=<code> msg=<msg>`
     - Print trailing `dispatched=<len(selected)>`.
     - Return exit code `0` if all dispatched ticks returned `0`, else the
       first non-zero exit code.

## Stages
- Probe (disruption 0): inspect `pool.py`, `queue_state.py`, `tick.py`,
  `cli.py`.
- RED: claim `p3` (`status="IN_PROGRESS"`, `claimed_by="hermes-cli"`) in the
  same commit as failing tests in `tests/test_pool.py` covering:
  1. Two non-conflicting lanes in a pool both selected and dispatched in
     parallel (`dispatched=2`, both land GREEN).
  2. Two lanes whose head `OPEN` rungs have overlapping `--files`: first lane
     dispatches, second lane emits `dispatch_skipped: <lane> reason=file_conflict`
     and is not ticked.
  3. An already `IN_PROGRESS` rung on Lane A blocks an overlapping `OPEN` rung
     on Lane B (`reason=file_conflict`).
  4. `--max-parallel 1` caps concurrent dispatches and emits
     `dispatch_skipped: <lane> reason=max_parallel`.
  5. `--dry-run` prints `would_dispatch:` + `dispatched=0` with zero writes.
- GREEN: implement in `pool.py` and `cli.py`; full test suite green.
- Receipt: write `.factory/receipts/p3_RECEIPT.md` with paired command/output
  fence and both required headings, mark `p3` `LANDED` with commit SHA, sync
  `ROADMAP.md`.

## Constraints
- Never modify `kernel_paths` (`software_factory/gate.py`,
  `software_factory/tick.py`).
- Per-lane mutual exclusion continues to rely on `.factory/tick.lock` inside
  `tick.run_tick`.

## What this does NOT prove
- Does not modify `tick.py` to skip a conflicting head-of-queue `OPEN` rung in
  favor of a second `OPEN` rung on the SAME lane; instead, `dispatch` skips
  that lane until the conflicting in-flight rung finishes (keeping `tick.py`
  untouched).
- Does not add a shared verify worker pool (`p4`, which requires a
  `kernel_edit` GO).
