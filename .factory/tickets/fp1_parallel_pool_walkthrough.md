# Rung fp1 — `templates/PARALLEL_POOL_WALKTHROUGH.md` multi-lane operator walkthrough

## Charter
Create `templates/PARALLEL_POOL_WALKTHROUGH.md` documenting how operators set up a multi-worktree fleet using the `v0.9.0` parallel scaling primitives (`p1` `factory pool`, `p2` `--files` conflict metadata, and `p3` `factory dispatch`).

## Scope & Constraints
- Declared `--files`: `templates/*`
- Touch ONLY `templates/PARALLEL_POOL_WALKTHROUGH.md` (plus `.factory/queue_state.json`, `.factory/decision_log.jsonl`, `.factory/receipts/fp1_RECEIPT.md`, and `ROADMAP.md` for rung lifecycle).
- NEVER modify `software_factory/gate.py`, `software_factory/tick.py`, or any `software_factory/*.py` / `tests/*.py` files.
- Do NOT invoke `factory tick` or `factory dispatch` from inside the builder session (recursion guard).

## Required Content in `templates/PARALLEL_POOL_WALKTHROUGH.md`
1. `# Parallel Lane Pool & Conflict-Aware Dispatch Walkthrough`
2. `## 1. Worktree Fleet Setup` — exact `git worktree add ../sf_lane2 -b lane2` + `factory init` commands.
3. `## 2. Pool Discovery (p1)` — `factory pool --paths ../sf_next,../sf_lane2` and readout format (`lane: ...`, `lanes=<N> active=<A> parked=<P>`).
4. `## 3. Declaring File Scope (p2)` — `factory ticket add/set --files <csv>` and symmetric prefix/glob overlap rules (`files_overlap`).
5. `## 4. Conflict-Aware Parallel Dispatch (p3)` — `factory dispatch --paths ... --max-parallel 2 [--dry-run]`, head-OPEN skip semantics (`reason=file_conflict`), and why per-lane `tick.lock` + fleet-level `in_flight_files` partitioning work together.

## Stages (Commit Per Sub-Step — Rule 7)

### Stage 1 — Claim + RED
1. Run the doc verification check BEFORE creating `templates/PARALLEL_POOL_WALKTHROUGH.md` to capture the RED failure output:
   ```bash
   /usr/bin/python3.12 -c "from pathlib import Path; p=Path('templates/PARALLEL_POOL_WALKTHROUGH.md'); assert p.is_file(), 'missing walkthrough'; txt=p.read_text(); [ None for h in ('## 1. Worktree Fleet Setup','## 2. Pool Discovery (p1)','## 3. Declaring File Scope (p2)','## 4. Conflict-Aware Parallel Dispatch (p3)') if h in txt or (_ for _ in ()).throw(AssertionError(h)) ]; print('WALKTHROUGH_OK')"
   ```
2. Claim `fp1`:
   ```bash
   /usr/bin/python3.12 -m software_factory ticket set fp1 --status IN_PROGRESS --claimed-by hermes-cli
   ```
   Update `- Rung fp1` in `ROADMAP.md` to `[IN_PROGRESS]` and commit `.factory/queue_state.json .factory/decision_log.jsonl ROADMAP.md`.

### Stage 2 — GREEN
1. Write `templates/PARALLEL_POOL_WALKTHROUGH.md` with all 4 required sections and concrete CLI examples.
2. Re-run the doc verification one-liner above (must print `WALKTHROUGH_OK` and exit 0) AND run `/usr/bin/python3.12 -m pytest tests/ -q` (must pass 160/160).
3. Commit `templates/PARALLEL_POOL_WALKTHROUGH.md`.

### Stage 3 — Receipt & Land
1. Write `.factory/receipts/fp1_RECEIPT.md` containing:
   - Paired command+output fence for the Stage 1 RED check (`AssertionError: missing walkthrough`)
   - Paired command+output fence for the Stage 2 GREEN check (`WALKTHROUGH_OK` + `160 passed`)
   - Mandatory `## What PASS proves` and `## What this does NOT prove` sections.
2. Validate receipt:
   ```bash
   /usr/bin/python3.12 -m software_factory receipt validate .factory/receipts/fp1_RECEIPT.md
   ```
3. Mark `fp1` LANDED using the 40-char git SHA of the Stage 2 GREEN commit, update `- Rung fp1` in `ROADMAP.md` to `[LANDED] (<short-sha>)`, and commit `.factory/receipts/fp1_RECEIPT.md .factory/queue_state.json .factory/decision_log.jsonl ROADMAP.md`.
