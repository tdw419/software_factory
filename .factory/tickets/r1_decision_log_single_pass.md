# TICKET — r1: Single-pass decision_log.un_abortedgos

## Charter
`ROADMAP.md` — Rung r1 (v0.3.0 self-hosting shakedown).

## Goal
Refactor `decision_log.un_abortedgos(repo, kind)` in `software_factory/decision_log.py` to compute un-aborted GO records in a single pass over `read_all(repo)` instead of calling `read_all(repo)` twice, while preserving exact GO/abort pairing semantics even if an abort record appears before or after its target GO timestamp.

## Stages (probe → RED → GREEN → receipt)
- stage-0 (disruption 0): inspect `software_factory/decision_log.py` (`read_all` and `un_abortedgos`) and `tests/test_state.py`.
- stage-1 RED: add a unit test in `tests/test_state.py` using `monkeypatch` to count `decision_log.read_all` invocations during `un_abortedgos(repo, "scanout")` and assert `call_count == 1` (fails on current code where `call_count == 2`).
- stage-2 GREEN: update `un_abortedgos` in `software_factory/decision_log.py` to read `recs = read_all(repo)` once, collect `aborted` timestamps and `gos` in memory, and return un-aborted GO records in order; verify `/usr/bin/python3.12 -m pytest tests/ -q` passes.
- stage-3: write `.factory/receipts/r1_RECEIPT.md` with paired command/output fences and a `## What this does NOT prove` section, land rung `r1` via `factory ticket set r1 --status LANDED --commit <sha>`, update `- Rung r1` in `ROADMAP.md` to `[LANDED]`, and commit.

## Constraints
- Lane rules 0–10 apply (see `.factory/queue_state.json`).
- Do NOT touch `software_factory/gate.py` or `software_factory/tick.py` (Rule 10: recursion guard).
- Enumerate exact paths in `git add`.

## Measured state (do not re-derive)
- Baseline suite: `/usr/bin/python3.12 -m pytest tests/ -q` -> `55 passed`.
- `software_factory/decision_log.py` lines 55–64 currently iterate `for r in read_all(repo):` twice inside `un_abortedgos()`.
