# TICKET — r3: ROADMAP.md supply-row status check in observer

## Charter
`ROADMAP.md` — Rung r3 (v0.3.0 self-hosting shakedown).

## Goal
Teach `observer.observe()` to optionally cross-check `ROADMAP.md` ladder lines (`- Rung <id> [<STATUS>]: ...`) when `digest.ladder.path` is configured, emitting `ladder_drift=<rungs>` (or `none`) when a rung's status in `ROADMAP.md` disagrees with `queue_state.json`.

## Stages (probe → RED → GREEN → receipt)
- stage-0 (disruption 0): inspect `software_factory/observer.py` and `software_factory/digest.py` ladder handling.
- stage-1 RED: add a test in `tests/test_observer.py` where `queue_state.json` has `t1` `LANDED` while `ROADMAP.md` still says `- Rung t1 [OPEN]: demo`, asserting `ladder_drift=t1` in `observer.observe(repo)`; run pytest to see RED.
- stage-2 GREEN: implement ladder status drift detection in `software_factory/observer.py` when a ladder file exists, keeping stdout deterministic and timestamp-free; run `/usr/bin/python3.12 -m pytest tests/ -q` to confirm GREEN.
- stage-3: write `.factory/receipts/r3_RECEIPT.md`, land rung `r3` in `queue_state.json` with the real commit SHA, update `ROADMAP.md`, and commit.

## Constraints
- Lane rules 0–10 apply (see `.factory/queue_state.json`).
- Do NOT touch `software_factory/gate.py` or `software_factory/tick.py` (Rule 10: recursion guard).
- `observer.observe()` must remain strictly read-only.

## Measured state (do not re-derive)
- `digest.compute()` already reads `ladder = {"path": "ROADMAP.md", "line_prefix": "- Rung"}` from `.factory/config.json`.
