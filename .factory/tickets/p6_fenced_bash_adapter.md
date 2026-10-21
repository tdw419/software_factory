# TICKET — p6: `adapters.fenced_bash` local builder loop

## Charter
The RTX 5090 empirical trial on `sf_pilot2` proved that local models (`qwen2.5-coder:14b`)
comfortably fit in VRAM and execute raw inference quickly (~8.5s), but fail at
emitting structured OpenAI-compatible `tool_calls` JSON schemas through agent
frameworks (emitting raw JSON or markdown text instead, resulting in 0 executed
tools).

The viable, schema-free protocol identified by both sessions is the
**xb-wrapper / fenced-bash pattern**:
The model outputs standard fenced ```bash code blocks; the adapter extracts
and executes them sequentially in the repository worktree, feeds stdout/stderr
back into the model context for the next turn, and loops until the model finishes
or reaches a turn limit.

This eliminates all JSON tool schema fragility while retaining 100% of the
factory's verify gate, Rule-0 claim+RED discipline, kernel guard, and receipt
validation invariants.

## Goals
1. **`adapters.run_fenced_bash`**:
   - Registered under `ADAPTERS["fenced_bash"]`.
   - Signature: `run_fenced_bash(repo, cmd_tmpl, prompt_path, run_dir, timeout_s, max_turns=15)`.
   - Reads `prompt_path` as the initial user/agent prompt.
   - In each turn:
     - Formats conversation history and executes `cmd_tmpl` (placeholders `{prompt}` or piped via stdin).
     - Scans response for fenced code blocks: ````(?:bash|sh)\s*\n(.*?)```` (re.DOTALL).
     - If no code blocks found or response contains `HALT` / `[DONE]` sentinel: ends loop cleanly with returncode 0.
     - Executes each extracted bash block sequentially via `subprocess.run(..., shell=True, cwd=str(repo))` under remaining timeout budget.
     - Appends full transcript to `run_dir / "fenced_bash.log"`.
     - Feeds command output (`Command exited with code <rc>:\n<stdout+stderr>`) as next turn context.
   - Returns a result object matching `run_shell` (`returncode`, `stdout`, `stderr`).
2. **Config & Visibility**:
   - Lanes can configure `"builder": {"adapter": "fenced_bash", "cmd": "...", "tier": "local", "max_turns": 15}`.
   - Backward compatibility: `"adapter": "shell"` and `"noop"` remain byte-identical.
3. **Tests & Offline Verification**:
   - `tests/test_adapters.py`: Unit tests with mock completion scripts simulating multi-turn fenced bash loops (turn 1: create file, turn 2: run test, turn 3: HALT), timeout handling, turn limits, and empty block completion. Requires zero network and zero GPU to test.

## Constraints
- Non-kernel: Modifies `software_factory/adapters.py` and `tests/test_adapters.py` only. Zero modifications to `tick.py` or `gate.py`.
- No heavy dependencies: Python stdlib only (`re`, `subprocess`, `time`, `shlex`, `pathlib`).
- Rule-0 claim + RED first: failing tests for `fenced_bash` in the claim commit.
- Receipt with paired fences and required sections.

## What this does NOT prove
- Does not guarantee every local model will reliably complete rungs — prompt adherence varies by model; this rung provides the reliable execution protocol.
- Does not modify cloud builder lanes.
