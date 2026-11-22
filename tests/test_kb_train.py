"""Knowledge-adapter optimisation (D32): retrieval, situation notes, unit pruning, splits,
the lenient / conversion lethal labels and the stage report."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from reps import kb_retrieval
from reps.knowledge import KnowledgeBase
from reps.knowledge_pack import KnowledgeProfile, KnowledgeSelector, load_custom, profile_from_mapping


def _kb(root):
    derived = root / "data" / "derived"
    derived.mkdir(parents=True)
    (root / "README.md").write_text("---\nversion: 9.9\n---\n", encoding="utf-8")
    rules = [
        {"ref": "R00 §1", "heading": "约定", "text": "本库的召唤物记号约定。", "evidence": ["官方"], "doc": "R00",
         "version_baseline": "v7.2.0"},
        {"ref": "R07 §1", "heading": "召唤物区", "text": "召唤物区最多 4 个召唤物；已满时无法生成新的召唤物。",
         "evidence": ["官方"], "doc": "R07", "version_baseline": "v7.2.0"},
        {"ref": "R01 §4.3", "heading": "结束阶段", "text": "结算结束阶段触发的效果（召唤物攻击、持续伤害、治疗等）。",
         "evidence": ["官方"], "doc": "R01", "version_baseline": "v7.2.0"},
        {"ref": "R02 §5", "heading": "元素调和", "text": "舍弃 1 张手牌，把 1 个元素骰转换为出战角色的元素类型。",
         "evidence": ["官方"], "doc": "R02", "version_baseline": "v7.2.0"},
    ]
    units = [{"id": u, "title": u, "condition": "c", "recommendation": "r", "conclusion": "x", "key_variables": "",
              "evidence_types": ["机制"], "confidence": "高", "limits": "", "doc": u[:3], "version_baseline": "通用"}
             for u in ("S04-P1", "S06-P1")]
    (derived / "rule_sections.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rules), encoding="utf-8")
    (derived / "strategy_units.jsonl").write_text("\n".join(json.dumps(u, ensure_ascii=False) for u in units), encoding="utf-8")
    return root


def _context(opp_hp=(3, 0, 0), defeated=(False, True, True)):
    chars = [SimpleNamespace(health=h, defeated=d) for h, d in zip(opp_hp, defeated)]
    me = SimpleNamespace(characters=[SimpleNamespace(health=8, defeated=False)])
    view = SimpleNamespace(players=[me, SimpleNamespace(characters=chars)], round_number=5)
    return SimpleNamespace(player_view=view, acting_player=0, legal_low_level_specs=[], request_type=None)


def test_bigram_bm25_ranks_chinese_and_excludes_documents(tmp_path):
    assert kb_retrieval.bigrams("召唤物区，max 4") == ["召唤", "唤物", "物区", "max"]
    kb = KnowledgeBase.load(_kb(tmp_path / "kb"))
    index = kb_retrieval.section_index(list(kb.rules.values()), exclude_docs=("R00",))
    assert index.rank("召唤物区满了还能召唤吗", 2)[0] == "R07 §1"
    assert "R00 §1" not in index.rank("召唤物 记号 约定", 5)
    assert index.rank("", 3) == []


def test_lethal_window_reads_the_visible_opponent_only():
    assert kb_retrieval.lethal_window(_context((3, 0, 0), (False, True, True)))
    assert not kb_retrieval.lethal_window(_context((6, 0, 0), (False, True, True)))
    assert not kb_retrieval.lethal_window(_context((3, 4, 0), (False, False, True)))
    assert not kb_retrieval.lethal_window(SimpleNamespace(player_view=None))


def test_rule_retrieval_mode_uses_the_decision_text(tmp_path, monkeypatch):
    kb = KnowledgeBase.load(_kb(tmp_path / "kb"))
    monkeypatch.setattr(kb_retrieval, "decision_query", lambda context, describer: "宣布回合结束 结束阶段 召唤物攻击")
    profile = profile_from_mapping("t", {"rules": True, "rule_selection": "retrieve", "max_rules": 1,
                                         "rule_evidence": ["官方"]})
    selector = KnowledgeSelector(profile, kb=kb)
    selector._describer = object()
    items = selector._rules(_context(), [])
    assert [i.id for i in items] == ["R01 §4.3"]
    with pytest.raises(ValueError):
        profile_from_mapping("t", {"rule_selection": "random"})
    assert "rule_selection" not in KnowledgeProfile(rules=True).as_dict()          # old manifests unchanged


def test_unit_frequency_table_prunes_uninformative_units(tmp_path, monkeypatch):
    import reps.knowledge_pack as kp

    kb = KnowledgeBase.load(_kb(tmp_path / "kb"))
    table = tmp_path / "freq.json"
    table.write_text(json.dumps({"frequency": {"S04-P1": 0.9, "S06-P1": 0.1}}), encoding="utf-8")
    monkeypatch.setattr(kp, "matching_units", lambda context: ("S04-P1", "S06-P1"))
    keep_all = KnowledgeSelector(KnowledgeProfile(strategy=True), kb=kb)
    pruned = KnowledgeSelector(KnowledgeProfile(strategy=True, unit_frequency_file=str(table),
                                                max_unit_frequency=0.5), kb=kb)
    assert [i.id for i in keep_all._strategy(_context())] == ["S04-P1", "S06-P1"]
    assert [i.id for i in pruned._strategy(_context())] == ["S06-P1"]


def test_situation_notes_appear_exactly_when_their_situation_holds(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("---\nkind: strategy\nversion: t\nwhen: lethal_window\n---\n# 斩杀窗口\n先算能否直接赢。\n", encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text("---\nkind: strategy\nwhen: full_moon\n---\n# x\ny\n", encoding="utf-8")
    chunks, warnings = load_custom([str(note), str(bad)])
    assert [c.when for c in chunks] == ["lethal_window"] and any("full_moon" in w for w in warnings)
    selector = KnowledgeSelector(KnowledgeProfile(custom=(str(note),)), kb=None)
    assert [i.title for i in selector._custom_items("", _context((3, 0, 0), (False, True, True)))] == ["斩杀窗口"]
    assert selector._custom_items("", _context((9, 0, 0), (False, True, True))) == []
    assert selector._custom_items("", None) == []


def test_kb_search_falls_back_to_bm25_for_chinese(tmp_path):
    kb = KnowledgeBase.load(_kb(tmp_path / "kb"))
    assert getattr(kb.search("召唤物区满了会怎样？", limit=1)[0], "ref", None) == "R07 §1"
    assert [getattr(x, "ref", None) for x in kb.search("R02", limit=1)] == ["R02 §5"]   # whitespace path unchanged


def test_scenario_split_is_fixed_and_roughly_40_30_30():
    from collections import Counter

    from bench.scenarios import SCENARIO_SEED_BASE, split_of

    labels = [split_of(SCENARIO_SEED_BASE + 1000 + i) for i in range(1000)]
    assert labels == [split_of(SCENARIO_SEED_BASE + 1000 + i) for i in range(1000)]
    share = {k: v / 1000 for k, v in Counter(labels).items()}
    assert abs(share["train"] - 0.4) < 0.05 and abs(share["dev"] - 0.3) < 0.05 and abs(share["test"] - 0.3) < 0.05


def test_stage_report_pools_runs_and_pairs_items(tmp_path, monkeypatch):
    from bench import kb_train

    monkeypatch.setenv("GITCG_DATA_DIR", str(tmp_path / "data"))
    scen = {"name": "t", "sources": [], "scenarios": [
        {"id": f"lethal-{i}", "kind": "lethal", "split": "dev"} for i in range(4)] + [
        {"id": "lethal-9", "kind": "lethal", "split": "test"}]}
    path = tmp_path / "set.json"
    path.write_text(json.dumps(scen), encoding="utf-8")
    truth = {"a": [[1, 0, 0, 1], [1, 0, 1, 1]], "b": [[1, 1, 1, 1], [1, 1, 1, 1]]}
    for r, tag in enumerate(("r1", "r2")):
        d = tmp_path / "data" / "bench" / tag
        d.mkdir(parents=True)
        rows = [{"subject": s, "kind": "lethal", "id": f"lethal-{i}", "converted": bool(v[r][i]), "calls": 1}
                for s, v in truth.items() for i in range(4)]
        rows.append({"subject": "a", "kind": "lethal", "id": "lethal-9", "converted": True})     # other split
        (d / "scenarios.jsonl").write_text("\n".join(json.dumps(x) for x in rows), encoding="utf-8")
    report = kb_train.stage_report(str(path), "dev", ["r1", "r2"], ["a", "b"])
    a, b = report["table"]
    assert (a["observations"], a["mean"], b["mean"]) == (8, 0.625, 1.0)
    assert a["per_run"]["r1"] == {"n": 4, "hits": 2, "rate": 0.5}
    cmp = report["comparisons"][0]
    assert (cmp["a"], cmp["b"], cmp["better_items"], cmp["worse_items"]) == ("b", "a", 2, 0)
    assert report["stability"]["a"] == {"items_with_2_runs": 4, "disagree": 1}


@pytest.mark.slow
def test_lenient_and_conversion_labels_on_a_real_scenario():
    """v1 lethal-0088: the opponent has declared end; declaring end wins in the end phase.
    Playing a free card first keeps the win; a policy that plays on converts it."""
    from bench.scenarios import converts_lethal, keeps_lethal, load_set
    from envs.policy import build_policy

    s = load_set("v1")
    sc = next(x for x in s["scenarios"] if x["id"] == "lethal-0088")
    src = s["sources"][sc["source"]]
    assert sc["winning"] == [1]
    assert keeps_lethal(src, sc, 1) and keeps_lethal(src, sc, 0)
    out = converts_lethal(src, sc, build_policy("heuristic", seed=1, role=f"p{sc['seat']}"))
    assert out["converted"] and out["ended_by"] == "win" and 1 <= out["steps"] <= 6


def test_situation_triggered_rules_come_first(tmp_path, monkeypatch):
    from reps.schema import OptionKind

    def ctx(*, ended=False, aura=0, summons=0, skill=True):
        opp_active = SimpleNamespace(health=5, defeated=False, is_active=True, aura=aura)
        me = SimpleNamespace(characters=[SimpleNamespace(health=8, defeated=False, is_active=True, aura=0)],
                             summons=[object()] * summons, declared_end=False)
        opp = SimpleNamespace(characters=[opp_active], summons=[], declared_end=ended)
        specs = [SimpleNamespace(kind=OptionKind.ACTION_USE_SKILL)] if skill else []
        return SimpleNamespace(player_view=SimpleNamespace(players=[me, opp], round_number=3), acting_player=0,
                               legal_low_level_specs=specs, request_type=None)

    assert kb_retrieval.triggered_rules(ctx(skill=False)) == []
    assert kb_retrieval.triggered_rules(ctx(ended=True, aura=1, summons=3)) == [
        "R03 §3", "R01 §4.3", "R06 §2", "R06 §3.1", "R07 §1", "R04 §3"]
    assert kb_retrieval.triggered_rules(SimpleNamespace(player_view=None)) == []
    kb = KnowledgeBase.load(_kb(tmp_path / "kb"))
    monkeypatch.setattr(kb_retrieval, "decision_query", lambda context, describer: "元素调和 骰子")
    profile = profile_from_mapping("t", {"rules": True, "rule_selection": "retrieve", "rule_triggers": True,
                                         "max_rules": 2, "rule_evidence": ["官方"]})
    selector = KnowledgeSelector(profile, kb=kb)
    selector._describer = object()
    # the fixture KB has R01 §4.3 and R07 §1 of the triggered sections; retrieval fills nothing more
    assert [i.id for i in selector._rules(ctx(ended=True, summons=3), [])] == ["R01 §4.3", "R07 §1"]
    assert [i.id for i in selector._rules(ctx(), [])] == ["R02 §5"]
    assert "rule_triggers" not in KnowledgeProfile(rules=True).as_dict()


def test_games_report_pools_runs_per_configuration_and_pairs_cells(tmp_path, monkeypatch):
    from bench import kb_train

    monkeypatch.setenv("GITCG_DATA_DIR", str(tmp_path / "data"))
    def write(tag, rows):
        d = tmp_path / "data" / "bench" / tag
        d.mkdir(parents=True)
        (d / "games.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    row = lambda subject, cell, score, **kw: {"subject": subject, "cell": cell, "score": score, "error": None,
                                              "degraded": False, "llm": {"calls": 2, "asked": 2, "first_reply_legal": 2,
                                                                         "usage": {"cost": 0.01}}, **kw}
    write("r1", [row("x", "c1", 1.0), row("x", "c2", 0.0), row("y", "c1", 1.0), row("y", "c2", 1.0),
                 row("x", "c3", None, error="boom")])
    write("r2", [row("x", "c1", 0.0), row("x", "c2", 0.0)])
    report = kb_train.games_report(["base=r1:x;r2:x", "new=r1:y"])
    base, new = report["arms"]
    assert (base["games"], base["invalid"], base["score"]) == (4, 1, 0.25)
    assert base["per_run"] == {"r1": {"games": 2, "score": 0.5}, "r2": {"games": 2, "score": 0.0}}
    cmp = report["comparisons"][0]
    assert (cmp["a"], cmp["b"], cmp["cells"], cmp["better_cells"], cmp["worse_cells"]) == ("new", "base", 2, 2, 0)
    assert cmp["delta"] == 0.75                      # c1: 1 - 0.5, c2: 1 - 0
    with pytest.raises(ValueError):
        kb_train.games_report(["no-equals"])


def _fake_source_game(task):
    import os

    calls = os.environ["KBT_FAKE_CALLS"]
    with open(calls, "a", encoding="utf-8") as fh:
        fh.write(f"{task['seed']}\n")
    if os.environ.get("KBT_FAKE_FAIL_FROM") and task["seed"] >= int(os.environ["KBT_FAKE_FAIL_FROM"]):
        raise RuntimeError("stopped")
    return {"source": {"seed": task["seed"], "trace": []}, "scenarios": [{"kind": "lethal", "winning": [0], "n_options": 2,
                                                                          "generator_index": 0}], "error": None}


def test_scenario_build_resumes_from_its_per_game_cache(tmp_path, monkeypatch):
    from bench import scenarios

    monkeypatch.setenv("GITCG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KBT_FAKE_CALLS", str(tmp_path / "calls.txt"))
    monkeypatch.setattr(scenarios, "SET_DIR", tmp_path / "sets")
    monkeypatch.setattr(scenarios, "_source_game", _fake_source_game)
    first_seed = scenarios.SCENARIO_SEED_BASE + 50
    monkeypatch.setenv("KBT_FAKE_FAIL_FROM", str(first_seed + 2))
    with pytest.raises(RuntimeError):
        scenarios.build_set("t", games=4, workers=1, decks=["a", "b"], seed_offset=50)
    monkeypatch.delenv("KBT_FAKE_FAIL_FROM")
    out = scenarios.build_set("t", games=4, workers=1, decks=["a", "b"], seed_offset=50)
    calls = [int(x) for x in (tmp_path / "calls.txt").read_text().split()]
    assert calls.count(first_seed) == 1 and calls.count(first_seed + 1) == 1     # done games are not replayed
    assert out["source_games"] == 4 and out["counts"] == {"lethal": 4}
    assert sum(v["sources"] for v in out["splits"].values()) == 4
