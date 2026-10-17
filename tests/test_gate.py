import pytest

from conftest import init_lane

from software_factory import decision_log, gate

PHRASE = "GO scanout — laptop"          # em dash, the canonical near-miss
PHRASE_ASCII = "GO scanout - laptop"    # the byte-different impostor


@pytest.fixture(autouse=True)
def lane(repo):
    init_lane(repo)
    return repo


def test_fire_with_nothing_armed(repo):
    code, rec = gate.fire(repo, PHRASE)
    assert code == 2


def test_wrong_phrase_refused_byte_exact(repo):
    gate.arm(repo, "scanout", PHRASE, ["true"])
    code, rec = gate.fire(repo, PHRASE_ASCII)   # hyphen instead of em dash
    assert code == 3
    assert rec["gate_refused"]["reason"] == "phrase_mismatch"
    assert gate.pending(repo) is not None       # gate stays armed


def test_dry_run_preflight_then_real_fire(repo, tmp_path):
    marker = tmp_path / "fired"
    gate.arm(repo, "scanout", PHRASE, ["touch", str(marker)])
    code, rec = gate.fire(repo, PHRASE, dry_run=True)
    assert code == 0 and rec["gate_preflight"] == "ok"
    assert not marker.exists()
    code, rec = gate.fire(repo, PHRASE)
    assert code == 0
    assert marker.exists()
    assert gate.pending(repo) is None
    recs = decision_log.read_all(repo)
    kinds = [k for r in recs for k in r]
    assert "scanout_go" in kinds and "scanout_result" in kinds


def test_un_aborted_go_blocks_refire(repo):
    gate.arm(repo, "scanout", PHRASE, ["true"])
    code, _ = gate.fire(repo, PHRASE)
    assert code == 0
    gate.arm(repo, "scanout", PHRASE, ["true"])
    code, rec = gate.fire(repo, PHRASE)
    assert code == 3
    assert rec["gate_refused"]["reason"] == "un-aborted GO already spent"


def test_abort_unblocks_and_clears_pending(repo):
    gate.arm(repo, "scanout", PHRASE, ["true"])
    gate.abort(repo, "scanout", "operator changed mind")
    assert gate.pending(repo) is None
    assert decision_log.un_abortedgos(repo, "scanout") == []
    gate.arm(repo, "scanout", PHRASE, ["true"])
    code, _ = gate.fire(repo, PHRASE)
    assert code == 0


def test_op_failure_recorded_and_pending_cleared(repo):
    gate.arm(repo, "scanout", PHRASE, ["false"])
    code, rec = gate.fire(repo, PHRASE)
    assert code == 1
    assert rec["scanout_result"]["exit"] == 1
    assert gate.pending(repo) is None
