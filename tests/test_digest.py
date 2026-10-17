from conftest import git, init_lane

from software_factory.digest import compute


def test_stable_when_nothing_changes(repo):
    a = compute(repo).stable
    b = compute(repo).stable
    assert a == b
    assert a != "DEGRADED"


def test_head_commit_wakes(repo):
    a = compute(repo).stable
    (repo / "app.py").write_text("print('v2')\n")
    git(repo, "add", "app.py")
    git(repo, "commit", "-qm", "v2")
    b = compute(repo).stable
    assert a != b


def test_tree_dirt_wakes(repo):
    a = compute(repo).stable
    (repo / "new.txt").write_text("x\n")
    b = compute(repo).stable
    assert a != b
    assert "TREE" in compute(repo).parts and compute(repo).parts["TREE"] != "CLEAN"


def test_churn_allowlist_does_not_wake(repo):
    init_lane(repo)
    before = compute(repo).stable
    # lane churn: decision log appends + run markers must NOT wake the tick
    with open(repo / ".factory" / "decision_log.jsonl", "a") as f:
        f.write('{"actor":"test","note":"churn — em dash"}\n')
    (repo / ".factory" / "runs").mkdir(exist_ok=True)
    (repo / ".factory" / "runs" / "20260101T000000-suppressed").write_text("x\n")
    after = compute(repo).stable
    assert before == after


def test_git_internal_state_never_wakes(repo):
    a = compute(repo).stable
    (repo / ".git" / "FETCH_HEAD").write_text("noise\n")
    (repo / ".git" / "HEAD.lock").write_text("noise\n")
    b = compute(repo).stable
    assert a == b


def test_degraded_when_git_unreadable(tmp_path, monkeypatch):
    empty = tmp_path / "not_a_repo"
    empty.mkdir()
    # ceiling: forbid git from discovering any repo above the tmp dir
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    fp = compute(empty)
    assert fp.degraded
    assert fp.stable == "DEGRADED"


def test_nested_lane_scopes_to_own_subtree(tmp_path):
    import os

    import subprocess

    parent = tmp_path / "monorepo"
    parent.mkdir()
    subprocess.run(["git", "-C", str(parent), "init", "-q", "-b", "main"], check=True)
    lane = parent / "services" / "my_lane"
    lane.mkdir(parents=True)
    subprocess.run(["git", "-C", str(parent), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(parent), "config", "user.name", "t"], check=True)
    (lane / "code.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(parent), "add", "services/my_lane/code.py"], check=True)
    subprocess.run(["git", "-C", str(parent), "commit", "-qm", "init lane"], check=True)

    a = compute(lane).stable
    # dirt OUTSIDE the lane subtree must not wake the lane
    (parent / "unrelated.txt").write_text("noise\n")
    b = compute(lane).stable
    assert a == b
    # dirt INSIDE the lane subtree wakes it
    (lane / "code.py").write_text("x = 2\n")
    c = compute(lane).stable
    assert a != c


def test_ladder_lines_hash_in(repo, tmp_path):
    ladder = repo / "ROADMAP.md"
    ladder.write_text("- Rung 0: baseline\n- Rung 1: next\n")
    git(repo, "add", "ROADMAP.md")
    git(repo, "commit", "-qm", "roadmap")
    cfg = {"path": "ROADMAP.md", "line_prefix": "- Rung"}
    a = compute(repo, ladder=cfg).stable
    ladder.write_text("- Rung 0: baseline\n- Rung 1: NEXT (edited)\n")
    git(repo, "add", "ROADMAP.md")
    git(repo, "commit", "-qm", "roadmap edit")
    b = compute(repo, ladder=cfg).stable
    assert a != b


def test_allowlist_path_separator_boundary(repo):
    init_lane(repo)
    before = compute(repo).stable
    # .factory/runs/ is allowlisted, so files inside it do not wake
    (repo / ".factory" / "runs" / "m1").write_text("ok\n")
    assert compute(repo).stable == before
    # .factory/runs_backup/x shares a string prefix with .factory/runs,
    # but is NOT under .factory/runs/ on a path-separator boundary
    (repo / ".factory" / "runs_backup").mkdir(exist_ok=True)
    (repo / ".factory" / "runs_backup" / "x").write_text("dirty\n")
    after = compute(repo).stable
    assert before != after
    assert compute(repo).parts["TREE"] != "CLEAN"
