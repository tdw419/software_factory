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


# --- r8: subtree-scoped HEAD (watch paths) ---------------------------------
#
# A lane nested in a bigger repo must wake on commits touching ITS scope,
# not on every commit in the repo. digest.watch_paths (lane-relative
# pathspecs, default ["."] = the lane's own subtree) scopes the HEAD part
# to `git log -1 -- <paths>` instead of repo-global rev-parse HEAD.

def _monorepo(tmp_path):
    """parent repo with lane/ + incumbent/ subtrees, both committed."""
    import subprocess
    parent = tmp_path / "monorepo"
    parent.mkdir()
    subprocess.run(["git", "-C", str(parent), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(parent), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(parent), "config", "user.name", "t"], check=True)
    lane = parent / "lane"
    lane.mkdir()
    inc = parent / "incumbent"
    inc.mkdir()
    (lane / "code.py").write_text("x = 1\n")
    (inc / "book.json").write_text("{}\n")
    subprocess.run(["git", "-C", str(parent), "add", "lane", "incumbent"], check=True)
    subprocess.run(["git", "-C", str(parent), "commit", "-qm", "seed both"], check=True)
    return parent, lane, inc


def test_r8_foreign_subtree_commit_does_not_wake(tmp_path):
    parent, lane, inc = _monorepo(tmp_path)
    a = compute(lane).stable
    (inc / "book.json").write_text('{"tick": 354}\n')
    git(parent, "add", "incumbent")
    git(parent, "commit", "-qm", "incumbent tick")
    b = compute(lane).stable
    assert a == b, "foreign-subtree commit must not move the lane fingerprint"


def test_r8_own_subtree_commit_wakes(tmp_path):
    parent, lane, inc = _monorepo(tmp_path)
    a = compute(lane).stable
    (lane / "code.py").write_text("x = 2\n")
    git(parent, "add", "lane")
    git(parent, "commit", "-qm", "lane work")
    b = compute(lane).stable
    assert a != b


def test_r8_watch_paths_narrower_than_lane(tmp_path):
    parent, lane, inc = _monorepo(tmp_path)
    (lane / "docs").mkdir()
    (lane / "docs" / "note.md").write_text("n\n")
    (lane / "src").mkdir()
    (lane / "src" / "core.rs").write_text("fn f() {}\n")
    git(parent, "add", "lane")
    git(parent, "commit", "-qm", "lane docs+src")
    a = compute(lane, watch_paths=["src"]).stable
    # commit touching the lane but OUTSIDE watch paths: no wake
    (lane / "docs" / "note.md").write_text("n2\n")
    git(parent, "add", "lane/docs")
    git(parent, "commit", "-qm", "docs only")
    b = compute(lane, watch_paths=["src"]).stable
    assert a == b
    # commit INSIDE watch paths: wake
    (lane / "src" / "core.rs").write_text("fn g() {}\n")
    git(parent, "add", "lane/src")
    git(parent, "commit", "-qm", "src change")
    c = compute(lane, watch_paths=["src"]).stable
    assert a != c


def test_r8_head_none_when_no_history_touches_watch_paths(tmp_path):
    parent, lane, inc = _monorepo(tmp_path)
    fp = compute(lane, watch_paths=["ghost_dir"])
    assert fp.parts["HEAD"] == "NONE"
    assert not fp.degraded
    # and the fingerprint is stable across repeats
    assert compute(lane, watch_paths=["ghost_dir"]).stable == fp.stable


def test_r8_root_lane_default_head_is_repo_head(repo):
    # v0.4.0 byte-compat: a repo-root lane with default watch_paths hashes
    # the same repo-global HEAD it always did
    init_lane(repo)
    fp = compute(repo)
    assert fp.parts["HEAD"] == git(repo, "rev-parse", "HEAD")[:12]


def test_r8_incumbent_bookkeeping_excluded_by_config(tmp_path):
    # the geometry_os pilot shape: lane dir holds .builder_queue/ (an
    # incumbent lane's bookkeeping) next to systems/ (the work subtree);
    # digest.watch_paths from CONFIG must exclude incumbent commits
    import json
    parent, lane, inc = _monorepo(tmp_path)
    bq = lane / ".builder_queue"
    bq.mkdir()
    sysd = lane / "systems"
    sysd.mkdir()
    (bq / "QUEUE_STATE.json").write_text("{}\n")
    (sysd / "bridge.rs").write_text("fn main() {}\n")
    git(parent, "add", "lane")
    git(parent, "commit", "-qm", "lane seed")
    fdir = lane / ".factory"
    fdir.mkdir()
    (fdir / "config.json").write_text(
        json.dumps({"digest": {"watch_paths": ["systems"]}}))
    a = compute(lane).stable
    (bq / "QUEUE_STATE.json").write_text('{"tick": 354}\n')
    git(parent, "add", "lane/.builder_queue")
    git(parent, "commit", "-qm", "incumbent bookkeeping")
    b = compute(lane).stable
    assert a == b, "config watch_paths must scope HEAD; incumbent churn must not wake"
    (sysd / "bridge.rs").write_text("fn main() { /* v2 */ }\n")
    git(parent, "add", "lane/systems")
    git(parent, "commit", "-qm", "bridge work")
    c = compute(lane).stable
    assert a != c


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
