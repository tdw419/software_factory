"""Shared helpers: atomic writes, timestamps, git shells."""

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    """UTC timestamp, ISO with offset — the live lane's log format."""
    return datetime.now(timezone.utc).isoformat()


def atomic_write_text(path: Path, text: str) -> None:
    """Write via tmp+rename so a crash never leaves a half-written state file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def dump_json(path: Path, obj) -> None:
    """JSON with ensure_ascii=False — raw UTF-8 (em dashes) must survive
    byte-identically; \\u2014 escapes broke the live lane's GO matcher."""
    atomic_write_text(Path(path), json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def git(repo, *args, timeout=30):
    """Run git in repo; returns CompletedProcess (never raises on nonzero)."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=timeout,
    )


def git_root(repo):
    """Resolve the git toplevel OWNING repo (None if not under a repo).

    Lanes may live in a subdirectory of a larger repo (the live lane does);
    every digest/status decision must use the owning toplevel, never the
    enclosing filesystem, or a parent repo's state silently bleeds in.
    """
    r = git(repo, "rev-parse", "--show-toplevel")
    if r.returncode != 0:
        return None
    return Path(r.stdout.strip())


def sh(cmd_argv, timeout, cwd=None, env=None):
    """Run a command under an explicit timeout (lane rule 8: never bare)."""
    return subprocess.run(
        cmd_argv, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env,
    )
