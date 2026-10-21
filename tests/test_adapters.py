"""Adapter tests: fenced_bash local builder loop + shell/noop compatibility.

Zero network, zero GPU: the "model" is a mock python script that returns
canned responses (with fenced ```bash blocks) in sequence, so the full
multi-turn loop is exercised offline.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from software_factory import adapters
from software_factory.adapters import AdapterError


# ---------------------------------------------------------------- helpers

def make_mock(run_dir, body):
    """Write a mock model script. `body` is python code that must print the
    model response; it may use `data` (the prompt text) and `STATE`
    (pathlib.Path counter file for multi-invocation sequencing)."""
    script = Path(run_dir) / "mock_model.py"
    script.write_text(
        "import pathlib, sys\n"
        f"STATE = pathlib.Path({str(Path(run_dir) / 'mock_turn')!r})\n"
        "n = int(STATE.read_text()) if STATE.exists() else 0\n"
        "STATE.write_text(str(n + 1))\n"
        "argv_prompt = sys.argv[2] if len(sys.argv) > 2 else None\n"
        "data = pathlib.Path(argv_prompt).read_text() if argv_prompt else sys.stdin.read()\n"
        + body +
        "\n"
    )
    return script


def cmd_stdin(script):
    # no {prompt} placeholder -> prompt is piped via stdin
    return f"{sys.executable} {script} {{run_dir}}"


def cmd_promptfile(script):
    # {prompt} placeholder -> per-turn prompt file path
    return f"{sys.executable} {script} {{run_dir}} {{prompt}}"


def mock_invocations(run_dir):
    p = Path(run_dir) / "mock_turn"
    return int(p.read_text()) if p.exists() else 0


# ---------------------------------------------------------------- registry

def test_fenced_bash_registered():
    assert "fenced_bash" in adapters.ADAPTERS
    assert adapters.get_adapter("fenced_bash") is adapters.ADAPTERS["fenced_bash"]


def test_get_adapter_unknown_raises():
    with pytest.raises(AdapterError):
        adapters.get_adapter("no_such_adapter")


# ---------------------------------------------------------------- the loop

def test_fenced_bash_multi_turn(repo, tmp_path):
    """turn 1: create file, turn 2: append, turn 3: HALT."""
    run_dir = tmp_path / "run"
    body = (
        "if n == 0:\n"
        "    out = '```bash\\necho one > step1.txt\\n```'\n"
        "elif n == 1:\n"
        "    out = '```bash\\necho two > step2.txt\\n```'\n"
        "else:\n"
        "    out = 'work complete HALT'\n"
        "sys.stdout.write(out)\n"
    )
    r = adapters.get_adapter("fenced_bash")(
        repo, cmd_stdin(make_mock(run_dir, body)), tmp_path / "prompt.md",
        run_dir, timeout_s=60,
    )
    assert r.returncode == 0, r.stderr
    assert (repo / "step1.txt").read_text().strip() == "one"
    assert (repo / "step2.txt").read_text().strip() == "two"
    assert mock_invocations(run_dir) == 3
    log = (run_dir / "fenced_bash.log").read_text()
    assert "TURN 1" in log and "TURN 2" in log and "TURN 3" in log


def test_fenced_bash_output_fed_back(repo, tmp_path):
    """Command output from turn 1 reaches the model as turn-2 context."""
    run_dir = tmp_path / "run"
    body = (
        "if 'payload-123' in data:\n"
        "    out = 'saw the payload [DONE]'\n"
        "else:\n"
        "    out = '```bash\\necho payload-123\\n```'\n"
        "sys.stdout.write(out)\n"
    )
    r = adapters.get_adapter("fenced_bash")(
        repo, cmd_stdin(make_mock(run_dir, body)), tmp_path / "prompt.md",
        run_dir, timeout_s=60,
    )
    assert r.returncode == 0, r.stderr
    assert "saw the payload" in r.stdout
    assert mock_invocations(run_dir) == 2


def test_fenced_bash_promptfile_placeholder(repo, tmp_path):
    """cmd_tmpl may take the prompt as a file path via {prompt}."""
    run_dir = tmp_path / "run"
    (tmp_path / "prompt.md").write_text("build the thing\n")
    body = "sys.stdout.write('prompt was: ' + data.strip())\n"
    r = adapters.get_adapter("fenced_bash")(
        repo, cmd_promptfile(make_mock(run_dir, body)),
        tmp_path / "prompt.md", run_dir, timeout_s=60,
    )
    assert r.returncode == 0, r.stderr
    assert "prompt was: build the thing" in r.stdout


def test_fenced_bash_no_blocks_ends_clean(repo, tmp_path):
    """Prose-only response: end the loop with rc 0 after one turn."""
    run_dir = tmp_path / "run"
    body = "sys.stdout.write('I am a chatty model, no code today')\n"
    r = adapters.get_adapter("fenced_bash")(
        repo, cmd_stdin(make_mock(run_dir, body)), tmp_path / "prompt.md",
        run_dir, timeout_s=60,
    )
    assert r.returncode == 0, r.stderr
    assert mock_invocations(run_dir) == 1


def test_fenced_bash_halt_sentinel_skips_blocks(repo, tmp_path):
    """HALT in the response wins: fenced blocks are NOT executed."""
    run_dir = tmp_path / "run"
    body = (
        "sys.stdout.write('HALT before doing anything\\n"
        "```bash\\necho side-effect > should_not_exist.txt\\n```')\n"
    )
    r = adapters.get_adapter("fenced_bash")(
        repo, cmd_stdin(make_mock(run_dir, body)), tmp_path / "prompt.md",
        run_dir, timeout_s=60,
    )
    assert r.returncode == 0, r.stderr
    assert not (repo / "should_not_exist.txt").exists()
    assert mock_invocations(run_dir) == 1


def test_fenced_bash_empty_block_continues(repo, tmp_path):
    """An empty fenced block executes trivially and the loop continues."""
    run_dir = tmp_path / "run"
    body = (
        "if n == 0:\n"
        "    out = '```bash\\n# nothing to do\\n```'\n"
        "else:\n"
        "    out = 'done HALT'\n"
        "sys.stdout.write(out)\n"
    )
    r = adapters.get_adapter("fenced_bash")(
        repo, cmd_stdin(make_mock(run_dir, body)), tmp_path / "prompt.md",
        run_dir, timeout_s=60,
    )
    assert r.returncode == 0, r.stderr
    assert mock_invocations(run_dir) == 2


def test_fenced_bash_turn_limit(repo, tmp_path):
    """Model never halts: stop at max_turns with a nonzero rc."""
    run_dir = tmp_path / "run"
    body = "sys.stdout.write('```bash\\necho spinning > spin.txt\\n```')\n"
    r = adapters.get_adapter("fenced_bash")(
        repo, cmd_stdin(make_mock(run_dir, body)), tmp_path / "prompt.md",
        run_dir, timeout_s=60, max_turns=2,
    )
    assert r.returncode != 0
    assert "turn limit" in r.stderr.lower()
    assert mock_invocations(run_dir) == 2


def test_fenced_bash_model_cmd_timeout(repo, tmp_path):
    """Model command exceeding the budget: rc 124, loop ends."""
    run_dir = tmp_path / "run"
    r = adapters.get_adapter("fenced_bash")(
        repo, f"{sys.executable} -c \"import time; time.sleep(30)\"",
        tmp_path / "prompt.md", run_dir, timeout_s=2,
    )
    assert r.returncode == 124


def test_fenced_bash_block_timeout(repo, tmp_path):
    """An extracted block exceeding the remaining budget: rc 124."""
    run_dir = tmp_path / "run"
    body = "sys.stdout.write('```bash\\nsleep 30\\n```')\n"
    r = adapters.get_adapter("fenced_bash")(
        repo, cmd_stdin(make_mock(run_dir, body)), tmp_path / "prompt.md",
        run_dir, timeout_s=2,
    )
    assert r.returncode == 124


# ------------------------------------------------- shell / noop compatibility

def test_shell_adapter_runs_cmd(repo, tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("hello")
    r = adapters.run_shell(repo, "echo prompt={prompt}", prompt, tmp_path / "rd", 30)
    assert r.returncode == 0
    assert f"prompt={prompt}" in r.stdout


def test_shell_adapter_empty_cmd_raises(repo, tmp_path):
    with pytest.raises(AdapterError):
        adapters.run_shell(repo, "", tmp_path / "prompt.md", tmp_path / "rd", 30)


def test_noop_adapter_dispatches_nothing(repo, tmp_path):
    r = adapters.run_noop(repo, "never run", tmp_path / "prompt.md", tmp_path / "rd", 30)
    assert r.returncode == 0
    assert "NOOP" in r.stdout
    subprocess.run(["true"])  # keep subprocess import meaningful on all legs
