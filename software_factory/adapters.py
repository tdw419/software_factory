"""Builder adapters — how a tick dispatches actual work.

The product is agent-agnostic: `shell` runs any CLI coding agent (hermes,
claude, aider, an ollama script...) with a rendered prompt file; `noop` is a
dry-run that dispatches nothing. The adapter's job is ONLY to run the
command and report; verification and bookkeeping stay in tick.py so no
builder can grade its own homework.
"""

import shlex
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
}


def get_adapter(name):
    if name not in ADAPTERS:
        raise AdapterError(f"unknown builder adapter {name!r} (have: {sorted(ADAPTERS)})")
    return ADAPTERS[name]
