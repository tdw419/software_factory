# RECEIPT — r2: CLI receipt validate subcommand + paired-fence check

## What PASS proves
`factory receipt validate <receipt>` exists in `software_factory/cli.py` and exits 0 on a
receipt carrying `## What PASS proves`, `## What this does NOT prove`, and at least one
fenced code block under `## Commands and outputs`; it exits 1 when the fence or a required
section is missing. `common.validate_receipt()` enforces the same fence rule for every
caller (tick post-check, observer), and `has_fenced_block_under()` implements the
section-scoped fence scan. The full suite (60 tests) passes on python3.12, and the
pre-existing r1 receipt still validates ok.

## Commands and outputs (paired in the same fence)
```bash
$ timeout 170 /usr/bin/python3.12 -m pytest tests/ -q
# ............................................................            [100%]
# 60 passed in <suite wall time> (full run shown in commit body of 616e893)
```

```bash
$ /usr/bin/python3.12 -m software_factory.cli --repo . receipt validate .factory/receipts/r1_RECEIPT.md
/home/jericho/projects/zion/projects/sf_next/.factory/receipts/r1_RECEIPT.md: ok
$ echo "rc=$?"
rc=0
```

```bash
# RED leg (before GREEN, commit e8936d7):
$ timeout 170 /usr/bin/python3.12 -m pytest tests/test_cli.py::test_cli_receipt_validate -q
# factory: error: argument cmd: invalid choice: 'receipt'
# FAILED tests/test_cli.py::test_cli_receipt_validate - SystemExit: 2
```

## What this does NOT prove (proof-limiting section — required)
- The fence scan is textual (section-scoped toggle on ``` lines); it does not parse
  Markdown — fences inside nested code spans or unusual indentation conventions may
  be counted differently than a strict Markdown parser would.
- It does not verify the commands in the receipt were actually run or that outputs are
  genuine — only that paired command/output evidence is structurally present.
- It does not prove the fence sits in every future receipt; only receipts written after
  this rung are gated by callers that use validate_receipt.
- v0.3.0 self-hosting shakedown (the parent charter) is not proven by this rung alone.
