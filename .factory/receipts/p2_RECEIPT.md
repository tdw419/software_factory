# RECEIPT — p2: rung conflict metadata (--files) + symmetric overlap filter

## What PASS proves
`queue_state.files_overlap(files_a, files_b)` implements the r6 matcher
(exact match, directory-prefix boundary via `common.is_under_allowlist`,
`fnmatch` globs via the same path) symmetrically, returning `False` when
either side is empty/`None`; `register_rung`/`update_rung` accept and persist
an optional `files` list; `factory ticket add/set --files` pass comma-
separated paths through to it; `next_actionable(q, in_flight_files=())`
skips `OPEN` rungs whose `files` overlap the in-flight set (picking the next
non-conflicting `OPEN` rung in insertion order, or `(None, False)` when all
conflict) while never skipping an already-claimed `IN_PROGRESS` rung, and the
default single-argument call `next_actionable(q)` is preserved
(`software_factory/tick.py:142` unchanged — zero kernel edits: no diff
touches `software_factory/tick.py` or `software_factory/gate.py` between
db4f6e5^ and 8d8fea3).

## Commands and outputs (paired in the same fence)
```bash
$ git worktree add /tmp/p2red db4f6e5 && cd /tmp/p2red && \
  /usr/bin/python3.12 -m pytest tests/test_conflict_files.py 2>&1 | tail -1
# ============================== 15 failed in 0.21s ==============================
# (RED leg: 15 gate tests fail against pre-p2 code; the p2 commit message said
#  "17 failing tests" — measured count at db4f6e5 is 15, stated here as measured)

$ /usr/bin/python3.12 -m pytest tests/test_conflict_files.py 2>&1 | tail -1
# 15 passed in 0.17s

$ /usr/bin/python3.12 -m pytest 2>&1 | tail -1
# 149 passed in 46.26s   (full suite green, zero pre-existing failures absorbed)

$ git log --oneline db4f6e5^..8d8fea3 -- software_factory/tick.py software_factory/gate.py
# (empty output — kernel_paths untouched across RED+GREEN)
```

## What this does NOT prove (proof-limiting section — required)
- `files` declarations on tickets are advisory metadata authored by the
  ticket creator; p2 does NOT prevent a builder from touching an undeclared
  file during execution.
- Single-lane `factory tick` calls `next_actionable(q)` without cross-lane
  `in_flight_files`; cross-lane conflict gating is exercised by p3
  (`factory dispatch`), which is still DRAFT.
- Overlap matching is syntactic (path/glob normalization), not semantic: two
  lanes declaring disjoint `files` may still conflict in practice (imports,
  shared config), and p2 does not detect that.
- The 149-test green run does not cover runtime concurrency; all conflict
  behavior is verified via unit-level `next_actionable` calls, not parallel
  ticks.
