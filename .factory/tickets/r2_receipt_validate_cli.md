# TICKET — r2: CLI receipt validate subcommand + paired-fence check

## Charter
`ROADMAP.md` — Rung r2 (v0.3.0 self-hosting shakedown).

## Goal
Add `factory receipt validate <receipt_file>` to `software_factory/cli.py` and extend `common.validate_receipt()` to verify that the receipt includes at least one fenced code block (` ``` `) under `## Commands and outputs` in addition to `## What PASS proves` and `## What this does NOT prove`.

## Stages (probe → RED → GREEN → receipt)
- stage-0 (disruption 0): inspect `software_factory/common.py` (`validate_receipt`) and `software_factory/cli.py` (`build_parser`).
- stage-1 RED: write a test in `tests/test_cli.py` invoking `main(["--repo", str(repo), "receipt", "validate", ...])` on a valid receipt (expect 0) and a receipt missing a code fence or required section (expect 1); run `/usr/bin/python3.12 -m pytest tests/ -q` to observe RED.
- stage-2 GREEN: implement `receipt validate` in `software_factory/cli.py` using `common.validate_receipt()`, update any test fixtures whose minimal receipts lack a fenced block if needed, and verify the full test suite passes.
- stage-3: write `.factory/receipts/r2_RECEIPT.md`, land rung `r2` in `queue_state.json` with the real commit SHA, update `ROADMAP.md`, and commit.

## Constraints
- Lane rules 0–10 apply (see `.factory/queue_state.json`).
- Do NOT touch `software_factory/gate.py` or `software_factory/tick.py` (Rule 10: recursion guard).

## Measured state (do not re-derive)
- `common.validate_receipt(path)` currently checks `## What PASS proves` and `## What this does NOT prove`.
- `factory ticket validate <ticket>` exists in `cli.py`, but there is no `factory receipt validate <receipt>` CLI command yet.
