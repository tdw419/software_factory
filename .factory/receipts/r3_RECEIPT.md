# RECEIPT — r3: ROADMAP.md supply-row status check in observer

## What PASS proves
`observer.observe()` now cross-checks the ladder file named by `digest.ladder.path`
in `.factory/config.json` (resolved via `common.resolve_ladder()`, the same source
`digest.compute()` hashes): for every `- Rung <id> [<STATUS>]: ...` line whose rung id
also exists in `queue_state.json`, a status mismatch is reported as
`ladder_drift=<comma-joined ids>` (sorted), agreement as `ladder_drift=none`. The line
is omitted entirely when the ladder is unconfigured or the file is missing, so lanes
without a ladder keep their previous output shape. The check is read-only and the
stdout tuple stays deterministic and timestamp-free. Full suite (62 tests) passes on
python3.12, including the two new RED-first tests.

## Commands and outputs (paired in the same fence)
```bash
# RED leg (before GREEN, commit 5868b64):
$ timeout 170 /usr/bin/python3.12 -m pytest tests/test_observer.py -q -k ladder
# FAILED tests/test_observer.py::test_ladder_in_sync_reports_none - KeyError: 'ladder_drift'
# FAILED tests/test_observer.py::test_ladder_drift_detected - KeyError: 'ladder_drift'
# 2 failed in 1.44s
```
```bash
$ timeout 170 /usr/bin/python3.12 -m pytest tests/
# ..............................................................            [100%]
# 62 passed in 6.23s
```

```bash
$ /usr/bin/python3.12 -c "
from software_factory import observer
d = dict(ln.split('=', 1) for ln in observer.observe('.'))
print('ladder line present:', 'ladder_drift' in d)
print(d.get('ladder_drift'))
"
# ladder line present: True
# r3
# (r3 itself: queue IN_PROGRESS vs ROADMAP [OPEN] at receipt-writing time — real drift, correctly surfaced)
```

## What this does NOT prove (proof-limiting section — required)
- Drift is only detected for rung ids present in BOTH the ladder file and
  queue_state.json — a rung line in ROADMAP.md with no queue rung (or vice versa)
  is silently ignored, not reported as drift.
- The parser is textual (`- Rung <id> [<STATUS>]` regex, configurable prefix); it does
  not parse Markdown, so non-standard ladder line shapes are skipped rather than
  flagged.
- It does not prove which side is right — drift is symmetric (stale ROADMAP and a
  rogue queue_state edit both surface as drift).
- It does not wake the lane by itself; the ladder file already hash-into
  digest.compute() (pre-existing), and this rung adds no wake logic.
- v0.3.0 self-hosting shakedown (the parent charter) is not proven by this rung alone.
