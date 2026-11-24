"""Replay / fork of traced games, divergence points and pattern mining (D35). Fast, offline."""

from __future__ import annotations

import json
import random
from types import SimpleNamespace as NS

import pytest

from bench import divergence, forks, mirror_mine


def _trace(index, n, request="action", source="llm"):
    return {"final_index": index, "n_options": n, "request_type": request, "source": source,
            "final_text": f"opt{index}", "reason": "r", "knowledge": {"items": [{"id": "R01 §4.2"}]}}


def test_game_source_puts_each_trace_on_its_seat():
    payload = {"cell": {"side": 1, "deck": "human:A", "opponent_deck": "human:B", "seed": 7, "version": "v6.3.0",
                        "rep": 3, "group": "mirror-train"},
               "subject_traces": [_trace(0, 2)], "rival_traces": [_trace(1, 3), _trace(0, 2)],
               "winner": 1, "rounds": 5, "subject": "s"}
    src = forks.game_source(payload, {"human:A": {}, "human:B": {}})
    assert (src["deck0"], src["deck1"], src["subject_seat"], src["pair"]) == ("human:B", "human:A", 1, 3)
    assert [d["role"] for d in src["seats"][1]] == ["subject"] and len(src["seats"][0]) == 2
    assert src["seats"][0][0] == {"index": 1, "n": 3, "request": "action", "source": "llm", "final_text": "opt1",
                                  "reason": "r", "knowledge": ["R01 §4.2"], "role": "rival"}


def test_seat_replays_then_forks_then_hands_over():
    from agents.human import HumanQuit

    shared = forks._Shared()
    built = lambda n: NS(context=NS(legal_low_level_codes=list(range(100, 100 + n))))   # noqa: E731
    cont = NS(choose=lambda b: 999)
    me = forks._Seat(0, [{"index": 1, "n": 3}, {"index": 0, "n": 2}], shared, fork_at=1, choice=1, continuation=cont)
    other = forks._Seat(1, [{"index": 0, "n": 2}], shared, continuation=cont)
    assert me.choose(built(3)) == 101                      # replayed
    assert other.choose(built(2)) == 100                   # replayed
    assert me.choose(built(2)) == 101 and shared.forked    # the fork: choice 1, not the recorded 0
    assert other.choose(built(5)) == 999 and me.choose(built(4)) == 999   # both seats continue after the fork
    bad = forks._Seat(0, [{"index": 0, "n": 4}], forks._Shared())
    with pytest.raises(HumanQuit):
        bad.choose(built(3))                               # option count changed: replay mismatch
    assert "recorded 4 options" in bad.mismatch


