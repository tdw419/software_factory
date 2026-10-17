"""Human gate — file-based ASK queue for operator decisions.

The builder-lane pattern: an agent that hits a decision it must not take
alone writes a PENDING ask with exact options; the operator answers by
editing the file. Files are the queue — no database, no daemon, and the
answers commit with provenance like everything else.
"""

import time
from pathlib import Path

from .common import atomic_write_text


def asks_dir(repo) -> Path:
    return Path(repo) / ".factory" / "asks"


def create(repo, subject: str, question: str, options: str = "",
           actor: str = "lane") -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    slug = "".join(c if c.isalnum() else "-" for c in subject.lower())[:40].strip("-")
    p = asks_dir(repo) / f"ASK-{ts}-{slug}.md"
    body = (
        f"# ASK — {subject}\n\n"
        f"status: PENDING\n"
        f"asked_by: {actor}\nasked_ts: {time.strftime('%Y-%m-%dT%H:%M:%S')}\n\n"
        f"## Question\n{question}\n\n"
        + (f"## Options\n{options}\n\n" if options else "")
        + "## Answer\n<operator writes here, then sets status: ANSWERED>\n"
    )
    atomic_write_text(p, body)
    return p


def list_asks(repo):
    out = []
    d = asks_dir(repo)
    if not d.is_dir():
        return out
    for p in sorted(d.glob("ASK-*.md")):
        status = "UNKNOWN"
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.startswith("status:"):
                status = ln.split(":", 1)[1].strip()
                break
        out.append((str(p), status))
    return out


def pending(repo):
    return [p for p, s in list_asks(repo) if s.upper() == "PENDING"]
