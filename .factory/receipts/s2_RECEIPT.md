# RECEIPT — s2: factory diagnose --draft (evidence-cited self-drafting + CLI covers)

## What PASS proves
`diagnose` now classifies `"builder TIMEOUT after <N>s"` as the deterministic
`failure_class:builder_timeout` bucket (rule ordered before `builder exit`),
closing the empirical gap s1 found against the live geometry_os lane.
`queue_state.register_rung(...)`/`update_rung(...)` accept an optional
`covers` list, wired through `factory ticket add --covers` and
`factory ticket set <id> --covers` (comma-separated, empties stripped,
persisted as `covers: [...]`). `factory diagnose --draft` drafts at most one
`DRAFT` rung (status="DRAFT", origin="self", covers=[signature]) per
uncovered finding, subject to the `diagnose.max_active_drafts` circuit
breaker (default 2): every drafted ticket cites the finding's signature,
count, and exact evidence ts, contains ## Goal / ## Stages / ## Constraints
(kernel_paths edit ban) / ## What this does NOT prove — `validate_ticket()`
returns `[]` — appends the ladder line (observer then reports
`ladder_drift=none`), appends a `diagnose_drafted` provenance record to
decision_log, and because `covers` includes the signature, an immediate
re-run reports `findings=0` with zero duplicate drafts. Bare `diagnose`
remains read-only (0 dirty files after a run on a committed lane). Full
suite: 123 passed; diagnose suite: 24 passed.

## Commands and outputs (paired in the same fence)
```bash
# Gates — s2 diagnose suite and full suite (rule-8 timeout):
timeout 170 /usr/bin/python3.12 -m pytest tests/test_diagnose.py 2>&1 | grep -E "passed|failed"
# 24 passed in 0.53s
timeout 170 /usr/bin/python3.12 -m pytest tests/ 2>&1 | grep -E "passed|failed"
# 123 passed in 7.81s

# Demo lane: scratch fixture (NOT the live lane) seeded with two
# "builder TIMEOUT after 1500s" tick_failed records, ladder configured
# (digest.ladder = ROADMAP.md, line_prefix "- Rung"), max_active_drafts=1.

# 1. Classification fix:
/usr/bin/python3.12 -c 'from software_factory.diagnose import classify_problem; print(classify_problem("builder TIMEOUT after 1500s"))'
# builder_timeout

# 2. Bare diagnose — builder_timeout now its own bucket (was failure_class:builder):
/usr/bin/python3.12 -m software_factory --repo <demo> diagnose
# finding: failure_class:builder_timeout count=2 evidence=2026-10-19T15:00:00+00:00,2026-10-19T15:20:00+00:00
# findings=1

# 3. --draft — one DRAFT rung, post-draft findings:
/usr/bin/python3.12 -m software_factory --repo <demo> diagnose --draft
# drafted: auto_failure_class_builder_timeout covers=failure_class:builder_timeout ticket=.factory/tickets/auto_failure_class_builder_timeout_failure_class_builder_timeout.md
# findings=0

# 4. Idempotence — immediate re-run:
/usr/bin/python3.12 -m software_factory --repo <demo> diagnose
# findings=0

# 5. Drafted ticket cites signature/count/evidence and validates:
# (ticket body shows: signature: failure_class:builder_timeout / count: 2 /
#  evidence ts: 2026-10-19T15:00:00+00:00, 2026-10-19T15:20:00+00:00)
/usr/bin/python3.12 /tmp/vt.py   # queue_state.validate_ticket on the drafted file
# auto_failure_class_builder_timeout_failure_class_builder_timeout.md -> [] (valid)

# 6. Ladder sync:
tail -1 <demo>/ROADMAP.md
# - Rung auto_failure_class_builder_timeout [DRAFT]: Auto-draft: address failure_class:builder_timeout (.factory/tickets/auto_failure_class_builder_timeout_failure_class_builder_timeout.md)
/usr/bin/python3.12 -m software_factory --repo <demo> observe
# ... rung_auto_failure_class_builder_timeout_status=DRAFT ... ladder_drift=none ...

# 7. Provenance record:
tail -1 <demo>/.factory/decision_log.jsonl
# {"actor": "factory-diagnose", "diagnose_drafted": {"rung": "auto_failure_class_builder_timeout", "signature": "failure_class:builder_timeout", "count": 2, "evidence": ["2026-10-19T15:00:00+00:00", "2026-10-19T15:20:00+00:00"]}, "ts": "..."}

# 8. Rung registered DRAFT / self / covers:
# {'status': 'DRAFT', ..., 'covers': ['failure_class:builder_timeout'], 'origin': 'self'}

# 9. Circuit breaker (max_active_drafts=1, one self rung already active;
# second seeded signature failure_class:verify_red must NOT draft):
/usr/bin/python3.12 -m software_factory --repo <demo> diagnose --draft
# draft_skipped=cap_reached
# finding: failure_class:verify_red count=2 evidence=2026-10-19T15:30:00+00:00,2026-10-19T15:40:00+00:00
# findings=1

# 10. CLI --covers, add then set:
/usr/bin/python3.12 -m software_factory --repo <demo> ticket add --id demo1 --title "Demo" --ticket .factory/tickets/demo1_x.md --covers "violation:kernel_edit,stall"
# registered rung demo1 (OPEN): Demo
# covers after add: ['violation:kernel_edit', 'stall']
/usr/bin/python3.12 -m software_factory --repo <demo> ticket set demo1 --covers "violation:kernel_edit"
# updated rung demo1: {'covers': ['violation:kernel_edit']}
# covers after set: ['violation:kernel_edit']

# 11. Bare diagnose stays read-only (after committing the demo lane):
/usr/bin/python3.12 -m software_factory --repo <demo> diagnose >/dev/null; git -C <demo> status --porcelain | wc -l
# 0
```

## What this does NOT prove (proof-limiting section — required)
- Does not auto-OPEN self-drafted rungs: the human gate (DRAFT -> OPEN) is
  sovereign and was never exercised automatically; s4 remains unsupplied.
- Drafted tickets are deterministic templates populated from decision_log
  evidence — no LLM authored the prose, and no reasoning about WHY the
  pattern occurs is claimed; the fix approach is unproven until a builder
  lands the rung with its own receipt.
- The breaker counts only `origin="self"` rungs in DRAFT/OPEN/IN_PROGRESS;
  human rungs never consume the self-draft budget, so the cap bounds
  machine-authored churn, not total lane breadth.
- Drafted rung ids derive from the signature (`auto_<slug>`); a signature
  whose slug collides with an existing rung id is silently skipped, not
  merged.
- The demo ran against a scratch fixture lane; the live sf-next lane was
  never drafted into (its only builder_timeout evidence predates this
  landing and belongs to s2 itself).
- The `builder_timeout` bucket fix does not make builder timeouts
  transient-tolerant or retry-aware — tick.py behavior is untouched
  (kernel freeze).
