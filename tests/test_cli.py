import json

from conftest import init_lane

from software_factory.cli import main


def test_cli_smoke(repo, capsys):
    assert main(["--repo", str(repo), "init", "--lane", "demo"]) == 0
    assert main(["--repo", str(repo), "status"]) == 0
    assert main(["--repo", str(repo), "digest"]) == 0
    assert main(["--repo", str(repo), "observe"]) == 0
    assert main(["--repo", str(repo), "version"]) == 0
    out = capsys.readouterr().out
    assert "lane:    demo" in out or "fingerprint" in out


def test_cli_ticket_add_and_log(repo, capsys):
    init_lane(repo)
    t = repo / ".factory" / "tickets" / "t9.md"
    t.write_text("# TICKET — t9\n## Goal\ng\n## Stages\ns\n## Constraints\nc\n")
    rc = main(["--repo", str(repo), "ticket", "add", "--id", "t9",
               "--title", "nine", "--ticket", ".factory/tickets/t9.md"])
    assert rc == 0
    assert main(["--repo", str(repo), "log", "--tail", "5"]) == 0
    out = capsys.readouterr().out
    assert "t9" in out


def test_cli_ask_flow(repo, capsys):
    init_lane(repo)
    rc = main(["--repo", str(repo), "ask", "create", "--subject", "packages",
               "--question", "install scipy?", "--options", "yes / no"])
    assert rc == 0
    ask_path = capsys.readouterr().out.strip().split()[-1]
    assert main(["--repo", str(repo), "ask", "list"]) == 0
    # operator answers by editing the file
    p = ask_path
    text = open(p).read().replace("status: PENDING", "status: ANSWERED")
    text += "\nYES — scipy, measured reason: fft missing\n"
    open(p, "w").write(text)
    from software_factory import human_gate
    assert human_gate.pending(repo) == []


def test_cli_gate_roundtrip(repo):
    init_lane(repo)
    assert main(["--repo", str(repo), "gate", "arm", "--kind", "demo",
                 "--phrase", "GO demo — now", "--", "true"]) == 0
    assert main(["--repo", str(repo), "gate", "status"]) == 0
    rc = main(["--repo", str(repo), "gate", "fire", "GO demo — now"])
    assert rc == 0


def test_ask_uniqueness_same_second(repo):
    from software_factory import human_gate
    init_lane(repo)
    p1 = human_gate.create(repo, "packages", "question 1?")
    p2 = human_gate.create(repo, "packages", "question 2?")
    p3 = human_gate.create(repo, "packages", "question 3?")
    assert len({p1, p2, p3}) == 3
    assert "question 1?" in p1.read_text(encoding="utf-8")
    assert "question 2?" in p2.read_text(encoding="utf-8")
    assert "question 3?" in p3.read_text(encoding="utf-8")
    assert len(human_gate.pending(repo)) == 3


def test_cli_ticket_set_lifecycle(repo, capsys):
    import subprocess
    init_lane(repo)
    t = repo / ".factory" / "tickets" / "t5.md"
    t.write_text("# TICKET — t5\n## Goal\ng\n## Stages\ns\n## Constraints\nc\n")
    assert main(["--repo", str(repo), "ticket", "add", "--id", "t5",
                 "--title", "five", "--ticket", ".factory/tickets/t5.md"]) == 0
    # unknown rung refused
    assert main(["--repo", str(repo), "ticket", "set", "nope",
                 "--status", "LANDED"]) == 1
    # prose commit handle refused at the source (observer would say PROSE)
    assert main(["--repo", str(repo), "ticket", "set", "t5",
                 "--commit", "this commit here"]) == 1
    # claim, then land with a real sha
    assert main(["--repo", str(repo), "ticket", "set", "t5",
                 "--claimed-by", "operator"]) == 0
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    assert main(["--repo", str(repo), "ticket", "set", "t5",
                 "--status", "LANDED", "--commit", sha]) == 0
    q = json.loads((repo / ".factory" / "queue_state.json").read_text())
    r = q["rungs"]["t5"]
    assert r["status"] == "LANDED" and r["commit"] == sha
    assert r["landed_at"] and r["claimed_at"]
    from software_factory import decision_log
    recs = decision_log.read_all(repo)
    assert any("rung_updated" in rec and rec["rung_updated"].get("status") == "LANDED"
               for rec in recs)


def test_cli_ask_answer_flow(repo, capsys):
    from pathlib import Path
    from software_factory import decision_log, human_gate
    init_lane(repo)
    assert main(["--repo", str(repo), "ask", "create", "--subject", "packages",
                 "--question", "install scipy?", "--options", "yes / no"]) == 0
    ask_path = Path(capsys.readouterr().out.strip().split()[-1])
    name = ask_path.name
    assert main(["--repo", str(repo), "ask", "answer", name,
                 "--answer", "YES — scipy"]) == 0
    text = ask_path.read_text(encoding="utf-8")
    assert "status: ANSWERED" in text
    assert "YES — scipy" in text and "answered_by: operator" in text
    assert "<operator writes here" not in text
    assert human_gate.pending(repo) == []
    assert any("ask_answered" in r for r in decision_log.read_all(repo))
    # never re-answer a closed ask
    assert main(["--repo", str(repo), "ask", "answer", name,
                 "--answer", "again"]) == 1
    # ambiguous prefix refused
    human_gate.create(repo, "packages", "second question?")
    assert main(["--repo", str(repo), "ask", "answer", "ASK",
                 "--answer", "x"]) == 1
    assert "ambiguous" in capsys.readouterr().out