def test_sample_ordinals_skip_forced_and_spread_over_the_game():
    decisions = [{"source": "forced" if i % 5 == 0 else "llm", "n": 1 if i % 7 == 0 else 3} for i in range(60)]
    picks = divergence.sample_ordinals(decisions, 8, random.Random(1))
    assert len(picks) == 8 and picks == sorted(picks)
    assert all(decisions[i]["source"] != "forced" and decisions[i]["n"] >= 2 for i in picks)
    assert picks == divergence.sample_ordinals(decisions, 8, random.Random(1))
    assert picks[0] < 15 and picks[-1] > 45                # one pick per slice
    few = [{"source": "llm", "n": 2}] * 3
    assert divergence.sample_ordinals(few, 8, random.Random(0)) == [0, 1, 2]


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def test_divergence_points_and_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("GITCG_DATA_DIR", str(tmp_path))
    run = tmp_path / "bench" / "t"
    pos = []
    for k in range(6):
        base = {"game": "g", "seat": 0, "ordinal": k, "path": "p", "request": "action" if k < 4 else "reroll_dice",
                "actor": "subject", "text": "x", "knowledge": []}
        pos.append({**base, "policy": "a", "index": 1 if k % 2 else 0, "source": "llm"})
        pos.append({**base, "policy": "b", "index": 0, "source": "fallback" if k == 5 else "llm"})
    _write(run / "positions.jsonl", pos)
    dps = divergence.divergence_points("t", "a", "b")
    assert [d["ordinal"] for d in dps] == [1, 3]            # k = 5 differs but b fell back: not a DP
    rolls = []
    for d, (sa, sb) in zip(dps, ((1.0, 0.0), (0.0, 0.0))):
        for cont, scores in (("heuristic", (sa, sb)), ("llm", (sa, 1.0 - sb))):
            rolls += [{"dp": d["dp"], "branch": "a", "rep": 0, "continuation": cont, "score": scores[0], "cost": 0.01},
                      {"dp": d["dp"], "branch": "b", "rep": 0, "continuation": cont, "score": scores[1], "cost": 0.01}]
    rolls.append({"dp": dps[0]["dp"], "branch": "a", "rep": 1, "continuation": "llm", "score": 0.0, "cost": 0.01})
    _write(run / "rollouts.jsonl", rolls)
    _write(run / "calls.jsonl", [{"cost": 0.002}] * 3)
    report = divergence.summarise("t", ["a:b"])
    c = report["comparisons"][0]
    assert (c["positions"], c["dps"], c["disagreement"]) == (5, 2, 0.4)
    h, m = c["by_continuation"]["heuristic"], c["by_continuation"]["llm"]
    assert (h["n"], h["decisive"], h["mean"]) == (2, 1, 0.5)
    assert m["repeat_branch_differs"] == 1.0 and m["repeat_branches"] == 1
    assert c["agreement"]["both_decisive"] == 1 and c["agreement"]["same_sign"] == 0
    assert report["model_calls_total"] == 3 and "分歧点" in divergence.render_markdown(report)


def test_divergence_refuses_dev_and_test_games(tmp_path):
    path = tmp_path / "g.json"
    path.write_text(json.dumps({"cell": {"group": "mirror-dev"}}), encoding="utf-8")
    with pytest.raises(SystemExit, match="train games only"):
        divergence._source(path)


def _ctx(chosen_kind, *, dice=4, opp_ended=False, hp=10, hand=5, kinds=("action_use_skill", "action_declare_end"),
         burst=False, draw_text=""):
    char = NS(is_active=True, defeated=False, health=hp)
    me = NS(dice=(1,) * dice, characters=(char, NS(is_active=False, defeated=False, health=10)), hand_cards=(None,) * hand)
    opp = NS(declared_end=opp_ended)
    specs = [NS(kind=NS(value=k), subject_definition_id=1) for k in kinds]
    if burst:
        specs.append(NS(kind=NS(value="action_use_skill"), subject_definition_id=9))
    specs.append(NS(kind=NS(value=chosen_kind), subject_definition_id=2))
    ctx = NS(request_type=NS(value="action"), legal_low_level_specs=specs, player_view=NS(players=(me, opp)),
             acting_player=0)
    assets = NS(get=lambda i: NS(kind="元素爆发" if i == 9 else "技能", description=draw_text if i == 2 else ""))
    return ctx, len(specs) - 1, assets


def test_mining_flags_follow_their_definitions():
    flag = lambda *a, **k: mirror_mine.flags(*_ctx(*a, **k))   # noqa: E731
    assert flag("action_declare_end") == ["end_with_dice"]
    assert flag("action_declare_end", dice=2) == []
    assert flag("action_declare_end", opp_ended=True, dice=2) == ["end_after_opp"]
    assert "low_hp_end" in flag("action_declare_end", hp=3, kinds=("action_switch_active",))
    assert flag("action_play_card", burst=True) == ["burst_skipped"]
    assert flag("action_play_card", hand=9, draw_text="抓2张牌") == ["draw_at_full_hand"]
    assert flag("action_play_card", hand=8, draw_text="抓2张牌") == []
    assert flag("action_elemental_tuning", opp_ended=True) == ["tune_after_opp"]


