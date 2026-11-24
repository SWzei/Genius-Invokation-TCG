"""KB versions and model-vs-model pairs (D34)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from bench import mirror
from bench.suite import Cell
from reps import kb_versions

KB = os.environ.get("GITCG_KB_DIR", "")
HAVE_KB = bool(KB) and (Path(KB) / "tools" / "build_index.py").exists() and bool(os.environ.get("GITCG_DATA_RELEASE"))


def _version(root: Path, name: str, layer: str, parent: str, paths: list[str]) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "version.toml").write_text(f'parent = "{parent}"\nlayer = "{layer}"\n', encoding="utf-8")
    body = "".join(f"--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-x\n+y\n" for p in paths)
    (d / "changes.patch").write_text(body, encoding="utf-8")


def test_chain_and_layer_discipline(tmp_path, monkeypatch):
    monkeypatch.setattr(kb_versions, "VERSIONS_DIR", tmp_path)
    _version(tmp_path, "v1.1", "rules", "v1.0", ["rules/R03_actions.md"])
    _version(tmp_path, "v1.1-s1", "strategy", "v1.1", ["strategy/S02_tempo_and_initiative.md"])
    _version(tmp_path, "v1.2", "rules", "v1.1", ["strategy/S01_resource_economy.md"])
    assert kb_versions.chain("v1.1-s1") == ["v1.1", "v1.1-s1"]
    assert kb_versions.check_layer("v1.1") == ["rules/R03_actions.md"]
    with pytest.raises(ValueError, match="touches"):
        kb_versions.check_layer("v1.2")                   # a rules version may not edit strategy/
    with pytest.raises(ValueError):
        kb_versions.chain("nonsense")


def test_unbuilt_version_never_silently_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("GITCG_DATA_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="not built"):
        kb_versions.resolve("v1.1")
    from reps.knowledge_pack import KnowledgeSelector, profile_from_mapping

    profile = profile_from_mapping("p", {"rules": True, "kb_version": "v1.1"})
    with pytest.raises(RuntimeError, match="not built"):
        KnowledgeSelector(profile)


@pytest.mark.skipif(not HAVE_KB, reason="needs GITCG_KB_DIR (KB v1.0) and GITCG_DATA_RELEASE")
def test_v11_builds_cards_into_the_injected_prefix(tmp_path, monkeypatch):
    monkeypatch.setenv("GITCG_DATA_DIR", str(tmp_path))
    manifest = kb_versions.build("v1.1")
    assert manifest["applied"][0]["paths"] and manifest["version"] == "v1.1"
    from reps.knowledge_pack import _squash

    def sections(root: Path) -> dict[str, str]:
        rows = (root / "data" / "derived" / "rule_sections.jsonl").read_text(encoding="utf-8").splitlines()
        return {r["ref"]: r["text"] for r in map(json.loads, rows)}

    old, new = sections(Path(KB)), sections(kb_versions.built_dir("v1.1"))
    carded = {"R03 §2", "R04 §3", "R06 §2", "R06 §3.1", "R10 §2"}
    for ref in carded:
        card = new[ref].split("\n\n", 1)[0]
        assert card.startswith("> **规则卡**") and len(card) <= 400
        assert _squash(new[ref], 420).startswith(_squash(card, 420))     # the whole card survives truncation
    assert {r for r in old if old[r] != new[r]} == carded                # nothing else changed
    assert "不超过充能上限" in _squash(new["R03 §2"], 420)
    assert (Path(KB) / "README.md").read_text(encoding="utf-8").count("version: 1.0") == 1   # v1.0 untouched


@pytest.mark.skipif(not HAVE_KB, reason="needs GITCG_KB_DIR (KB v1.0)")
def test_reaction_card_matches_the_engine_table_cell_by_cell():
    """R06 §2: the v1.1 card must give the same reaction as the engine-derived table for every
    (aura, element) pair of the base table."""
    text = (Path(KB) / "rules" / "R06_elements_and_reactions.md").read_text(encoding="utf-8")
    section = text.split("## 2. 附着转移表", 1)[1].split("\n## ", 1)[0]
    header = None
    table: dict[tuple[str, str], str] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| 当前附着"):
            header = cells[1:]
        elif header and line.startswith("|") and not line.startswith("|---"):
            for element, cell in zip(header, cells[1:]):
                table[(cells[0], element)] = cell
    patch = (kb_versions.VERSIONS_DIR / "v1.1" / "changes.patch").read_text(encoding="utf-8")
    card = next(l[1:] for l in patch.splitlines() if l.startswith("+> **规则卡**（目标附着"))
    pairs: dict[frozenset, str] = {}
    for a, b, name in re.findall(r"([冰水火雷风岩草])\+([冰水火雷草/]+) (\S\S)", card):
        for x in b.split("/"):
            pairs[frozenset((a, x))] = name
    assert len(pairs) == 17
    reactions = {"融化", "蒸发", "超载", "超导", "感电", "冻结", "扩散", "结晶", "燃烧", "绽放", "激化"}
    checked = 0
    for (aura, element), cell in table.items():
        if aura not in ("冰", "水", "火", "雷", "草"):
            continue
        found = next((r for r in reactions if r in cell), None)
        assert pairs.get(frozenset((aura, element))) == found, (aura, element, cell)
        checked += 1
    assert checked == 35
    for element in ("水", "火", "雷", "风", "岩"):                    # cryo+dendro: cryo reacts, dendro stays
        cell = table[("冰+草", element)]
        assert cell.endswith("→ 草") and pairs[frozenset(("冰", element))] in cell
    assert "冰与草可以共存" in card and "先与冰反应，草保留" in card


# ------------------------------------------------------------------ mirror pairs


def _decks(n_per_split: int = 3) -> dict:
    out = {}
    for split in ("train", "dev", "test"):
        for version in ("v6.2.0", "v6.3.0"):
            for i in range(n_per_split):
                out[f"human:{split}{version}{i}"] = {"characters": [1, 2, 3], "cards": [], "native_version": version,
                                                     "mirror_split": split}
    return out


def test_pairs_swap_players_but_not_seats_or_decks():
    suite = mirror.build_pairs("dev", 6, _decks())
    assert len(suite.cells) == 12
    by_rep: dict[int, list[Cell]] = {}
    for c in suite.cells:
        by_rep.setdefault(c.rep, []).append(c)
        assert c.opponent_policy == mirror.RIVAL and "dev" in c.deck and c.version in c.deck
    for rep, (a, b) in by_rep.items():
        assert a.seed == b.seed and {a.side, b.side} == {0, 1}
        p0 = lambda c: c.deck if c.side == 0 else c.opponent_deck          # noqa: E731
        p1 = lambda c: c.opponent_deck if c.side == 0 else c.deck          # noqa: E731
        assert (p0(a), p1(a)) == (p0(b), p1(b)) and p0(a) != p1(a)
    seeds = {c.seed for c in suite.cells}
    assert seeds.isdisjoint({c.seed for c in mirror.build_pairs("test", 6, _decks()).cells})
    assert mirror.build_pairs("dev", 6, _decks()).fingerprint == suite.fingerprint   # deterministic


def test_deck_split_is_stable_and_roughly_4_3_3():
    counts = {"train": 0, "dev": 0, "test": 0}
    for i in range(3000):
        counts[mirror.deck_split(f"code{i}")] += 1
    assert mirror.deck_split("abc") == mirror.deck_split("abc")
    assert 0.35 < counts["train"] / 3000 < 0.45 and 0.25 < counts["dev"] / 3000 < 0.35


def _rows(subject: str, results: list[tuple[float, float]]) -> list[dict]:
    rows = []
    for rep, (first, second) in enumerate(results):
        for side, score in ((0, first), (1, second)):
            rows.append({"subject": subject, "cell": f"g|{rep}|{side}", "group": "g", "rep": rep, "side": side,
                         "score": score, "winner": side if score == 1 else 1 - side, "rounds": 6, "error": None,
                         "degraded": False, "rival_degraded": False,
                         "llm": {"usage": {"cost": 0.02, "calls": 10}}, "rival_llm": {"usage": {"cost": 0.01, "calls": 9}}})
    return rows


def test_report_pairs_aa_and_ab(tmp_path, monkeypatch):
    monkeypatch.setenv("GITCG_DATA_DIR", str(tmp_path))
    for tag, results in (("aa", [(1, 0)] * 8),                      # seat 0 wins both: every pair even
                         ("ab", [(1, 1)] * 6 + [(1, 0)] * 3 + [(0, 0)])):
        d = tmp_path / "bench" / tag
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"subjects": ["s"], "rival": "r"}), encoding="utf-8")
        (d / "games.jsonl").write_text("\n".join(json.dumps(r) for r in _rows("s", results)), encoding="utf-8")
    report = mirror.summarise(["aa", "ab"])
    aa, ab = report["arms"]
    assert (aa["pairs"], aa["win_rate"], aa["se"], aa["seat0_win_rate"], aa["same_seat_won_both"]) == (8, 0.5, 0.0, 1.0, 8)
    assert (ab["pairs"], ab["better"], ab["worse"], ab["even"]) == (10, 6, 1, 3)
    assert ab["win_rate"] == pytest.approx((6 * 2 + 3) / 20)
    assert ab["p_sign"] == pytest.approx(mirror.sign_test(6, 1))
    assert ab["cost_per_game_rival"] == pytest.approx(0.01)
    assert "胜率" in mirror.render_markdown(report, "t")


def test_a_broken_game_drops_its_whole_pair(tmp_path, monkeypatch):
    monkeypatch.setenv("GITCG_DATA_DIR", str(tmp_path))
    rows = _rows("s", [(1, 1), (1, 0)])
    rows[3]["rival_degraded"] = True
    d = tmp_path / "bench" / "x"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"subjects": ["s"], "rival": "r"}), encoding="utf-8")
    (d / "games.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    arm = mirror.summarise(["x"])["arms"][0]
    assert (arm["pairs"], arm["dropped_pairs"], arm["win_rate"]) == (1, 1, 1.0)


def test_runner_counts_the_rivals_spend():
    from bench.run import _totals

    calls, cost = _totals(_rows("s", [(1, 0)]))
    assert calls == 2 * (10 + 9) and cost == pytest.approx(2 * 0.03)


def test_trace_keeps_the_prompt_only_when_asked():
    from agents.llm_policy import DecisionTrace

    t = DecisionTrace(step_index=0, request_type="action", n_options=2, source="llm", final_code=1, final_index=0)
    assert "prompt" not in t.as_dict()
    t.prompt = "局面"
    assert t.as_dict()["prompt"] == "局面"


def test_version_detectors_leave_v10_untouched():
    from reps import knowledge

    assert knowledge.detector_table("") == knowledge._DETECTORS == knowledge.detector_table("1.0")
    s1 = knowledge.detector_table("1.0-s1")
    assert {"S01-P9", "S02-P7"} <= set(s1) and not {"S01-P9", "S02-P7"} & set(knowledge._DETECTORS)
    assert s1["S09-P4"] is not knowledge._DETECTORS["S09-P4"]          # re-conditioned only for s1
    assert set(knowledge.detector_ids()) == set(knowledge._DETECTORS)  # other callers see v1.0


def test_s1_detectors_fire_on_their_stated_conditions():
    from types import SimpleNamespace as NS

    from reps import knowledge
    from reps.schema import DecisionType, OptionKind

    def ctx(*, dice=4, opp_ended=False, energy=2, max_energy=2, kinds=("action_use_skill", "action_declare_end",
                                                                       "action_play_card"), supports=0):
        char = NS(is_active=True, defeated=False, energy=energy, max_energy=max_energy)
        me = NS(characters=(char,), dice=(1,) * dice, supports=(None,) * supports, summons=(), declared_end=False)
        opp = NS(characters=(), declared_end=opp_ended, supports=(), summons=())
        view = NS(players=(me, opp))
        specs = tuple(NS(kind=OptionKind(k)) for k in kinds)
        return NS(request_type=DecisionType.ACTION, acting_player=0, player_view=view, legal_low_level_specs=specs)

    t = knowledge.detector_table("1.0-s1")
    assert t["S02-P7"](ctx(dice=4)) and not t["S02-P7"](ctx(dice=6)) and not t["S02-P7"](ctx(dice=4, opp_ended=True))
    assert t["S01-P9"](ctx(dice=3)) and not t["S01-P9"](ctx(dice=3, energy=1)) and not t["S01-P9"](ctx(dice=2))
    assert t["S09-P4"](ctx(supports=4)) and not t["S09-P4"](ctx(supports=3))
    assert knowledge._DETECTORS["S09-P4"](ctx(supports=3))             # v1.0 condition unchanged


def test_call_log_spend_counts_calls_in_flight_incrementally(tmp_path):
    """D35: the runner's cap reads the call log (games still running included), not only finished rows."""
    from bench.run import _CallLog

    path = tmp_path / "calls.jsonl"
    log = _CallLog(path)
    assert log.totals() == (0, 0.0)
    path.write_text('{"cost": 0.01}\n{"cost": 0.02}\n{"cost": 0.', encoding="utf-8")   # last line still being written
    assert log.totals() == (2, pytest.approx(0.03))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('04}\n{"ok": false}\n')
    assert log.totals() == (4, pytest.approx(0.07))


def test_budget_kill_marks_the_game_for_retry(monkeypatch):
    import bench.run as run

    procs = run._Processes()
    procs.kill_all()                                      # budget already exhausted: any new game dies at once
    task = {"subject": "s", "key": "k", "cell": {"group": "g"}}
    row = run._spawn(task, 60, Path("/dev/null"), procs)
    assert row["error"] == "game process stopped: budget" and row["score"] is None
    assert row["error"].startswith("game process")       # resumed runs retry these
