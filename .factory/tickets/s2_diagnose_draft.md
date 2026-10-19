# TICKET — s2: factory diagnose --draft (evidence-cited self-drafting + CLI covers)

## Charter
`s1` shipped `factory diagnose` as a read-only pattern counter over live +
archived `decision_log`. Running `s1` against the live `geometry_os` pilot
lane immediately surfaced two empirical gaps alongside the planned `--draft`
step:

1. **Telemetry gap (`builder TIMEOUT`)**: `tick.py` logs builder timeouts as
   `"builder TIMEOUT after <N>s"`, `transient: true`. `diagnose._PROBLEM_RULES`
   has `("verify gate TIMEOUT", "verify_timeout")` but lacks
   `("builder TIMEOUT", "builder_timeout")`, so builder timeouts fall through
   to the first-word fallback and classify as `failure_class:builder`.
2. **CLI gap (`--covers`)**: `s1` deduplicates findings against a rung's
   `covers: [<signature>, ...]` list in `queue_state.json`, but neither
   `factory ticket add` nor `factory ticket set` accepts `--covers`, forcing
   operators/builders to hand-edit `queue_state.json`.
3. **Self-drafting (`factory diagnose --draft`)**: Automate necessity
   detection while keeping the human gate at `DRAFT -> OPEN`.

## Goal
1. **Classification fix**: Add `("builder TIMEOUT", "builder_timeout")` to
   `diagnose._PROBLEM_RULES` (before `"builder exit"`) so `"builder TIMEOUT
   after 1500s"` classifies deterministically as
   `failure_class:builder_timeout`.
2. **CLI `--covers` wiring**:
   - `queue_state.register_rung(...)` and `queue_state.update_rung(...)`
     accept an optional `covers` list of signature strings (persisted as
     `covers: [...]` on the rung when provided).
   - `factory ticket add` and `factory ticket set` accept
     `--covers <sig[,sig...]>` (comma-separated string, stripped of empty
     items) and pass the list through to `queue_state`.
3. **`factory diagnose --draft`**:
   - Bare `factory diagnose` (without `--draft`) remains 100% read-only and
     byte-identical to `s1` (except for the `builder_timeout` bucket fix).
   - When `--draft` is passed (`diagnose.run(repo, cfg=..., draft=True)` /
     `factory diagnose --draft`):
     - After computing uncovered findings, draft at most one `DRAFT` rung per
       uncovered finding signature, subject to circuit breakers:
       - **Active self-draft cap**: count rungs in `queue_state.json` with
         `origin == "self"` and `status in ("DRAFT", "OPEN", "IN_PROGRESS")`.
         If already `>= max_active_drafts` (from `diagnose.max_active_drafts`
         in config, default `2`), stop drafting and append
         `draft_skipped=cap_reached` to stdout lines.
       - **Evidence citation**: every drafted ticket file must cite the
         finding's `signature`, `count`, and the exact `evidence` timestamps
         from `decision_log`.
       - **Valid ticket structure**: the written ticket at
         `.factory/tickets/<rung_id>_<slug>.md` must include `## Goal`,
         `## Stages`, `## Constraints` (explicitly forbidding edits to
         `kernel_paths`), and `## What this does NOT prove` so
         `queue_state.validate_ticket()` returns `[]`.
       - **Queue registration & idempotence**: register the rung in
         `queue_state.json` with `status="DRAFT"`, `origin="self"`, and
         `covers=[signature]`. Because `covers` includes `signature` and
         status is `DRAFT`, an immediate second `factory diagnose` or
         `factory diagnose --draft` sees the signature as covered (`findings=0`,
         zero duplicate drafts).
       - **Ladder sync**: if `digest.ladder` (e.g. `ROADMAP.md` with
         `line_prefix: "- Rung"`) is configured and the ladder file exists,
         append `- Rung <id> [DRAFT]: <title> (<ticket_rel>)` so
         `observer.observe()` continues reporting `ladder_drift=none`.
       - **Provenance**: append a `diagnose_drafted` record to
         `decision_log.jsonl` naming `rung`, `signature`, `count`, and
         `evidence`, and emit `drafted: <rung_id> covers=<signature> ticket=<ticket_rel>`
         before `findings=<n>`.

## Stages
- Probe (disruption 0): inspect `diagnose.py`, `queue_state.py`, `cli.py`,
  and `tests/test_diagnose.py`.
- RED: commit claiming `s2` (`IN_PROGRESS`, `claimed_by="hermes-cli"`) together
  with failing tests in `tests/test_diagnose.py` covering:
  1. `classify_problem("builder TIMEOUT after 1500s") == "builder_timeout"`
  2. `factory ticket add ... --covers` and `factory ticket set ... --covers`
  3. `factory diagnose --draft` creating a `DRAFT` rung (`origin="self"`,
     `covers=[sig]`), writing a valid ticket file citing the evidence `ts`,
     syncing `ROADMAP.md` when configured (`ladder_drift=none`), and making an
     immediate re-run report `findings=0`.
  4. Circuit breaker: `max_active_drafts` (default 2) caps active `origin="self"`
     rungs and emits `draft_skipped=cap_reached`.
- GREEN: implement in `diagnose.py`, `queue_state.py`, and `cli.py`; full
  pytest suite green.
- Receipt: write `.factory/receipts/s2_RECEIPT.md` with paired command/output
  fence and both required headings, mark `s2` `LANDED` with commit SHA, sync
  `ROADMAP.md`.

## Constraints
- Never modify `kernel_paths` (`software_factory/gate.py`,
  `software_factory/tick.py`).
- Self-drafted rungs are ALWAYS `status="DRAFT"` — never `OPEN`. The human
  gate (`DRAFT -> OPEN`) is sovereign.
- Bare `factory diagnose` without `--draft` must perform zero writes.

## What this does NOT prove
- Does not auto-OPEN self-drafted rungs (`s4` remains unsupplied).
- Does not use an LLM to author prose; drafted tickets are deterministic
  templates populated from `decision_log` evidence records.
