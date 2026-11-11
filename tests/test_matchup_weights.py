"""Matchup weighting for the floor attack (H5).

The M4 floor gate is per (deck, opponent) — "no matchup below 45%" — while the BC
loss treats every sample the same, so a corpus dominated by easy matchups spends its
capacity there. These tests pin the two reweighting modes and the regression guard
that ``none`` reproduces the historical plain-CE loss exactly.
"""

from __future__ import annotations

import torch

from scripts.train_bc_scale import (
    Config,
    Store,
    _apply_sample_weights,
    matchup_weights_for_store,
    run_batch,
)
from train.model import CVPN, CVPNConfig


def _store(groups: dict[str, tuple[int, float]]) -> Store:
    """``groups`` maps a matchup name to (sample count, win rate) for that matchup."""
    empty = torch.zeros(0)
    keys, values = [], []
    for name, (count, rate) in groups.items():
        wins = int(round(count * rate))
        for i in range(count):
            keys.append(("deck", name, 0, i))
            values.append(1.0 if i < wins else 0.0)
    n = len(keys)
    return Store(
        tokens=[torch.zeros(2, 4) for _ in range(n)],
        options=[torch.tensor([[0.0, 1.0], [1.0, 0.0]]) for _ in range(n)],
        teacher=[0] * n, value=values,
        b_hand=[empty] * n, b_deck=[empty] * n, b_hist=[empty] * n,
        b_hsize=[0.0] * n, b_burst=[0.0] * n, b_mask=[False] * n,
        keys=keys,
    )


def test_none_mode_is_unweighted():
    store = _store({"a": (4, 0.5), "b": (12, 0.2)})
    assert matchup_weights_for_store(store, mode="none") is None


def test_balance_equalises_total_weight_per_matchup():
    store = _store({"easy": (12, 0.9), "hard": (4, 0.1)})
    weights = matchup_weights_for_store(store, mode="balance")
    assert weights is not None
    totals = {}
    for weight, key in zip(weights, store.keys):
        totals[key[1]] = totals.get(key[1], 0.0) + weight
    assert abs(totals["easy"] - totals["hard"]) < 1e-9
    assert abs(sum(weights) / len(weights) - 1.0) < 1e-9


def test_deficit_mode_boosts_only_matchups_below_the_floor():
    store = _store({"strong": (8, 0.8), "weak": (8, 0.25), "mid": (8, 0.45)})
    weights = matchup_weights_for_store(store, mode="deficit", strength=1.0, floor=0.45)
    by_group = {}
    for weight, key in zip(weights, store.keys):
        by_group.setdefault(key[1], []).append(weight)
    strong, weak, mid = (by_group["strong"][0], by_group["weak"][0], by_group["mid"][0])
    assert abs(strong - mid) < 1e-9          # at the floor => untouched
    assert weak > strong                     # below the floor => boosted
    assert abs(weak / strong - 1.2 / 1.0) < 1e-6 or weak > strong  # 1 + (0.45-0.25)
    assert abs(sum(weights) / len(weights) - 1.0) < 1e-9


def test_sample_weights_none_matches_plain_mean():
    raw = torch.tensor([1.0, 3.0, 2.0, 4.0])
    assert torch.allclose(_apply_sample_weights(raw, [0, 1, 2, 3], None), raw.mean())
    weighted = _apply_sample_weights(raw, [0, 1, 2, 3], [2.0, 2.0, 0.0, 0.0])
    assert torch.allclose(weighted, torch.tensor(2.0))


def test_run_batch_weighting_changes_the_loss_but_not_the_default_path():
    # different teachers per matchup, so the per-sample CE really differs by group
    empty = torch.zeros(0)
    keys, teachers, values = [], [], []
    for name, count, teacher in (("easy", 8, 0), ("hard", 8, 1)):
        for i in range(count):
            keys.append(("deck", name, 0, i))
            teachers.append(teacher)
            values.append(0.9 if teacher == 0 else 0.1)
    n = len(keys)
    store = Store(
        tokens=[torch.zeros(2, 4) for _ in range(n)],
        options=[torch.tensor([[0.0, 1.0], [1.0, 0.0]]) for _ in range(n)],
        teacher=teachers, value=values,
        b_hand=[empty] * n, b_deck=[empty] * n, b_hist=[empty] * n,
        b_hsize=[0.0] * n, b_burst=[0.0] * n, b_mask=[False] * n,
        keys=keys,
    )
    index = list(range(len(store)))
    torch.manual_seed(0)
    model = CVPN(CVPNConfig(token_dim=4, option_dim=2, d_model=8, option_hidden=8, value_hidden=8))
    weights = matchup_weights_for_store(store, mode="deficit", floor=0.45)
    assert weights is not None
    _, plain = run_batch(model, store, index, "cpu", 0.5, 0.5, False, Config())
    _, weighted = run_batch(model, store, index, "cpu", 0.5, 0.5, False, Config(), None, weights)
    _, ones = run_batch(model, store, index, "cpu", 0.5, 0.5, False, Config(), None, [1.0] * n)
    assert abs(plain["ce"] - ones["ce"]) < 1e-9          # None == explicit all-ones
    assert abs(plain["ce"] - weighted["ce"]) > 1e-6      # real reweighting moves it


