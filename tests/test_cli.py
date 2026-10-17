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
