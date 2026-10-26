from copybot.harvester import Candidate, evenly_spaced, rank_candidates


def test_mid_wave_sampling_spans_the_whole_history():
    sigs = list(range(5000))
    picked = evenly_spaced(sigs, 100)
    assert len(picked) == 100 and picked[0] == 0 and picked[-1] >= 4900  # not just the latest page
    assert evenly_spaced([1, 2], 10) == [1, 2]


def test_multi_token_wallets_rank_first():
    one = Candidate("one", {"A": {"buys": 3, "sells": 3, "sol": 50.0}})
    multi = Candidate("multi", {"A": {"buys": 1, "sells": 0, "sol": 1.0}, "B": {"buys": 1, "sells": 1, "sol": 1.0}})
    seller = Candidate("seller", {"C": {"buys": 0, "sells": 2, "sol": 2.0}})
    assert [c.address for c in rank_candidates({c.address: c for c in (one, multi, seller)})] == ["multi", "one", "seller"]
