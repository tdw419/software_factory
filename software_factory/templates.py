"""Embedded defaults for materialized lane files.

Single source of truth: `factory init` materializes these into .factory/;
the repo-root templates/ directory mirrors them as readable docs. Builder
contract text encodes the live lane's rules 1/2/5/7/10.
"""

PROMPT_TEMPLATE = """# Lane tick — {lane} — rung {rung_id}{resuming}

You are the builder for this lane tick. Repository: {repo}
{resuming_note}
## Ticket
{ticket_body}

## Lane rules (binding)
{rules}

## Builder contract
- Claim the rung FIRST: set status=IN_PROGRESS, claimed_by, claimed_at in
  .factory/queue_state.json (or via `factory ticket set {rung_id} --status IN_PROGRESS --claimed-by <agent>`),
  IN THE SAME COMMIT as your first work commit.
- COMMIT PER SUB-STEP: never hold finished sub-steps in the tree.
- COMMIT SCOPE: enumerate exact paths; never `git add -A` or bare `git add .`.
- RED-first: prove the verification gate can fail before trusting GREEN.
- Write the receipt at {receipt_path}: commands and outputs PAIRED in the
  same fence, with exact section headings `## What PASS proves` and
  `## What this does NOT prove` (follow .factory/receipts/_TEMPLATE.md).
- Land the rung in queue_state.json: status=LANDED, landed_at, and
  commit=<the real sha> (or `factory ticket set {rung_id} --status LANDED --commit <sha>`).
  NEVER the prose "this commit".
- End the tick with a commit even if only decisions landed (infra_notes).
"""

TICKET_TEMPLATE = """# TICKET — {rung_id}: {title}

## Charter
<roadmap / ladder file this ticket serves, with pointers>

## Goal
<smallest measurable outcome — one sentence>

## Stages (probe → RED → GREEN → receipt)
- stage-0 (disruption 0): measure/probe only, no code.
- stage-1 RED: prove the verification gate FAILS on the unfixed state.
- stage-2 GREEN: implement; gate passes on the real target (not just a mirror).
- stage-3: receipt + queue_state update + commit.

## Constraints
- Lane rules apply (see queue_state.json). Add ticket-specific ones here.

## Measured state (do not re-derive)
- <baselines the ticket author already measured>
"""

RECEIPT_TEMPLATE = """# RECEIPT — {rung_id}: {title}

## What PASS proves
<one paragraph>

## Commands and outputs (paired in the same fence)
```bash
<command>
# <actual output>
```

## What this does NOT prove (proof-limiting section — required)
- <named limits>
"""

OBSERVER_PROMPT_TEMPLATE = """# LLM observer leg — lane {lane}

You are the lane's SECOND CHECKER, not its builder. You never write to the
repo. Read the mechanical observer's output (factory observe), the queue,
the receipts, and the decision log, then append an entry to the OBS file:

1. PRIORS: quote the values the next tick needs from the previous entry.
2. HEARTBEAT: state what triggered this run (cron leg id, not re-hunted).
3. FINDINGS: measure, never inherit — every claim re-executed this tick.
4. COVERAGE: if you were down, measure the hole (census the runs dir), and
   attribute silence correctly: "did not fire" vs "fired and died" differ.
5. CORRECTIONS: if you mis-wrote a number, issue a correction AGAINST
   YOURSELF in the same entry, with stamps.
6. STATUS line: CLEAN or the named RED condition.

A log-only heartbeat cannot distinguish "did not fire" from "fired and died
before writing" — judge coverage from the run directory, never from your own
output alone.
"""

DEFAULT_CONFIG = {
    "lane": "lane",
    "operator": "operator",
    "builder": {
        "adapter": "shell",
        "cmd": "",
        "timeout_s": 1500,
    },
    "verify": {
        "cmd": "",
        "timeout_s": 170,
        "required": False,
    },
    "digest": {
        "churn_allowlist": [
            ".factory/decision_log.jsonl",
            ".factory/state.json",
            ".factory/runs/",
            ".factory/asks/",
            ".factory/pending_gate.json",
            ".factory/tick.lock",
        ],
        "ladder": {"path": "", "line_prefix": "- Rung"},
        "watch_paths": ["."],
    },
    "observer": {
        "stale_secs": 5400,
        "watch_rules": [],
    },
    "kernel_paths": [],
}
