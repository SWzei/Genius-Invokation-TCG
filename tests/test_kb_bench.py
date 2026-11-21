"""Knowledge-base benchmark tools: QA bank, retrievers, scoring, full strategy rendering, probe.

All offline: a small fixture KB, the built-in ``mock`` model profile, and (for the
shipped bank) the real KB only when ``GITCG_KB_DIR`` is set.
"""

from __future__ import annotations

import json
import os

import pytest

from bench import kb_qa
from reps.knowledge import KnowledgeBase


def _kb(root):
    derived = root / "data" / "derived"
    derived.mkdir(parents=True)
    (root / "README.md").write_text("---\nversion: 9.9\n---\n", encoding="utf-8")
    rules = [
        {"ref": "R07 §1", "heading": "区域与上限", "text": "召唤物区最多 4 个；已满时无法生成新的召唤物。支援区最多 4 张。",
         "evidence": ["官方"], "doc": "R07", "version_baseline": "v7.2.0"},
        {"ref": "R02 §5", "heading": "元素调和", "text": "快速行动：舍弃 1 张手牌，把 1 个元素骰转换为出战角色的元素类型。",
         "evidence": ["官方"], "doc": "R02", "version_baseline": "v7.2.0"},
        {"ref": "R01 §5", "heading": "抓牌与牌堆", "text": "手牌上限 10 张；牌堆为空时抓牌不会获得手牌。",
         "evidence": ["官方"], "doc": "R01", "version_baseline": "v7.2.0"},
    ]
    units = [
        {"id": "S04-P1", "title": "切人要换来具体收益", "condition": "考虑切人", "recommendation": "只为具体收益切人",
         "conclusion": "一次切人约等于 1 骰 + 1 个行动轮；只为躲击倒、换到能击倒的角色等具体收益而切。",
         "key_variables": "生存、切入角色价值", "evidence_types": ["机制"], "confidence": "高", "limits": "快速切换除外",
         "doc": "S04", "version_baseline": "通用"},
    ]
    (derived / "rule_sections.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rules), encoding="utf-8")
    (derived / "strategy_units.jsonl").write_text("\n".join(json.dumps(u, ensure_ascii=False) for u in units), encoding="utf-8")
    return root


def _bank():
    return {"name": "t", "items": [
        {"id": "a", "ref": "R07 §1", "question": "召唤物区已满时再生成召唤物会怎样？",
         "options": {"A": "替换最早的", "B": "无法生成", "C": "由牌手选择", "D": "叠加"}, "answer": "B",
         "evidence": "已满时无法生成新的召唤物"},
        {"id": "b", "ref": "R01 §5", "question": "手牌上限是多少？",
         "options": {"A": "7", "B": "8", "C": "10", "D": "无上限"}, "answer": "C", "evidence": "手牌上限 10 张"},
    ]}


def test_bank_validation_checks_evidence_options_and_ids(tmp_path):
    kb = KnowledgeBase.load(_kb(tmp_path / "kb"))
    bank = _bank()
    assert kb_qa.validate(bank, kb) == []
    broken = json.loads(json.dumps(bank))
    broken["items"][0]["evidence"] = "这句话不在原文里"
    broken["items"][1]["answer"] = "E"
    broken["items"].append(dict(broken["items"][1], ref="R99 §9"))
    problems = kb_qa.validate(broken, kb)
    assert any("a: evidence not found" in p for p in problems)
    assert any("b: options must be" in p for p in problems)
    assert any("duplicate id" in p for p in problems) and any("unknown section" in p for p in problems)


def test_bm25_finds_sections_for_chinese_questions_where_builtin_search_cannot(tmp_path):
    kb = KnowledgeBase.load(_kb(tmp_path / "kb"))
    bm25 = kb_qa.BM25(list(kb.rules.values()))
    assert bm25.rank("召唤物区已满时再生成召唤物会怎样？", 1) == ["R07 §1"]
    assert bm25.rank("元素调和把骰子变成什么？", 1) == ["R02 §5"]
    assert bm25.rank("", 3) == []
    # the KB's own search splits on whitespace: a natural Chinese question is one term
    assert kb.search("召唤物区已满时再生成召唤物会怎样？") == []
    table = kb_qa.retrieval_table(_bank(), kb, ks=(1, 3))
    assert table["bm25"]["hit@1"] == 1.0 and table["search"]["empty"] == 2


def test_retrieve_conditions_and_prompt_contents(tmp_path):
    kb = KnowledgeBase.load(_kb(tmp_path / "kb"))
    item = _bank()["items"][0]
    bm25 = kb_qa.BM25(list(kb.rules.values()))
    assert kb_qa.retrieve("closed", item, kb, bm25) == []
    assert kb_qa.retrieve("oracle", item, kb, bm25) == ["R07 §1"]
    assert kb_qa.retrieve("bm25", item, kb, bm25)[0] == "R07 §1"
    with pytest.raises(ValueError):
        kb_qa.retrieve("web", item, kb, bm25)
    closed = kb_qa.build_messages(item, [], kb)[1]["content"]
    oracle = kb_qa.build_messages(item, ["R07 §1"], kb)[1]["content"]
    assert "【资料】" not in closed and "B. 无法生成" in closed
    assert oracle.index("【资料】") < oracle.index("【题目】") and "已满时无法生成新的召唤物" in oracle


def test_answer_parsing():
    assert kb_qa.parse_answer('{"answer": "c"}') == "C"
    assert kb_qa.parse_answer("答案是 B。") == "B"
    assert kb_qa.parse_answer('{"choice": 0}') is None
    assert kb_qa.parse_answer("") is None and kb_qa.parse_answer(None) is None


def test_summary_pairs_conditions_against_closed_book():
    bank = {"name": "t", "items": [{"id": f"q{i}", "ref": "R01 §5"} for i in range(4)]}
    rows = []
    for i in range(4):
        rows.append({"profile": "m", "condition": "closed", "id": f"q{i}", "correct": i == 0, "gold_retrieved": False,
                     "ok": True, "answer": "A", "gold": "A", "prompt_tokens": 10, "completion_tokens": 1,
                     "latency_seconds": 0.1})
        rows.append({"profile": "m", "condition": "oracle", "id": f"q{i}", "correct": i != 3, "gold_retrieved": True,
                     "ok": True, "answer": "A", "gold": "A", "prompt_tokens": 20, "completion_tokens": 1,
                     "latency_seconds": 0.1})
    report = kb_qa.summarise(rows, bank)
    closed, oracle = report["table"]
    assert (closed["condition"], closed["correct"], oracle["correct"]) == ("closed", 1, 3)
    pair = report["paired"][0]
    assert (pair["condition"], pair["gained"], pair["lost"]) == ("oracle", 2, 0) and pair["p_mcnemar"] == 0.5
    assert report["oracle_misses"]["m"] == [{"id": "q3", "answer": "A", "gold": "A"}]


def test_eval_end_to_end_with_offline_model_resumes(tmp_path, monkeypatch):
    root = _kb(tmp_path / "kb")
    monkeypatch.setenv("GITCG_KB_DIR", str(root))
    monkeypatch.setenv("GITCG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GITCG_REPORTS_DIR", str(tmp_path / "reports"))
    bank_path = tmp_path / "bank.json"
    bank_path.write_text(json.dumps(_bank(), ensure_ascii=False), encoding="utf-8")
    report = kb_qa.evaluate(str(bank_path), ["mock:first"], tag="t", conditions=("closed", "oracle"), workers=2)
    rows = (tmp_path / "data" / "bench" / "t" / "kb_qa.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 4
    assert all(e["n"] == 2 and e["unparsed"] == 2 for e in report["table"])      # the mock answers {"choice": 0}
    assert (tmp_path / "reports" / "bench" / "t.md").exists()
    kb_qa.evaluate(str(bank_path), ["mock:first"], tag="t", conditions=("closed", "oracle"))
    rows_again = (tmp_path / "data" / "bench" / "t" / "kb_qa.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows_again) == 4          # resuming skips calls that already succeeded (even if unparsed)


def test_full_strategy_rendering_uses_the_unit_substance(tmp_path):
    from reps.knowledge_pack import KnowledgeProfile, KnowledgeSelector, profile_from_mapping

    kb = KnowledgeBase.load(_kb(tmp_path / "kb"))
    selector = KnowledgeSelector(KnowledgeProfile(strategy=True, strategy_detail="full", strategy_chars=600), kb=kb)
    detail = selector._detail("S04-P1")
    assert detail["conclusion"].startswith("一次切人")
    assert selector._detail("S99-P9") == {}
    with pytest.raises(ValueError):
        profile_from_mapping("x", {"strategy_detail": "verbose"})
    brief = KnowledgeProfile(strategy=True)
    assert "strategy_detail" not in brief.as_dict()                   # unchanged manifests for old profiles
    assert KnowledgeProfile(strategy=True, strategy_detail="full").as_dict()["strategy_detail"] == "full"


@pytest.mark.skipif(not os.environ.get("GITCG_KB_DIR"), reason="GITCG_KB_DIR not set")
def test_shipped_bank_is_valid_against_the_real_kb():
    bank = kb_qa.load_bank("rules_v1")
    assert len(bank["items"]) == 56
    assert kb_qa.validate(bank, KnowledgeBase.load()) == []
    assert sorted({i["answer"] for i in bank["items"]}) == ["A", "B", "C", "D"]


def test_probe_summary_counts_reach_per_profile():
    from bench.kb_probe import summarise

    class _KB:
        version, rules, units = "1.0", {"R03 §1": 1, "R02 §5": 2}, {"S04-P1": 1, "S01-P7": 2, "S99-P1": 3}

    games = [{"decisions": [
        {"request": "action", "packs": {"p": {"rules": ["R03 §1"], "strategy": ["S04-P1"], "chars": 100, "warnings": 0}}},
        {"request": "action", "packs": {"p": {"rules": ["R03 §1"], "strategy": [], "chars": 60, "warnings": 1}}},
        {"request": "reroll_dice", "packs": {"p": {"rules": ["R02 §5"], "strategy": [], "chars": 40, "warnings": 0}}},
    ], "warning_samples": {"p": ["rule R03 §1: written for v6.0.0"]}}]
    out = summarise(games, ["p"], _KB())
    p = out["profiles"]["p"]
    assert out["decisions"] == 3 and out["by_request"] == {"action": 2, "reroll_dice": 1}
    assert (p["decisions_with_rules"], p["decisions_with_strategy"], p["decisions_with_version_warning"]) == (3, 1, 1)
    assert p["distinct_rule_sections"] == 2 and p["distinct_units"] == 1 and p["chars_max"] == 100
    assert out["kb"]["units_with_detector"] == 2                       # S04-P1 and S01-P7 have detectors
    assert out["warning_samples"]["p"] == ["rule R03 §1: written for v6.0.0"]