def test_state_text_names_elements_only_when_asked():
    from reps.describe import AssetEntry, AssetText, DecisionDescriber

    assets = AssetText({1: AssetEntry(1, "甘雨", "角色", element="冰")})
    side = {"characters": [{"name": "甘雨", "element": "冰", "active": True, "defeated": False, "hp": 10, "max_hp": 10,
                            "energy": 0, "max_energy": 3, "aura": "无", "entities": []}],
            "combat_statuses": [], "summons": [], "supports": [], "dice": [], "hand": [], "pile_count": 0,
            "declared_end": False, "legend_used": False}
    plain = DecisionDescriber(assets)._side_text(side, "我方", own=True, detail=False)[1]
    shown = DecisionDescriber(assets, elements=True)._side_text(side, "我方", own=True, detail=False)[1]
    assert "［冰］" not in plain and "甘雨［冰］（出战）" in shown
    payload = {"data": [{"id": 1, "name": "甘雨", "hp": 10, "skills": [], "tags": ["GCG_TAG_ELEMENT_CRYO"]}]}
    assert AssetText.from_payload(payload).get(1).element == "冰"


def _mull_trace(step, text, prompt=""):
    return {"step_index": str(step), "request_type": "switch_hands", "final_text": text, "reason": "r", "prompt": prompt}


def test_natural_divergence_is_the_first_differing_choice():
    def game(side, seat0_choice):
        subj, riv = [_mull_trace(1, seat0_choice if side == 0 else "替换 B")], [_mull_trace(1, "替换 B" if side == 0 else seat0_choice)]
        subj.append({**_mull_trace(5, "x"), "request_type": "action"})
        return {"cell": {"side": side, "group": "mirror-train", "seed": 1}, "subject_traces": subj, "rival_traces": riv}
    seq = mirror_mine.seat_sequence(game(1, "替换 A"))
    assert [(s, seat, role) for s, seat, role, _ in seq] == [(1, 0, "plain"), (1, 1, "knowledge"), (5, 1, "knowledge")]
    same_start = mirror_mine.first_divergence(game(0, "替换 A"), game(1, "替换 A"))
    assert (same_start["ordinal"], same_start["request"]) == (2, "action")   # mulligans equal; seats then differ
    dp = mirror_mine.first_divergence(game(0, "替换 A"), game(1, "替换 C"))
    assert (dp["ordinal"], dp["seat"], dp["request"]) == (0, 0, "switch_hands")
    assert (dp["a"]["role"], dp["b"]["role"]) == ("knowledge", "plain")


def test_mulligan_counts_signature_and_arcane_cards():
    prompt = ("手牌（4）：\n    1. 万家灶火（事件，费用 1秘传）：……\n    2. 神性之陨（装备，费用 3岩）：（牌组中包含阿贝多，才能加入牌组）\n"
              "    3. 神性之陨（装备，费用 3岩）：（牌组中包含阿贝多，才能加入牌组）\n    4. 原木刀（装备，费用 3任意）：……\n  牌库 25 张")
    cards = mirror_mine.hand_cards(prompt)
    assert [(c["name"], c["signature"], c["arcane"]) for c in cards] == [
        ("万家灶火", False, True), ("神性之陨", True, False), ("神性之陨", True, False), ("原木刀", False, False)]
    assert mirror_mine.swapped("替换 神性之陨、原木刀") == ["神性之陨", "原木刀"] and mirror_mine.swapped("不替换") == []
    stat = {}
    mirror_mine._mull_add(stat, cards, ["神性之陨", "原木刀"])     # one of two copies swapped
    mirror_mine._mull_add(stat, cards, ["原木刀"])
    assert (stat["n"], stat["core_hands"], stat["core_swapped"]) == (2, 2, 1)
    assert (stat["signature_cards"], stat["signature_swapped"], stat["arcane_swapped"], stat["cards"]) == (4, 1, 0, 3)
