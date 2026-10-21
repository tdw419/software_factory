"""Builder adapters — how a tick dispatches actual work.

The product is agent-agnostic: `shell` runs any CLI coding agent (hermes,
claude, aider, an ollama script...) with a rendered prompt file; `noop` is a
dry-run that dispatches nothing. The adapter's job is ONLY to run the
command and report; verification and bookkeeping stay in tick.py so no
builder can grade its own homework.
"""

import re
import shlex
import subprocess
import time
from pathlib import Path

from .common import sh


class AdapterError(Exception):
    pass


def render_prompt(template: str, *, lane, rung_id, repo, ticket_body, rules,
                  receipt_path, resuming=False) -> str:
    return template.format(
        lane=lane,
        rung_id=rung_id,
        resuming=" (RESUMING a claimed rung)" if resuming else "",
        resuming_note=(
            "\nThis rung is already IN_PROGRESS claimed by the lane — pick up\n"
            "its claimed_at state; do not restart finished sub-steps.\n"
            if resuming else ""
        ),
        repo=str(repo),
        ticket_body=ticket_body,
        rules="\n".join(f"[{i}] {r}" for i, r in enumerate(rules)),
        receipt_path=receipt_path,
    )


def run_shell(repo, cmd_tmpl, prompt_path, run_dir, timeout_s):
    """Run the configured builder command. Placeholders: {repo} {prompt} {run_dir}."""
    if not cmd_tmpl:
        raise AdapterError(
            "builder.cmd is empty — set it in .factory/config.json "
            "(e.g. 'hermes chat --query-file {prompt} --oneshot --in {repo} --yolo')"
        )
    cmd = cmd_tmpl.format(repo=str(repo), prompt=str(prompt_path), run_dir=str(run_dir))
    argv = shlex.split(cmd)
    return sh(argv, timeout_s, cwd=str(repo))


#: Fenced ```bash / ```sh code blocks in a model response (non-greedy).
_FENCE_RE = re.compile(r"```(?:bash|sh)\s*\n(.*?)```", re.DOTALL)

#: Sentinels that end the loop cleanly before any block execution.
_HALT_SENTINELS = ("HALT", "[DONE]")

#: Exit codes for abnormal loop ends (modeled on timeout(1)'s 124).
_RC_TIMEOUT = 124
_RC_TURN_LIMIT = 3


def _result(cmd, returncode, stdout, stderr):
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def _run_capture(cmd, cwd, timeout, input_text=None):
    """shell=True run under an explicit timeout. Returns CompletedProcess, or
    None when the timeout expired (lane rule 8: never a bare subprocess)."""
    try:
        return subprocess.run(
            cmd, shell=True, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout,
            input=input_text if input_text is not None else None,
            stdin=subprocess.DEVNULL if input_text is None else None,
        )
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        err = e.stderr or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return _result(cmd, _RC_TIMEOUT, out, err + f"\n[fenced_bash: TIMEOUT after {timeout:.1f}s]")


def run_fenced_bash(repo, cmd_tmpl, prompt_path, run_dir, timeout_s,
                    max_turns=15):
    """Local-model builder loop (schema-free xb-wrapper protocol).

    Each turn: render cmd_tmpl (placeholders {repo} {prompt} {run_dir};
    {prompt} is a per-turn prompt file — when cmd_tmpl has no {prompt}, the
    prompt is piped via stdin), scan the response for fenced ```bash/```sh
    blocks, execute each sequentially with cwd=repo, and feed the output back
    as the next turn's context. HALT / [DONE] (checked BEFORE executing any
    block) or a response without fenced blocks ends the loop with rc 0.
    Timeout exhaustion -> rc 124; turn-limit exhaustion without a sentinel
    -> rc 3. Full transcript lands in run_dir / "fenced_bash.log".

    The adapter only runs commands and reports; verification and bookkeeping
    stay in tick.py so no builder can grade its own homework.
    """
    if not cmd_tmpl:
        raise AdapterError(
            "builder.cmd is empty — set it in .factory/config.json "
            "(e.g. 'ollama run qwen2.5-coder:14b \"$(cat {prompt})\"')"
        )
    repo = Path(repo)
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "fenced_bash.log"

    prompt_text = Path(prompt_path).read_text(encoding="utf-8")
    deadline = time.monotonic() + float(timeout_s)

    def _log(text):
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(text)

    _log(f"===== fenced_bash start {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} "
         f"timeout_s={timeout_s} max_turns={max_turns} repo={repo}\n")

    for turn in range(1, max_turns + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _log(f"[budget exhausted before TURN {turn}] rc={_RC_TIMEOUT}\n")
            return _result(cmd_tmpl, _RC_TIMEOUT, "", "fenced_bash: timeout budget exhausted")

        prompt_file = run_dir / f"prompt_turn_{turn:03d}.txt"
        prompt_file.write_text(prompt_text, encoding="utf-8")
        cmd = cmd_tmpl.format(repo=str(repo), prompt=str(prompt_file), run_dir=str(run_dir))

        _log(f"\n===== TURN {turn}\n----- cmd -----\n{cmd}\n"
             f"----- prompt ({prompt_file.name}) -----\n{prompt_text}\n----- response -----\n")

        stdin_text = None if "{prompt}" in cmd_tmpl else prompt_text
        r = _run_capture(cmd, repo, remaining, input_text=stdin_text)
        _log(f"{r.stdout}\n[runtime rc={r.returncode}]\n")
        if r.returncode == _RC_TIMEOUT:
            _log(f"[model command timed out] rc={_RC_TIMEOUT}\n")
            return _result(cmd, _RC_TIMEOUT, r.stdout, r.stderr)

        response = r.stdout
        if any(s in response for s in _HALT_SENTINELS):
            _log("[halt sentinel — loop ends cleanly] rc=0\n")
            return _result(cmd, 0, response, r.stderr)

        blocks = _FENCE_RE.findall(response)
        if not blocks:
            _log("[no fenced bash blocks — loop ends cleanly] rc=0\n")
            return _result(cmd, 0, response, r.stderr)

        outputs = []
        for i, block in enumerate(blocks, 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _log(f"[budget exhausted before block {i}] rc={_RC_TIMEOUT}\n")
                return _result(cmd, _RC_TIMEOUT, response,
                               "fenced_bash: timeout budget exhausted")
            _log(f"----- block {i} -----\n{block}\n")
            br = _run_capture(block, repo, remaining)
            _log(f"[block {i} rc={br.returncode}]\n{br.stdout}{br.stderr}")
            outputs.append(
                f"Command exited with code {br.returncode}:\n{br.stdout}{br.stderr}"
            )
        prompt_text = "\n".join(outputs)

    _log(f"[turn limit {max_turns} reached without HALT/[DONE]] rc={_RC_TURN_LIMIT}\n")
    return _result(
        cmd_tmpl, _RC_TURN_LIMIT, "",
        f"fenced_bash: turn limit {max_turns} reached without HALT/[DONE]",
    )


def run_noop(repo, cmd_tmpl, prompt_path, run_dir, timeout_s):
    """Dry-run adapter: dispatches nothing, changes nothing."""
    return type("R", (), {
        "returncode": 0,
        "stdout": f"NOOP: would dispatch builder with prompt {prompt_path}",
        "stderr": "",
    })()


ADAPTERS = {
    "shell": run_shell,
    "noop": run_noop,
    "fenced_bash": run_fenced_bash,
}


def get_adapter(name):
    if name not in ADAPTERS:
        raise AdapterError(f"unknown builder adapter {name!r} (have: {sorted(ADAPTERS)})")
    return ADAPTERS[name]
