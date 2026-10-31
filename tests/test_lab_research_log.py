"""Trial counting and the frozen holdout. No network, no Nautilus."""

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")

from nautilus_lab import cli, research_log as rl

# addresses whose sha256 prefix decides the hash rule (found once; asserted below so a change is loud)
H1, D1 = "A" * 44, "B" * 44


def test_hash_rule_is_deterministic_and_the_fixture_addresses_are_what_we_think(tmp_path):
    path = tmp_path / "holdout.json"
    rl.holdout_state(path)
    holds = {a: rl.is_holdout(a, path) for a in (H1, D1)}
    assert holds == {a: rl.is_holdout(a, path) for a in (H1, D1)}
    pools = [chr(65 + i) * 44 for i in range(26)]
    share = sum(rl.is_holdout(p, path) for p in pools) / len(pools)
    assert 0.1 <= share <= 0.5  # roughly 30%, chosen by hash and not by results


def test_contaminated_pools_can_never_be_holdout(tmp_path):
    path = tmp_path / "holdout.json"
    pools = [chr(65 + i) * 44 for i in range(26)]
    hashed = [p for p in pools if int(__import__("hashlib").sha256(p.encode()).hexdigest()[:8], 16) % 10 < 3]
    assert hashed, "fixture needs at least one hash-holdout pool"
    rl.holdout_state(path, contaminated=[hashed[0][:8]])
    assert not rl.is_holdout(hashed[0], path)
    assert all(rl.is_holdout(p, path) for p in hashed[1:])


def test_holdout_opens_exactly_once(tmp_path):
    path = tmp_path / "holdout.json"
    rl.holdout_state(path)
    rl.open_holdout("abc123", path)
    with pytest.raises(PermissionError, match="already opened"):
        rl.open_holdout("def456", path)


def test_trial_count_includes_untracked_history_and_dedups_identical_configs(tmp_path):
    path = tmp_path / "trials.json"
    assert rl.trial_count(path) == rl.PRIOR_UNTRACKED_TRIALS
    a = rl.record_trial({"delay": 1, "momentum": {}}, path)
    assert a == rl.PRIOR_UNTRACKED_TRIALS + 1
    assert rl.record_trial({"momentum": {}, "delay": 1}, path) == a  # same config, key order irrelevant
    assert rl.record_trial({"delay": 0, "momentum": {}}, path) == a + 1  # a different setting costs a trial


def test_dev_runs_exclude_the_holdout_and_holdout_runs_see_nothing_else(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    pools = [chr(65 + i) * 44 for i in range(26)]
    rl.holdout_state()
    hold = [p for p in pools if rl.is_holdout(p)]
    dev = [p for p in pools if not rl.is_holdout(p)]
    files = [Path(f"{p}.csv") for p in pools]

    def split(open_holdout):
        ds, fl = [(p[:8], object()) for p in pools], list(files)
        note = cli._split_holdout(ds, fl, SimpleNamespace(synthetic=False, open_holdout=open_holdout))
        return [f.stem for f in fl], note

    kept, note = split(False)
    assert kept == dev and f"{len(hold)} holdout pool(s) untouched" in note
    assert "excluded from this development run" in capsys.readouterr().out
    kept, note = split(True)
    assert kept == hold and note.startswith("HOLDOUT run")
    # a file without an address-like name is never holdout
    ds, fl = [("custom", object())], [Path("my_custom.csv")]
    cli._split_holdout(ds, fl, SimpleNamespace(synthetic=False, open_holdout=False))
    assert fl == [Path("my_custom.csv")]