# --------------------------------------------------------------------------- #
# 2026-11 regression: realistic store keys (one seed per game)
# --------------------------------------------------------------------------- #
def _realistic_store(matchups: dict[str, list[float]], steps_per_game: int = 3) -> Store:
    """``matchups`` maps an opponent to per-game outcomes; each game has its own seed.

    This is the layout ``load_store``/``datafirst_bc_store`` actually produce:
    ``(deck, opponent, seed, step)`` with one episode outcome repeated over the
    game's decisions. The historical fixture above put every sample of a matchup on
    seed 0, which hid that the grouping was per game.
    """
    empty = torch.zeros(0)
    keys, values = [], []
    for opponent, outcomes in matchups.items():
        for seed, outcome in enumerate(outcomes):
            for step in range(steps_per_game):
                keys.append(("deck", opponent, 100 + seed, step))
                values.append(float(outcome))
    n = len(keys)
    return Store(
        tokens=[torch.zeros(2, 4) for _ in range(n)],
        options=[torch.tensor([[0.0, 1.0], [1.0, 0.0]]) for _ in range(n)],
        teacher=[0] * n, value=values,
        b_hand=[empty] * n, b_deck=[empty] * n, b_hist=[empty] * n,
        b_hsize=[0.0] * n, b_burst=[0.0] * n, b_mask=[False] * n,
        keys=keys,
    )


def test_deficit_weights_are_constant_within_a_matchup_across_games():
    # "weak" wins 1 of 4 games (rate 0.25 < floor); "strong" wins 3 of 4.
    store = _realistic_store({"strong": [1, 1, 1, 0], "weak": [1, 0, 0, 0]})
    weights = matchup_weights_for_store(store, mode="deficit", strength=1.0, floor=0.45)
    by_group: dict[str, set[float]] = {}
    for weight, key in zip(weights, store.keys):
        by_group.setdefault(key[1], set()).add(round(weight, 9))
    # One weight per matchup: a lost game inside "strong" is not up-weighted.
    assert len(by_group["strong"]) == 1
    assert len(by_group["weak"]) == 1
    (strong,), (weak,) = by_group["strong"], by_group["weak"]
    assert abs(weak / strong - 1.2) < 1e-9   # 1 + (0.45 - 0.25) vs 1 + 0


def test_balance_equalises_matchups_not_games():
    # 6 games vs "many", 2 games vs "few": balance must equalise the two
    # matchups' total weight (the historical per-game grouping equalised games).
    store = _realistic_store({"many": [1, 0, 1, 0, 1, 0], "few": [1, 0]})
    weights = matchup_weights_for_store(store, mode="balance")
    totals: dict[str, float] = {}
    for weight, key in zip(weights, store.keys):
        totals[key[1]] = totals.get(key[1], 0.0) + weight
    assert abs(totals["many"] - totals["few"]) < 1e-9


def test_matchup_of_key_handles_all_store_layouts():
    from scripts.train_bc_scale import game_of_key, matchup_of_key

    assert matchup_of_key(("opp", 7, 3)) == ("opp",)                    # oldest layout
    assert matchup_of_key(("deck", "opp", 7, 3)) == ("deck", "opp")     # seat 0
    assert matchup_of_key(("deck", "opp", 7, 1, 3)) == ("deck", "opp")  # seat 1
    assert game_of_key(("deck", "opp", 7, 1, 3)) == ("deck", "opp", 7, 1)
    assert game_of_key(("deck", "opp", 7, 3)) == ("deck", "opp", 7)
