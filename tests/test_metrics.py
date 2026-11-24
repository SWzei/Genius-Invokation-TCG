"""Outcome metrics for mirror pairs and the noisy calibration policy (D37). Fast, offline."""

from __future__ import annotations

import math
import random
from types import SimpleNamespace as NS

from bench import metrics
from envs.policy import NoisyPolicy, build_policy


def _row(side, score, *, hp=(5, 0), max_hp=(30, 30), defeated=(1, 3), taken=(25, 40), rep=0, cell=None, **extra):
    return {"subject": "s", "cell": cell or f"c{rep}-{side}", "group": "mirror-train", "rep": rep, "side": side,
            "score": score, "error": None, "outcome": {"alive": [3 - defeated[0], 3 - defeated[1]], "hp": list(hp),
                                                       "max_hp": list(max_hp), "defeated": list(defeated),
                                                       "damage_taken": list(taken)}, **extra}


def test_game_metrics_follow_their_definitions():
    m = metrics.game_metrics(_row(0, 1.0))                      # seat 0 won with 5/30 HP left
    assert m["W"] == 1.0 and math.isclose(m["H"], 5 / 30) and math.isclose(m["K"], 2 / 3)
    assert math.isclose(m["D"], 40 / 65 - 0.5)
    m1 = metrics.game_metrics(_row(1, 0.0))                     # same game seen from seat 1
    assert all(math.isclose(m1[k], -m[k]) for k in ("H", "K", "D")) and m1["W"] == 0.0
    assert metrics.game_metrics({**_row(0, 1.0), "outcome": None}) is None


def test_pair_values_are_antisymmetric_and_break_seat_ties():
    # the same seat wins both games (a W tie), but the subject won by more
    rows = [_row(0, 1.0, hp=(20, 0), rep=0), _row(1, 0.0, hp=(8, 0), rep=0)]
    pairs, dropped = metrics.pairs_from_rows(rows)
    assert dropped == 0 and pairs[0]["W"] == 0.0 and pairs[0]["H"] > 0
    swapped = [_row(1, 0.0, hp=(20, 0), rep=0), _row(0, 1.0, hp=(8, 0), rep=0)]   # roles exchanged
    other, _ = metrics.pairs_from_rows(swapped)
    assert all(math.isclose(other[0][k], -pairs[0][k], abs_tol=1e-12) for k in metrics.METRICS)


def test_broken_games_drop_the_whole_pair_for_both_sides():
    rows = [_row(0, 1.0, rep=0), {**_row(1, 0.0, rep=0), "error": "x"}, _row(0, 1.0, rep=1), _row(1, 1.0, rep=1)]
    pairs, dropped = metrics.pairs_from_rows(rows)
    assert dropped == 1 and [p["rep"] for p in pairs] == [1]
    rows = [_row(0, 1.0, rep=0), {**_row(1, 0.0, rep=0), "rival_degraded": True}]
    assert metrics.pairs_from_rows(rows) == ([], 1)


def test_stats_sign_test_and_power():
    s = metrics.stats([0.5] * 12 + [-0.5] * 4 + [0.0] * 4)
    assert (s["better"], s["worse"], s["even"], s["pair_rate"]) == (12, 4, 4, 0.7)
    assert math.isclose(s["p_one"], sum(math.comb(16, j) for j in range(12, 17)) / 2 ** 16, rel_tol=1e-3)
    assert metrics.n80(s) < metrics.n80(metrics.stats([0.5] * 9 + [-0.5] * 7 + [0.0] * 4))
    assert metrics.n80(metrics.stats([-1.0] * 5)) == math.inf
    rng = random.Random(0)
    null = [rng.choice((-1.0, 1.0)) for _ in range(200)]
    assert metrics.null_rejection(null, draws=400) < 0.1
    assert metrics.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0


def test_noisy_policy_is_a_seeded_handicap():
    codes = list(range(100, 110))
    built = NS(context=NS(legal_low_level_codes=codes))
    base = NS(choose=lambda b: 100)
    never = NoisyPolicy(base, 0.0, seed=1)
    assert all(never.choose(built) == 100 for _ in range(50))
    a, b = NoisyPolicy(base, 0.5, seed=3), NoisyPolicy(base, 0.5, seed=3)
    seq = [a.choose(built) for _ in range(200)]
    assert seq == [b.choose(built) for _ in range(200)] and 50 < sum(c != 100 for c in seq) < 150
    policy = build_policy("noisy:0.3:heuristic", seed=7, role="p0")
    assert isinstance(policy, NoisyPolicy) and policy.epsilon == 0.3
    # same seat and seed: unsalted specs share a stream, salted ones do not (a real A/A)
    salted = [build_policy(f"noisy:0.3@{s}:heuristic", seed=7, role="p0") for s in "ab"]
    assert salted[0].epsilon == 0.3
    draws = [[p._rng.random() for _ in range(5)] for p in (policy, build_policy("noisy:0.3:heuristic", seed=7, role="p0"))]
    assert draws[0] == draws[1]
    assert [salted[0]._rng.random() for _ in range(5)] != [salted[1]._rng.random() for _ in range(5)]


def test_tiebreak_puts_wins_first_and_orders_the_factors():
    won = {"W": 0.5, "K": -1.0, "H": -0.5, "D": -0.2}               # won on games: factors ignored
    tie_k = {"W": 0.0, "K": 1 / 3, "H": -0.2, "D": -0.1}            # K decides before H and D
    tie_h = {"W": 0.0, "K": 0.0, "H": -0.2, "D": 0.1}               # K level: H decides
    flat = {"W": 0.0, "K": 0.0, "H": 0.0, "D": 0.0}
    assert metrics.pair_outcome(won, "order") == 1.0 and metrics.pair_outcome(won, "loss") == 1.0
    assert [metrics.pair_outcome(p, "order") for p in (tie_k, tie_h, flat)] == [1.0, 0.0, 0.5]
    assert metrics.pair_outcome(tie_h, "any_for") == 1.0 and metrics.pair_outcome(tie_k, "any_against") == 0.0
    assert (metrics.pair_outcome(tie_k, "loss"), metrics.pair_outcome(tie_k, "win"), metrics.pair_outcome(tie_k, "none")) \
        == (0.0, 1.0, 0.5)
    r = metrics.tiebreak([won, tie_k, tie_h, flat])
    rates = {k: v["rate"] for k, v in r["rules"].items()}
    assert r["w_ties"] == 3 and rates["loss"] == 0.25 and rates["win"] == 1.0 and rates["order"] == 0.625
    assert rates["loss"] <= rates["any_against"] <= rates["order"] <= rates["any_for"] <= rates["win"]
    # swapping the sides mirrors every rule (fairness)
    neg = [{k: -v for k, v in p.items()} for p in (won, tie_k, tie_h, flat)]
    mirrored = metrics.tiebreak(neg)["rules"]
    assert math.isclose(mirrored["order"]["rate"], 1 - rates["order"])
    assert math.isclose(mirrored["any_for"]["rate"], 1 - rates["any_against"])
