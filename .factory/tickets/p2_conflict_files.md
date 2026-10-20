# TICKET — p2: rung conflict metadata (--files) + symmetric overlap filter

## Charter
When two lanes in a pool run concurrently against the same repository, two
builders editing overlapping files will create a merge war at milestone
merge-back. `p2` adds deterministic expected-touch path metadata (`files`) to
rungs and a symmetric path/glob overlap filter on `queue_state.next_actionable`
— keeping `tick.py` (`kernel_paths`) completely untouched.

## Goal
1. **Rung `files` metadata (`queue_state.py` + `cli.py`)**:
   - `queue_state.register_rung(...)` and `queue_state.update_rung(...)`
     accept an optional `files=None` parameter (validated as a list of
     non-empty path/glob strings; persisted as `files: [...]` on the rung when
     provided).
   - `factory ticket add` and `factory ticket set` accept
     `--files <path[,path...]>` (comma-separated, stripped of whitespace and
     empty items) and pass the list through to `queue_state`.
2. **Symmetric path/glob overlap (`queue_state.files_overlap(files_a, files_b) -> bool`)**:
   - Return `False` if either `files_a` or `files_b` is empty/`None`.
   - Normalize entries with `common._strip_dot_slash(p.strip()).rstrip("/")`.
   - Two entries `a` and `b` overlap if:
     - `a == b`, OR
     - `common.is_under_allowlist(a, [b])`, OR
     - `common.is_under_allowlist(b, [a])`
     (This reuses `r6`'s exact, directory-prefix boundary, and `fnmatch` glob
     matcher symmetrically so `"software_factory"` and
     `"software_factory/observer.py"`, or `"tests/test_*.py"` and
     `"tests/test_pool.py"`, always conflict regardless of argument order,
     while `"foo"` and `"foobar.py"` never false-conflict.)
3. **Conflict-filtered `queue_state.next_actionable(q: dict, in_flight_files=())`**:
   - Default `in_flight_files=()` preserves 100% backward compatibility with
     `tick.py:142`'s single-argument call `queue_state.next_actionable(q)`
     (zero kernel edits).
   - An already-claimed `IN_PROGRESS` rung (`resuming=True`) is NEVER skipped
     by `in_flight_files` (it already owns its in-flight work).
   - When `in_flight_files` is non-empty, an `OPEN` rung whose
     `r.get("files")` overlaps `in_flight_files` via `files_overlap()` is
     skipped so the next non-conflicting `OPEN` rung in insertion order is
     returned (or `(None, False)` if all `OPEN` rungs conflict).

## Stages
- Probe (disruption 0): inspect `queue_state.py`, `common.py`, `cli.py`.
- RED: claim `p2` (`status="IN_PROGRESS"`, `claimed_by="hermes-cli"`) in the
  same commit as failing tests in `tests/test_pool.py` (or
  `tests/test_conflict_files.py`) covering:
  1. `files_overlap` symmetry across exact paths, directory prefixes vs nested
     files, path-boundary non-matches (`foo` vs `foobar.py`), and `r6` globs.
  2. `factory ticket add --files` and `factory ticket set --files`.
  3. `next_actionable(q, in_flight_files=...)` skipping conflicting `OPEN`
     rungs to pick a later non-conflicting `OPEN` rung, returning
     `(None, False)` when all `OPEN` rungs conflict, and never skipping a
     claimed `IN_PROGRESS` rung.
- GREEN: implement in `queue_state.py` and `cli.py`; full test suite green.
- Receipt: write `.factory/receipts/p2_RECEIPT.md` with paired command/output
  fence and both required headings, mark `p2` `LANDED` with commit SHA, sync
  `ROADMAP.md`.

## Constraints
- Never modify `kernel_paths` (`software_factory/gate.py`,
  `software_factory/tick.py`).
- Calling `next_actionable(q)` with one argument must behave byte-identically
  to pre-`p2`.

## What this does NOT prove
- `files` declarations on tickets are advisory metadata authored by the
  ticket creator; `p2` does not prevent a builder from touching an undeclared
  file during execution.
- Single-lane `factory tick` calls `next_actionable(q)` without cross-lane
  `in_flight_files`; cross-lane conflict gating is exercised by `p3`
  (`factory dispatch`).
