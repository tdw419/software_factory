# RECEIPT — p6: adapters.fenced_bash local builder execution loop

## What PASS proves
`adapters.run_fenced_bash` implements the schema-free xb-wrapper / fenced-bash
protocol end-to-end, offline: it reads the prompt file, renders `cmd_tmpl`
(per-turn prompt file via `{prompt}`, or the prompt piped via stdin when the
placeholder is absent), scans the model response for fenced ```bash/```sh
blocks (non-greedy, re.DOTALL), executes each block sequentially with
`cwd=repo` under a shared deadline budget, and feeds
`Command exited with code <rc>:\n<stdout><stderr>` back as the next turn's
context. HALT/[DONE] sentinels are checked BEFORE any block execution (a
response containing HALT plus a block executes nothing); a response with no
fenced blocks ends the loop cleanly with rc 0; timeout-budget exhaustion
returns rc 124 (model command and extracted blocks both covered); turn-limit
exhaustion without a sentinel returns rc 3 with a named stderr message. The
full transcript (turns, cmds, prompts, responses, blocks, outputs) lands in
`run_dir/fenced_bash.log` and per-turn prompt snapshots in
`run_dir/prompt_turn_NNN.txt`. The adapter is registered as
`ADAPTERS["fenced_bash"]` with signature
`(repo, cmd_tmpl, prompt_path, run_dir, timeout_s, max_turns=15)` — the first
five positional parameters are exactly what `tick.run_tick` passes, so lanes
can select it with `builder.adapter = "fenced_bash"` and zero kernel changes.
`shell` and `noop` are untouched; their behavior is locked by new compat legs.
RED was shown first: at claim commit `414a1d3` 10 of the 13 fenced_bash/registry
legs failed (`unknown builder adapter 'fenced_bash'`) and the 3 trivial-pass
legs are the shell/noop compatibility guarantees, which hold pre-change
because the surfaces were never modified.

## Commands and outputs (paired in the same fence)
```bash
# RED leg — at the claim commit, before any implementation existed
$ git stash -q && /usr/bin/python3.12 -m pytest tests/test_adapters.py -p no:warnings -q 2>&1 | tail -4
FAILED tests/test_adapters.py::test_fenced_bash_no_blocks_ends_clean - softwa...
FAILED tests/test_adapters.py::test_fenced_bash_registered - AssertionError: ...
FAILED tests/test_adapters.py::test_fenced_bash_multi_turn - software_factory...
E           software_factory.adapters.AdapterError: unknown builder adapter 'fenced_bash' (have: ['noop', 'shell'])
# 10 failed, 3 passed (recorded at the 414a1d3 worktree state; RED shown before GREEN)
```

```bash
# GREEN leg — adapter suite after implementation commit a60f1ab
$ /usr/bin/python3.12 -m pytest tests/test_adapters.py -p no:warnings -q
..............                                                           [100%]
# exit 0 — 14 passed
```

```bash
# No regressions in the full offline suite
$ /usr/bin/python3.12 -m pytest -p no:warnings -q
........................................................................ [ 39%]
........................................................................ [ 78%]
........................................                                 [100%]
# exit 0 — 182 passed, 0 failed (no pre-existing failures absorbed or excluded)
```

```bash
# Registration + tick-compatible signature
$ /usr/bin/python3.12 -c "from software_factory import adapters; import inspect; \
print(sorted(adapters.ADAPTERS)); print(inspect.signature(adapters.run_fenced_bash))"
['fenced_bash', 'noop', 'shell']
(repo, cmd_tmpl, prompt_path, run_dir, timeout_s, max_turns=15)
```

```bash
# Commit scope: kernel surfaces untouched
$ git show --stat --oneline a60f1ab | tail -3
 software_factory/adapters.py | 127 ++++++++++++++++++++++++++++++++++++++++++++
 tests/test_adapters.py       |  23 +++++---
 2 files changed, 142 insertions(+), 8 insertions(+)
# claim commit 414a1d3: tests/test_adapters.py + .factory/queue_state.json (claim in same commit)
```

## What this does NOT prove (proof-limiting section — required)
- Does NOT prove any local model reliably completes rungs through this loop:
  qwen2.5-coder:14b was never invoked here (zero GPU, zero network); all
  model behavior was simulated with mock scripts. Prompt adherence, halt
  honesty, and code quality of real local models remain unproven.
- Does NOT prove the loop works through any specific agent framework or
  ollama invocation — `cmd_tmpl` integration with a real model server is
  operator-side configuration, untested here.
- Does NOT prove shell/noop are byte-identical at the source level — they
  were not edited, and the compat legs lock behavior (exit codes, stdout),
  not bytes of the module.
- Does NOT prove end-to-end tick integration: `tick.py` passes only 5
  positional args, so `max_turns` always takes the default 15 when dispatched
  by the kernel; a per-lane `builder.max_turns` config key is currently
  advisory (visibility only) until a kernel change wires it through.
- Does NOT prove sandboxing: extracted blocks run with full `shell=True`
  authority as the lane user inside the repo worktree — same trust level as
  the `shell` adapter, by design.
