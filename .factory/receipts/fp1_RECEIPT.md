# RECEIPT — fp1: templates/PARALLEL_POOL_WALKTHROUGH.md multi-lane operator walkthrough

## What PASS proves
The gate one-liner can fail (RED) when the walkthrough is absent, and passes
(GREEN) once `templates/PARALLEL_POOL_WALKTHROUGH.md` exists with all four
required section headings. The full test suite passes 160/160 after the doc
lands, so the addition breaks no existing gate. The document's CLI examples
were cross-checked against the actual argparse surface (`factory pool
--paths`, `factory ticket add/set --files`, `factory dispatch
--paths/--max-parallel/--dry-run`) and the `files_overlap` / `plan_dispatch`
source in `software_factory/queue_state.py` and `software_factory/pool.py`.

## Commands and outputs (paired in the same fence)
Stage 1 — RED (before the file existed):
```bash
/usr/bin/python3.12 -c "from pathlib import Path; p=Path('templates/PARALLEL_POOL_WALKTHROUGH.md'); assert p.is_file(), 'missing walkthrough'; txt=p.read_text(); [ None for h in ('## 1. Worktree Fleet Setup','## 2. Pool Discovery (p1)','## 3. Declaring File Scope (p2)','## 4. Conflict-Aware Parallel Dispatch (p3)') if h in txt or (_ for _ in ()).throw(AssertionError(h)) ]; print('WALKTHROUGH_OK')"
# Traceback (most recent call last):
#   File "<string>", line 1, in <module>
# AssertionError: missing walkthrough
```

Stage 2 — GREEN (after the doc landed, commit e59a7f6):
```bash
/usr/bin/python3.12 -c "from pathlib import Path; p=Path('templates/PARALLEL_POOL_WALKTHROUGH.md'); assert p.is_file(), 'missing walkthrough'; txt=p.read_text(); [ None for h in ('## 1. Worktree Fleet Setup','## 2. Pool Discovery (p1)','## 3. Declaring File Scope (p2)','## 4. Conflict-Aware Parallel Dispatch (p3)') if h in txt or (_ for _ in ()).throw(AssertionError(h)) ]; print('WALKTHROUGH_OK')"
# WALKTHROUGH_OK

/usr/bin/python3.12 -m pytest tests/
# ........................................................................ [ 45%]
# ........................................................................ [ 90%]
# ................                                                         [100%]
# 160 passed in 48.37s
```

## What this does NOT prove (proof-limiting section — required)
- The walkthrough is documentation, not execution: no command in it was run
  against a real second worktree. `git worktree add` / `factory init` /
  `factory dispatch` examples were checked against `--help` output and
  source, not exercised live (the ticket forbids invoking `factory tick` /
  `factory dispatch` from the builder session).
- The sample `factory pool` readout in section 2 is illustrative — lane
  names/heartbeats in the example block are representative of the format
  produced by `pool.findings()`, not captured output from a live two-lane
  fleet.
- Heading presence does not prove prose accuracy; the overlap rules and
  skip semantics were read from `queue_state.files_overlap` and
  `pool.plan_dispatch` docstrings/code at HEAD e59a7f6, but future kernel
  changes can silently invalidate the doc (docs are not gate-covered).
- The 160-test suite passing proves no regression, not that every doc
  claim about runtime behavior (e.g. `--builder-timeout` behavior) is
  verified end-to-end.
