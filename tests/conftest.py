import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def init_lane(rd, lane="lane", verify_cmd="", builder_cmd=""):
    from software_factory.cli import main
    argv = ["--repo", str(rd), "init", "--lane", lane]
    if verify_cmd:
        argv += ["--verify-cmd", verify_cmd]
    if builder_cmd:
        argv += ["--builder-cmd", builder_cmd]
    rc = main(argv)
    assert rc == 0


import pytest


@pytest.fixture
def repo(tmp_path):
    rd = tmp_path / "proj"
    rd.mkdir()
    git(rd, "init", "-q", "-b", "main")
    git(rd, "config", "user.email", "t@t.local")
    git(rd, "config", "user.name", "tester")
    (rd / "README.md").write_text("proj\n")
    (rd / "app.py").write_text("print('v1')\n")
    git(rd, "add", "README.md", "app.py")
    git(rd, "commit", "-qm", "init")
    return rd
