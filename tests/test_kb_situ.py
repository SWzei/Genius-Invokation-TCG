"""Situational rule questions (D32): answers follow the KB rule tables and the visible view."""

from __future__ import annotations

import json
import random

import pytest

from bench import kb_situ


def _view(*, dice=3, aura="无", opp_ended=False, summons=0):
    char = {"name": "甲", "active": True, "defeated": False, "aura": aura, "hp": 5}
    return {"me": {"dice": ["万能"] * dice, "summons": [{"name": f"s{i}"} for i in range(summons)],
                   "characters": [dict(char, name="我")], "declared_end": False},
            "opponent": {"characters": [char, dict(char, name="乙", active=False)], "summons": [],
                         "declared_end": opp_ended}}


@pytest.mark.parametrize("aura,element,expected", [
    ("冰", "火", "触发融化反应，本次伤害 +2"),
    ("水", "雷", "触发感电反应，本次伤害 +1"),
    ("雷", "风", "触发扩散反应，本次伤害 +0"),
    ("冰+草", "火", "触发融化反应，本次伤害 +2"),           # reacts with 冰 first, 草 stays
    ("冰", "草", "不发生反应，冰与草共存"),
    ("草", "岩", "不发生反应，草元素保留"),
    ("无", "风", "不发生反应，也不附着元素"),
    ("无", "水", "不发生反应，目标附着水元素"),
    ("火", "火", "不发生反应，附着不变"),
])
def test_reaction_outcomes_follow_the_attachment_table(aura, element, expected):
    assert kb_situ.reaction_outcome(aura, element) == expected


def test_every_table_cell_has_an_answer_with_three_distinct_distractors():
    rng = random.Random(3)
    for aura in ("无", "冰", "水", "火", "雷", "草", "冰+草"):
        for element in kb_situ.ELEMENTS:
            correct = kb_situ.reaction_outcome(aura, element)
            wrong = kb_situ._reaction_distractors(correct, rng)
            assert len(set(wrong) | {correct}) == 4


def test_answers_track_the_visible_position():
    rng = random.Random(1)
    by_type = lambda view: {q["qtype"]: q for q in kb_situ.questions_for(view, 0, rng)}
    q = by_type(_view(dice=4, opp_ended=True, summons=4, aura="冰"))
    assert q["charged"]["options"][q["charged"]["answer"]] == "是，视为重击"
    assert q["turn"]["options"][q["turn"]["answer"]] == "仍由我方继续行动"
    assert q["end"]["options"][q["end"]["answer"]].startswith("进入结束阶段")
    assert q["summon"]["options"][q["summon"]["answer"]] == "0 个"
    assert q["reaction"]["facts"]["aura"] == "冰" and q["reaction"]["facts"]["first"] is None
    q = by_type(_view(dice=5, opp_ended=False, summons=2))
    assert q["charged"]["options"][q["charged"]["answer"]] == "否，不视为重击"
    assert q["turn"]["options"][q["turn"]["answer"]] == "轮到对方行动"
    assert q["summon"]["options"][q["summon"]["answer"]] == "2 个"
    first = q["reaction"]["facts"]["first"]                     # nothing attached: a two-hit question
    expected = kb_situ.reaction_outcome(first, q["reaction"]["facts"]["element"])
    assert first and q["reaction"]["options"][q["reaction"]["answer"]] == expected


def test_refs_and_prompt_layout():
    assert kb_situ.refs_of("R06 §2 / §3.1") == ["R06 §2", "R06 §3.1"]
    assert kb_situ.refs_of("R03 §3 / R01 §4.3") == ["R03 §3", "R01 §4.3"]
    item = kb_situ.questions_for(_view(), 0, random.Random(0))[0]
    closed = kb_situ.build_messages(item, "局面文本", "")[1]["content"]
    with_kb = kb_situ.build_messages(item, "局面文本", "知识文本")[1]["content"]
    assert "【参考知识】" not in closed
    # state and knowledge come before the question, so items of one position share a prompt prefix
    assert with_kb.index("局面文本") < with_kb.index("知识文本") < with_kb.index("【题目】")


def test_summary_pools_runs_and_pairs(tmp_path, monkeypatch):
    monkeypatch.setenv("GITCG_DATA_DIR", str(tmp_path / "data"))
    bank = {"name": "t", "items": [{"id": f"c{i}:charged", "qtype": "charged", "split": "dev"} for i in range(4)]
            + [{"id": "c9:charged", "qtype": "charged", "split": "test"}]}
    path = tmp_path / "bank.json"
    path.write_text(json.dumps(bank), encoding="utf-8")
    truth = {"none": [[1, 0, 0, 0], [1, 0, 0, 1]], "kb": [[1, 1, 1, 1], [1, 1, 0, 1]]}
    for r, tag in enumerate(("r1", "r2")):
        d = tmp_path / "data" / "bench" / tag
        d.mkdir(parents=True)
        rows = [{"kb": kb, "id": f"c{i}:charged", "qtype": "charged", "ok": True, "correct": bool(v[r][i]),
                 "has_ref": kb == "kb"} for kb, v in truth.items() for i in range(4)]
        (d / "situ.jsonl").write_text("\n".join(json.dumps(x) for x in rows), encoding="utf-8")
    report = kb_situ.summarise(str(path), ["r1", "r2"], ["none", "kb"], "dev")
    none, kb = report["table"]
    assert (none["observations"], none["accuracy"], kb["accuracy"]) == (8, 0.375, 0.875)
    assert kb["ref_in_knowledge"] == {"charged": "8/8"} and none["ref_in_knowledge"] == {"charged": "0/8"}
    cmp = report["comparisons"][0]
    assert (cmp["a"], cmp["b"], cmp["better"], cmp["worse"]) == ("kb", "none", 3, 0)
    assert "情境" in kb_situ.render_markdown(report, "情境规则题")


def test_reason_mode_asks_for_a_justification_first():
    item = kb_situ.questions_for(_view(), 0, random.Random(0))[0]
    plain = kb_situ.build_messages(item, "局面", "")[0]["content"]
    reason = kb_situ.build_messages(item, "局面", "", mode="reason")[0]["content"]
    assert '"reason"' not in plain and reason.index('"reason"') < reason.index('"answer"')
