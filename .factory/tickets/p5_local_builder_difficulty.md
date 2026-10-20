# TICKET — p5: builder tier label + ticket difficulty field

## Charter
The fleet pilot (fp1/fp2) measured that 98.8% of tick wall-clock is builder
execution, not verify — the real GPU/throughput lever for this product is
more concurrent *builders*, not a faster verify gate (p4 is correctly held).
`adapters.run_shell` already executes any CLI the operator points it at
(`builder.cmd` in `.factory/config.json`), so running a local model (e.g.
`ollama run qwen2.5-coder` on a local GPU) as a lane's builder requires no
new adapter code today — only config. What's missing is the *visibility and
routing metadata* around that choice: which lanes run cloud vs. local
builders (so trust calibration stays legible per landing), and which rungs
are suited to a lower-trust local builder in the first place (mechanical:
tests/docs/benchmarks vs. fuzzy-scope: architecture, API design).

## Goal
1. **`builder.tier` config field** (`.factory/config.json`, optional string,
   e.g. `"cloud"` or `"local"`; free-form, not validated against an enum —
   this is a label, not a gate). When present, `observer.observe()` emits
   `builder=<tier>` immediately after `tick_heartbeat=...`. Absent config on
   a lane keeps output byte-identical (no `builder=` line) — the r5/r7
   contract.
2. **`difficulty` field on rungs** (advisory, not enforced): extend
   `queue_state.register_rung()` / `update_rung()` to accept an optional
   `difficulty` string (free-form, e.g. `"mechanical"` / `"fuzzy"`), and wire
   `factory ticket add --difficulty <value>` / `factory ticket set <id>
   --difficulty <value>` through to it, following the exact pattern `--files`
   used in p2 and `--covers` used in s2. `factory pool`'s per-lane
   `inspect_lane()` output and `factory observe`'s per-rung lines should
   surface `difficulty` when present, same style as the existing
   `rung_<id>_status=` line.
3. **Documentation, not automation**: update `HERMES_CRON_WIRING.md` /
   `README.md` with the operator guidance already validated by the pilot —
   mechanical rungs (test legs, doc rungs, benchmark harnesses) are
   candidates for a `builder.tier: "local"` lane; fuzzy-scope rungs stay on
   cloud builders. This rung does NOT implement automatic routing of a rung
   to a tier/lane based on its `difficulty` — that stays an operator
   decision (which lane you open the rung in), consistent with every other
   human-gated supply decision in this product.

## Constraints
- No new adapter code required or expected — `run_shell` already handles any
  CLI builder; do not add an `ollama` or `llama.cpp`-specific adapter unless
  a real local-builder trial surfaces a concrete gap `run_shell` can't cover
  (if it does, that's a follow-up rung with its own evidence, not this one).
- `builder.tier` and `difficulty` are both free-form metadata, not validated
  enums — do not hardcode a tier/difficulty vocabulary that would need a
  migration later.
- Byte-stability regression: a lane with no `builder.tier` configured and a
  rung with no `difficulty` set must produce output identical to pre-p5
  (both new lines omitted, not emitted empty).
- Non-kernel: `observer.py`, `queue_state.py`, `cli.py`, `pool.py` only —
  `tick.py` and `gate.py` stay untouched.
- RED-first in the claim commit (rule 0); receipt with paired
  commands/outputs; both required sections (`## What PASS proves`,
  `## What this does NOT prove`).

## What this does NOT prove
- Does not prove a local model (qwen2.5-coder or otherwise) can pass this
  product's verify gate and rule-0 claim discipline on a real rung — that is
  a live trial to run after this rung lands, with its own receipt, not a
  claim this ticket can make in advance.
- Does not implement automatic difficulty-based lane routing or load
  balancing across the pool — `factory dispatch`'s greedy conflict-free
  assignment is unchanged; `difficulty` is metadata for a human to read, not
  an input the scheduler consumes (yet).
- Does not change `max_active_drafts`, `diagnose.py`, or any self-diagnosis
  behavior — `difficulty` is orthogonal to `origin`/`covers`.
