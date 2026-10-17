"""Human gate — file-based ASK queue for operator decisions.

The builder-lane pattern: an agent that hits a decision it must not take
alone writes a PENDING ask with exact options; the operator answers by
editing the file. Files are the queue — no database, no daemon, and the
answers commit with provenance like everything else.
"""

import time
from pathlib import Path

from . import decision_log, queue_state
from .common import atomic_write_text


class AskError(Exception):
    pass


def asks_dir(repo) -> Path:
    return queue_state.factory_dir(repo) / "asks"


def create(repo, subject: str, question: str, options: str = "",
           actor: str = "lane") -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    slug = "".join(c if c.isalnum() else "-" for c in subject.lower())[:40].strip("-") or "ask"
    d = asks_dir(repo)
    p = d / f"ASK-{ts}-{slug}.md"
    seq = 2
    while p.exists():
        p = d / f"ASK-{ts}-{slug}-{seq}.md"
        seq += 1
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


def _resolve_ask(repo, ask_ref: str) -> Path:
    """Resolve an ask by absolute path, basename, or unique name prefix."""
    cands = [p for p in sorted(asks_dir(repo).glob("ASK-*.md"))
             if ask_ref in (str(p), p.name) or p.name.startswith(ask_ref)]
    if not cands:
        raise AskError(f"no ask matches {ask_ref!r}")
    if len(cands) > 1 and ask_ref not in (str(cands[0]), cands[0].name):
        raise AskError(f"ambiguous ask ref {ask_ref!r}: matches "
                       + ", ".join(p.name for p in cands))
    return cands[0]


def answer(repo, ask_ref: str, answer: str, actor: str = "operator") -> Path:
    """Answer a PENDING ask: flip status, fill the Answer section, and append
    a decision_log record so the answer carries provenance like everything
    else on the lane. Refusing to re-answer keeps the record append-only."""
    p = _resolve_ask(repo, ask_ref)
    text = p.read_text(encoding="utf-8")
    status = "UNKNOWN"
    for ln in text.splitlines():
        if ln.startswith("status:"):
            status = ln.split(":", 1)[1].strip()
            break
    if status.upper() != "PENDING":
        raise AskError(f"{p.name} is {status}, not PENDING — never re-answer a closed ask")
    text = text.replace("status: PENDING", "status: ANSWERED", 1)
    placeholder = "<operator writes here, then sets status: ANSWERED>"
    filled = f"{answer}\n(answered_by: {actor})"
    if placeholder in text:
        text = text.replace(placeholder, filled, 1)
    else:
        text = text.replace("## Answer", f"## Answer\n{filled}", 1)
    atomic_write_text(p, text)
    decision_log.append(repo, {
        "actor": actor,
        "ask_answered": {"ask": p.name, "answer": answer},
    })
    return p
