# RECEIPT — r1: Single-pass decision_log.un_abortedgos

Rung: r1 · Lane: sf-next · Work commit: e1d2701
RED/claim commit: cdd2168

## What PASS proves

`un_abortedgos(repo, kind)` in `software_factory/decision_log.py` calls
`read_all(repo)` exactly once: the new `test_un_abortedgos_single_pass`
monkeypatches `decision_log.read_all`, counts invocations, and asserts
`call_count == 1` — shown RED (assert 2 == 1) against the old two-pass
code before the refactor, GREEN after. The full suite is green, and a
probe confirms GO/abort pairing is by ts value, not file order: an
abort record physically before or after its target GO line both remove
the GO from the result, matching the old semantics.

## What was changed

`un_abortedgos(repo, kind)` in `software_factory/decision_log.py` previously
called `read_all(repo)` twice (one pass to collect aborted ts values, a second
to collect GO records). It now reads the log once, collecting abort ts values
and GO records in the same scan, then filters GOs whose ts was aborted.
GO/abort pairing is by ts value, not file order, so both loops were merged
without changing semantics — including the pathological case of one record
carrying both `{kind}_go` and `{kind}_go_aborted` keys (kept as two
independent `if` checks, not `elif`, for that reason).

## Commands and outputs (paired)

### stage-1 RED — new test fails on old code

```
$ timeout 150 /usr/bin/python3.12 -m pytest tests/test_state.py::test_un_abortedgos_single_pass --timeout=60
>       assert calls["n"] == 1
E       assert 2 == 1
tests/test_state.py:34: AssertionError
FAILED tests/test_state.py::test_un_abortedgos_single_pass - assert 2 == 1
1 failed in 0.13s
```

### stage-2 GREEN — same test passes on new code

```
$ timeout 150 /usr/bin/python3.12 -m pytest tests/test_state.py::test_un_abortedgos_single_pass tests/test_state.py::test_go_abort_pairing --timeout=60
..                                                                       [100%]
2 passed in 0.13s
```

### Full suite after fix

```
$ timeout 150 /usr/bin/python3.12 -m pytest tests/ --timeout=120
58 passed in 6.14s
```

(Baseline measured at tick start: `57 passed in 6.12s`. The ticket quoted 55;
the scaffold commit added 2 since that measurement. +1 test = 58. No
pre-existing failures absorbed.)

### Pairing semantics — abort before AND after target GO ts

Probe script rewrote the log so an abort line physically precedes its GO
line, then ran the normal order:

```
abort-before-GO -> ['GO-B']
abort-after-GO -> []
OK: pairing holds both orders
```

## What this does NOT prove

- That a record carrying BOTH `{kind}_go` and `{kind}_go_aborted` keys
  behaves identically — the double-`if` preserves the old code's handling
  by inspection, but no test exercises that pathological record.
- Single-pass performance. No benchmark was run; the change is structural
  (halved full-log reads), not measured.
- Thread/interleaving safety: `read_all` still snapshots the file once;
  a GO appended between two `un_abortedgos` calls is simply not seen, as
  before. Nothing new is proven about concurrent appends.
- That `read_all`'s JSON error path (ValueError on line N) is unaffected —
  it was not touched and not re-tested beyond the existing suite.
- That the fix holds for kinds other than "scanout" — the test suite only
  exercises "scanout" (unchanged coverage from before this ticket).
