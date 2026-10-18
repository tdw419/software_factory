# RECEIPT — r4: decision_log compaction guard

## What PASS proves
The mechanical gate proves: the 7 RED legs in tests/test_log_compact.py now
pass alongside the pre-existing 62 (69/69 total, zero regressions), i.e.
compact() moves entries beyond the newest N to
.factory/decision_log.archive.jsonl preserving oldest-first order on both
sides, emits exactly one `log_compacted` record with kept/archived counts,
is a no-op (no archive file, no record, exit 0) when total <= keep, refuses
keep < 1 with exit 2, refuses with exit 8 while any process holds
.factory/tick.lock via the same flock a tick takes, `un_abortedgos` still
finds a GO in the archive window (spend-blocks a re-fire; an abort appended
to the LIVE log pairs by ts with the ARCHIVED GO), and the observer emits a
stable bucketed `log_archive=yes/no` line. The CLI surface
(`factory log compact [--keep N]`) was additionally exercised end-to-end on
a scratch lane with the commands shown below, including a lock refusal via
an external `flock` holder.

## Commands and outputs (paired in the same fence)
```bash
# full suite after the fix (claim commit had all 7 legs RED: AttributeError compact/read_archived)
/usr/bin/python3.12 -m pytest -q
# .....................................................................    [100%]
# 69 passed (62 pre-existing + 7 new), 0 failed
```

```bash
# scratch lane: 10 records, compact --keep 4
/usr/bin/python3.12 -m software_factory.cli log compact --keep 4
# {"kept": 4, "archived": 6, "keep": 4, "archive": "decision_log.archive.jsonl"}
# exit=0
wc -l .factory/decision_log.jsonl .factory/decision_log.archive.jsonl
# 5 .factory/decision_log.jsonl   (4 kept + the log_compacted record)
# 6 .factory/decision_log.archive.jsonl
/usr/bin/python3.12 -m software_factory.cli log --tail 2
# {"actor": "t", "n": 9, "ts": "..."}
# {"actor": "lane", "log_compacted": {"kept": 4, "archived": 6, ...}, "ts": "..."}
```

```bash
# observer bucket flips only when the archive exists
/usr/bin/python3.12 -m software_factory.cli observe | grep log_archive
# log_archive=yes            (scratch lane, after compact)
# log_archive=no             (this lane, no archive yet)
```

```bash
# locked refusal: external flock holder on the scratch lane
flock .factory/tick.lock -c 'factory log compact --keep 4; echo exit=$?'
# {"compact_error": "refused: a factory tick holds tick.lock"}
# exit=8
```

```bash
# REAL lane (this repo): the parent tick that launched this builder session
# (PID 235901, run 2026-10-18T193719.543063+0000-r4) holds tick.lock, so the
# live-lane compact was refused by the real constraint, not a test fixture:
/usr/bin/python3.12 -m software_factory.cli log compact; echo "exit=$?"
# {"compact_error": "refused: a factory tick holds tick.lock"}
# exit=8
# 17 .factory/decision_log.jsonl   (untouched — well under keep=2000 anyway)
```

```bash
# gate the receipt itself passes the fence gate
/usr/bin/python3.12 -m software_factory.cli receipt validate .factory/receipts/r4_RECEIPT.md
# .factory/receipts/r4_RECEIPT.md: ok
```

## What this does NOT prove (proof-limiting section — required)
- Not proven: operator adoption. On this lane compact() can never run from
  INSIDE a tick (the parent tick holds the lock for the builder's whole
  lifetime) — wiring compact into the tick loop is out of scope; a cron or
  the operator must invoke `factory log compact` between ticks.
- Not proven: crash-safety of the two-phase write. The archive append and
  the live atomic rewrite are not in one transaction; a kill between them
  leaves each GO duplicated in both files. The ts-dedupe in un_abortedgos
  makes that harmless for spend accounting (covered by reasoning, not by a
  crash-injection test).
- Not proven: un_abortedgos is still ONE read of each file — the r1
  single-pass test wraps read_all only; read_archived is a second file
  read by design (archive + live), so the r1 test's call-count==1 contract
  is preserved but total I/O is now proportional to archive size too.
- Not proven: performance. The ticket's motivation (read_all cost) is not
  benchmarked; compaction bounds the LIVE log only, and gate preflight
  still scans archive + live.
- Not proven: concurrent compact() vs compact() — mutual exclusion relies
  on the same flock, and the loser gets exit 8, but simultaneous compactions
  were not race-tested.
