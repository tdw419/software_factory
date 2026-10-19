# RECEIPT — s1: factory diagnose (read-only self-diagnosis counter)

## What PASS proves
`factory diagnose` is a deterministic, write-free counter over the lane's
own decision history: it scans decision_log live + archive deduped by ts
(compaction-proof), classifies tick_failed/gate_refused/rung_demoted
records into fixed signature buckets (failure_class:<pattern>,
violation:<kind>, stall, parked), counts per class over a sliding window
against configurable thresholds with fixed byte-stable defaults, dedupes
against queue_state.json rung `covers` entries (DRAFT/OPEN/IN_PROGRESS
suppress; a LANDED covering rung re-fires when the newest evidence
postdates landed_at), and prints one `finding:` line per signature plus
`findings=<n>`. The 18-test suite proves each signature, the threshold
and window config, ts-dedup across the crash-window duplicate, archive
survival across a real `factory log compact`, and byte-stability with no
config. On the real sf-next lane it currently prints `findings=0`.

## Commands and outputs (paired in the same fence)
```bash
# RED leg (before diagnose.py existed):
timeout 170 /usr/bin/python3.12 -m pytest tests/test_diagnose.py -q
# ImportError: cannot import name 'diagnose' from 'software_factory'
# =========== 1 error during collection ===========  (RED, commit 1488436)

# GREEN leg — s1 suite:
timeout 170 /usr/bin/python3.12 -m pytest tests/test_diagnose.py 2>&1 | tail -1
# 18 passed in 0.42s

# Full suite (real gate cmd, under the 170s rule-8 timeout):
timeout 170 /usr/bin/python3.12 -m pytest tests/ 2>&1 | tail -1
# 117 passed in 7.73s

# Real lane, read-only invocation:
/usr/bin/python3.12 -m software_factory diagnose
# findings=0

# Receipt self-check:
/usr/bin/python3.12 -m software_factory receipt validate .factory/receipts/s1_RECEIPT.md
# .factory/receipts/s1_RECEIPT.md: ok
```

## What this does NOT prove (proof-limiting section — required)
- Does not draft tickets, flip anything OPEN, or judge code quality — s2
  adds --draft with citations; diagnose writes nothing anywhere.
- Default thresholds (failure_class=2, violation=1, stall=3, parked=1)
  and window=50 are guesses until s2 tunes them against real evidence.
- Cannot see cron-layer or builder-side failures that never reach the
  decision log (e.g. suppressed ticks never append records).
- The `covers` dedup convention is defined here (rung key
  `covers: [<signature>, ...]`); no rung has declared coverage yet, so
  that path is proven by tests only, not by live-lane history.
- violation:kernel_edit detection keys on rung_demoted reason text; a
  kernel guard violation surfaced only via the observer tuple (not the
  log) is invisible to diagnose.
