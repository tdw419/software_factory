# RECEIPT — r6: allowlist glob patterns

## What PASS proves
Allowlist entries containing glob metacharacters (`*`, `?`, `[`) now match via
`fnmatch.fnmatch` against the full lane-relative path in
`common._single_path_under_allowlist` — so `*.lock`, `audits/*.md`,
`audit?.md`, `run[0-9].txt` all work, and `scoped_dirty_rows()` inherits the
matcher (digest and observer share the one implementation through
`is_under_allowlist`). Entries WITHOUT metacharacters take the untouched
exact/`path/`-prefix branch, so existing configs behave identically: a
scratch lane's fingerprint computed pre-fix and post-fix is byte-identical
(same `stable`, same `parts` dict, dirty lane with churn + non-allowlisted
noise). A glob matching digest-needed files is safe: a ticket file suppressed
by `.factory/tickets/*.md` keeps TREE=CLEAN while the TICKETS hash still
moves the fingerprint via its dedicated channel (QUEUE/TICKETS/LADDER are
hashed independently of TREE in `digest.compute`).

## Commands and outputs (paired in the same fence)
```bash
$ git -C /home/jericho/projects/zion/projects/sf_next log --oneline -3
# 371f1d2 feat(r6): allowlist glob patterns — entries with *?[ match via fnmatch.fnmatch against the full lane-relative path; entries without metacharacters keep exact/prefix (scratch-lane digest byte-identical pre/post); scoped_dirty_rows inherits the matcher (digest+observer, one implementation); glob-suppressed ticket files still move TICKETS channel
# 61572e1 claim(r6) + RED: allowlist glob tests — 6 legs fail (fnmatch matching absent: *.local.json, audits/*.md, audit?, run[0-9] never match, scoped_dirty_rows leaks glob files, TICKETS-channel safety untestable); 2 no-glob regression legs pass RED (existing semantics already correct); claims r6 IN_PROGRESS per rule 0
# daa5dcc chore(bookkeeping): pre-existing factory churn — operator opened r6 (DRAFT->OPEN, ROADMAP sync, decision_log 20:47:35Z) + factory-tick counters from r5 landing (20:46:05Z); provenance per rule 9

$ git -C /home/jericho/projects/zion/projects/sf_next worktree add ~/../.hermes/cache/scratch/r6_red 61572e1
$ cd /home/jericho/.hermes/cache/scratch/r6_red && timeout 165 /usr/bin/python3.12 -m pytest tests/test_allowlist_globs.py -q   # RED, at claim commit 61572e1
# FAILED tests/test_allowlist_globs.py::test_glob_dir_pattern_suppresses_wake
# FAILED tests/test_allowlist_globs.py::test_glob_bracket_class
# FAILED tests/test_allowlist_globs.py::test_scoped_dirty_rows_uses_same_matcher
# FAILED tests/test_allowlist_globs.py::test_glob_question_mark_is_single_char
# FAILED tests/test_allowlist_globs.py::test_glob_allowlisted_ticket_still_moves_TICKETS_channel
# FAILED tests/test_allowlist_globs.py::test_glob_entry_suppresses_wake
# 6 failed, 2 passed in 0.23s
# (the 2 passing legs are the no-glob regression legs — existing exact/prefix semantics were already correct; the negative leg is RED before the fix)

$ timeout 165 /usr/bin/python3.12 -m pytest tests/ -q --tb=no   # GREEN, at fix commit 371f1d2
# ........................................................................ [ 87%]
# ..........                                                               [100%]
# exit=0

$ timeout 60 /usr/bin/python3.12 -m pytest tests/ --collect-only -q
# tests/test_allowlist_globs.py: 8
# tests/test_cli.py: 8
# tests/test_digest.py: 9
# tests/test_gate.py: 8
# tests/test_log_compact.py: 7
# tests/test_observer.py: 22
# tests/test_state.py: 6
# tests/test_tick_e2e.py: 14
# (82 collected, 82 passed — pre-r6 baseline was 74/74, all 74 still pass)

$ cd /home/jericho/.hermes/cache/scratch/r6_regress/lane && /usr/bin/python3.12 -c "
from software_factory.digest import compute
fp = compute('.'); print(fp.stable); import json; print(json.dumps(fp.parts, sort_keys=True))"
# BEFORE fix (PYTHONPATH at claim-state code): ceb982943942e94b
#   {"HEAD": "42487b787948", "QUEUE": "f20550d341bbab74", "TICKETS": "599b464747d9c1ac", "TREE": "bc8f4c087e2c59b3"}
# AFTER fix (PYTHONPATH at 371f1d2 code):
#   ceb982943942e94b
#   {"HEAD": "42487b787948", "QUEUE": "f20550d341bbab74", "TICKETS": "599b464747d9c1ac", "TREE": "bc8f4c087e2c59b3"}
$ diff digest_before.txt digest_after.txt && echo DIGEST_BYTE_IDENTICAL
# DIGEST_BYTE_IDENTICAL   (scratch lane, default allowlist — no glob entries — identical fingerprint)

$ cd /home/jericho/.hermes/cache/scratch/r6_regress/lane && /usr/bin/python3.12 -c "
from software_factory.common import scoped_dirty_rows
ok, rows = scoped_dirty_rows('.')
for r in rows: print(r)"
# ?? .factory/.gitignore
# ?? .factory/config.json
# ?? .factory/decision_log.jsonl
# ?? .factory/queue_state.json
# ?? .factory/receipts/_TEMPLATE.md
# ?? .factory/templates/OBSERVER_PROMPT.md
# ?? .factory/templates/PROMPT_TEMPLATE.md
# ?? .factory/tickets/_TEMPLATE.md
# ?? audits/other.txt
# ?? notes.txt
$ git status --porcelain -uall | wc -l
# 12
# (scratch config churn_allowlist was set to ['*.lock', 'audits/*.md', 'notes/']: poetry.lock and
#  audits/scan.md are suppressed by the glob entries — 12 raw rows -> 10 scoped rows, observer
#  tree=DIRTY(10); audits/other.txt and notes.txt correctly still wake; .factory/* rows correctly
#  still show because that replacement allowlist does not list them)

$ git -C /home/jericho/projects/zion/projects/sf_next diff 61572e1..371f1d2 --stat -- software_factory/gate.py software_factory/tick.py
# (empty — recursion guard rule 10: no kernel surfaces touched)
```

## What this does NOT prove (proof-limiting section — required)
- Not proved that fnmatch `*` matching across path separators is the desired
  semantic for every lane: `audits/*.md` also matches `audits/nested/deep.md`
  (fnmatch has no `**` distinction). Lanes wanting strict one-level depth
  cannot express it; the behavior is documented in the code comment, not
  configurable.
- Not proved for glob entries interacting with the rename format
  (`old -> new`): the rename split tests cover non-glob entries only; a glob
  matching both sides of a rename was not separately tested.
- Not proved that every existing production lane's config.json is glob-free;
  byte-identity was measured on a synthetic scratch lane with the DEFAULT
  allowlist plus churn, not against every live lane (this repo's config was
  not modified).
- Case sensitivity follows fnmatch.fnmatch (OS-normcase): on case-insensitive
  filesystems globs would match case-insensitively; only Linux (case-
  sensitive) was tested.
- PASS does not prove a glob like `*` (match-everything) is safe to configure
  — it would suppress all TREE wake signal; only that QUEUE/TICKETS/LADDER
  channels remain independent, which was shown for the TICKETS channel alone.
- The observer demo ran via `scoped_dirty_rows` directly and `factory
  observe`; the change-gated cron wiring consuming that output is outside
  this repo and was not exercised.
