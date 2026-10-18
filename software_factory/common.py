"""Shared helpers: atomic writes, timestamps, git shells, hashing, paths."""

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    """UTC timestamp, ISO with offset — the live lane's log format."""
    return datetime.now(timezone.utc).isoformat()


def sha_hex(data: str, length: int = 16) -> str:
    """Truncated SHA-256 hex digest of UTF-8 string."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:length]


def sha16(data: str) -> str:
    return sha_hex(data, 16)


def sha12(data: str) -> str:
    return sha_hex(data, 12)


def factory_dir(repo) -> Path:
    """Return the .factory directory path for a repository."""
    return Path(repo) / ".factory"


#: Paths whose churn must never wake the lane. Directories match by prefix.
DEFAULT_ALLOWLIST = (
    ".factory/decision_log.jsonl",
    ".factory/state.json",
    ".factory/runs/",
    ".factory/asks/",
    ".factory/pending_gate.json",
    ".factory/tick.lock",
)

REQUIRED_RECEIPT_SECTIONS = (
    "## What PASS proves",
    "## What this does NOT prove",
)

#: Receipts must carry at least one fenced code block under this heading
#: (paired command + output evidence).
RECEIPT_FENCE_HEADING = "## Commands and outputs"


def resolve_allowlist(repo, allowlist=None) -> tuple:
    """Resolve the churn allowlist for repo from explicit arg, .factory/config.json,
    or DEFAULT_ALLOWLIST — single source of truth for digest and observer."""
    if allowlist is not None:
        return tuple(allowlist)
    cfg_path = factory_dir(repo) / "config.json"
    if cfg_path.exists():
        try:
            cfg = load_json(cfg_path)
            cfg_allow = cfg.get("digest", {}).get("churn_allowlist")
            if cfg_allow is not None:
                return tuple(cfg_allow)
        except Exception:
            pass
    return DEFAULT_ALLOWLIST


def validate_receipt(path: Path) -> list:
    """Validate that a receipt file exists, is a regular file, contains all
    required sections (including 'What this does NOT prove'), and carries at
    least one fenced code block under '## Commands and outputs'.
    Returns a list of problems: missing section headers, or
    '<no fenced code block under ## Commands and outputs>'
    (or ['<missing>'] if file absent)."""
    path = Path(path)
    if not path.is_file():
        return ["<missing>"]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ["<unreadable>"]
    missing = [sec for sec in REQUIRED_RECEIPT_SECTIONS if sec not in text]
    if not has_fenced_block_under(text, RECEIPT_FENCE_HEADING):
        missing.append(f"<no fenced code block under {RECEIPT_FENCE_HEADING}>")
    return missing


def has_fenced_block_under(text: str, heading: str) -> bool:
    """True if the section starting with `heading` contains at least one
    fenced code block (a line starting with ``` ... closed by a later ```
    line, or still open at end of text)."""
    in_section = False
    in_fence = False
    for ln in text.splitlines():
        if not in_fence and ln.startswith("## "):
            in_section = ln.startswith(heading)
            continue
        if not in_section:
            continue
        if ln.lstrip().startswith("```"):
            if in_fence:
                return True  # a block opened and closed inside the section
            in_fence = True
    return in_fence  # unterminated trailing fence still shows a block


def is_under_allowlist(path: str, allowlist) -> bool:
    """Check if a lane-relative path matches any entry in the churn allowlist
    on a proper path-separator boundary."""
    path = path.strip()
    if " -> " in path:
        # git status --porcelain rename format: "R  old -> new"
        parts = [p.strip().strip('"') for p in path.split(" -> ", 1)]
        return all(_single_path_under_allowlist(p, allowlist) for p in parts)
    return _single_path_under_allowlist(path.strip('"'), allowlist)


def _strip_dot_slash(p: str) -> str:
    while p.startswith("./"):
        p = p[2:]
    return p


def _single_path_under_allowlist(path: str, allowlist) -> bool:
    path = _strip_dot_slash(path)
    for a in allowlist:
        a_clean = _strip_dot_slash(a.strip()).rstrip("/")
        if not a_clean:
            continue
        if path == a_clean or path.startswith(a_clean + "/"):
            return True
    return False


#: Default kernel files whose modification requires a fired kind="kernel_edit" GO
#: when kernel_guard is enabled (or when kernel_paths is non-empty).
DEFAULT_KERNEL_PATHS = ()


def resolve_kernel_paths(repo, kernel_paths=None) -> tuple:
    """Resolve protected kernel paths for repo from explicit arg or .factory/config.json."""
    if kernel_paths is not None:
        return tuple(kernel_paths)
    cfg_path = factory_dir(repo) / "config.json"
    if cfg_path.exists():
        try:
            cfg = load_json(cfg_path)
            kp = cfg.get("kernel_paths")
            if kp is not None:
                return tuple(kp)
        except Exception:
            pass
    return DEFAULT_KERNEL_PATHS


def touched_kernel_paths(repo, base_rev: str, target_rev: str = "HEAD",
                         include_working_tree: bool = True,
                         kernel_paths=None) -> list:
    """Return sorted list of lane-relative paths matching kernel_paths that were
    modified between base_rev and target_rev (plus uncommitted working-tree edits
    if include_working_tree=True)."""
    repo = Path(repo)
    kpaths = resolve_kernel_paths(repo, kernel_paths)
    if not kpaths:
        return []
    root = git_root(repo)
    if root is None:
        return []
    rel = os.path.relpath(repo, root)
    changed = set()

    if base_rev and base_rev != "UNREADABLE" and target_rev and target_rev != "UNREADABLE":
        r = git(root, "diff", "--name-only", base_rev, target_rev)
        if r.returncode == 0:
            for ln in r.stdout.splitlines():
                if ln.strip():
                    changed.add(ln.strip())

    if include_working_tree:
        st = git(root, "status", "--porcelain", "-uall")
        if st.returncode == 0:
            for ln in st.stdout.splitlines():
                if not ln.strip():
                    continue
                p = ln[3:] if len(ln) > 3 else ln
                changed.add(p.split(" -> ", 1)[-1].strip().strip('"'))

    matched = []
    for p in sorted(changed):
        if rel != ".":
            prefix = rel + os.sep
            if not (p == rel or p.startswith(prefix)):
                continue
            p_rel = os.path.relpath(p, rel)
        else:
            p_rel = p
        if is_under_allowlist(p_rel, kpaths):
            matched.append(p_rel)
    return matched


def scoped_dirty_rows(repo, allowlist=None) -> tuple:
    """Return (ok: bool, rows: list[str]) of dirty git status lines scoped to repo
    and filtered by allowlist."""
    repo = Path(repo)
    allowlist = resolve_allowlist(repo, allowlist)
    root = git_root(repo)
    if root is None:
        return False, []
    st = git(root, "status", "--porcelain", "-uall")
    if st.returncode != 0:
        return False, []
    rel = os.path.relpath(repo, root)
    rows = []
    for ln in st.stdout.splitlines():
        if not ln.strip():
            continue
        p = ln[3:] if len(ln) > 3 else ln
        p_check = p.split(" -> ", 1)[-1].strip().strip('"')
        if rel != ".":
            prefix = rel + os.sep
            if not (p_check == rel or p_check.startswith(prefix)):
                continue  # outside the lane's subtree
            p_rel = os.path.relpath(p_check, rel)
        else:
            p_rel = p_check
        if not is_under_allowlist(p_rel, allowlist):
            rows.append(ln)
    return True, rows


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
