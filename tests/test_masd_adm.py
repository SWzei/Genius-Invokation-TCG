"""MASD-ADM / VCSD compatibility layer (PLAN D28).

Fast tests (no engine unless noted):

* supervision schema: exact sign test, paired comparison, the verification gate,
  JSON round-trip, store keys;
* knowledge adapter and tournament-deck adapter on fixture files (and on the
  real ``GITCG_KB`` / ``GITCG_Data`` release when ``GITCG_KB_DIR`` /
  ``GITCG_DATA_RELEASE`` point at them);
* strategy targets: modes, alignment checks, KL == CE for one-hot targets;
* training hook: off by default and byte-identical when off, deterministic;
* adaptive gates, text student, evidence-agreement metric;
* fork injection key check; belief roots over an inline hidden zone.

Slow engine tests: a label-only evidence game is the same game a plain collection
run records; its evidence is information-legal by construction (every fork starts
from a determinized public-belief root with empty prefixes and a verified
injection key); decision annotations and text do not read the full state.
"""

from __future__ import annotations

import dataclasses
import json
import os

import pytest
import torch

from reps.strategy import (
    SCHEMA,
    CandidateEstimate,
    CounterfactualEvidence,
    DecisionSupervision,
    OptionRef,
    Provenance,
    paired_comparison,
    read_supervision,
    reliability,
    sign_test_p,
    verdict,
    write_supervision,
)
from scripts.train_bc_scale import Config, Store, run_batch, train
from train.model import CVPN, CVPNConfig
from train.strategy_targets import DecisionTargets, TargetSpec, target_for

DECK, OPPONENT, SEED = "double_geo_navia", "aywolfskirk", 3
LEGAL = {"root": "public_belief", "empty_prefix": True}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _evidence(expert, alt, *, expert_index=0, alt_index=1, information=None) -> CounterfactualEvidence:
    return CounterfactualEvidence(
        candidates=(CandidateEstimate(expert_index, tuple(expert)), CandidateEstimate(alt_index, tuple(alt))),
        baseline_index=expert_index,
        continuation={"self": "expert:a", "opponent": "expert:b"},
        information=dict(LEGAL if information is None else information),
        rollouts=len(expert),
        base_seed=1,
    )


def _record(step=0, *, n_options=2, expert_index=0, evidence=None, side=0, knowledge=()) -> DecisionSupervision:
    return DecisionSupervision(
        deck="deck", opponent="opp", seed=1, side=side, step_index=step, ordinal=step,
        round_number=1, request_type="action",
        options=tuple(OptionRef(i, "action_use_skill", ["k", i], f"[{i}] option {i}") for i in range(n_options)),
        expert_index=expert_index, expert_policy="expert:deck", outcome=1.0, text="state text",
        knowledge=tuple(knowledge), evidence=evidence,
        provenance=Provenance(source="test", version="1"),
    )


def _store(n: int, *, teachers=None, n_options=2, side=0) -> Store:
    empty = torch.zeros(0)
    teachers = list(teachers) if teachers is not None else [0] * n
    torch.manual_seed(7)
    key = ("deck", "opp", 1) + ((side,) if side else ())
    return Store(
        tokens=[torch.randn(2, 4) for _ in range(n)],
        options=[torch.randn(n_options, 3) for _ in range(n)],
        teacher=teachers, value=[1.0, 0.0] * (n // 2) + [1.0] * (n % 2),
        b_hand=[empty.clone() for _ in range(n)], b_deck=[empty.clone() for _ in range(n)],
        b_hist=[empty.clone() for _ in range(n)], b_hsize=[0.0] * n, b_burst=[0.0] * n,
        b_mask=[False] * n, keys=[key + (i,) for i in range(n)],
    )


def _model(seed: int = 0) -> CVPN:
    torch.manual_seed(seed)
    return CVPN(CVPNConfig(token_dim=4, option_dim=3, d_model=8, option_hidden=8, value_hidden=8))


WIN8, LOSE8 = [1.0] * 8, [0.0] * 8


# --------------------------------------------------------------------------- #
# schema, statistics, gate
# --------------------------------------------------------------------------- #
def test_sign_test_is_exact_and_two_sided():
    assert sign_test_p(0, 0) == 1.0
    assert sign_test_p(5, 0) == pytest.approx(2 / 32)
    assert sign_test_p(6, 0) == pytest.approx(2 / 64)
    assert sign_test_p(0, 6) == sign_test_p(6, 0)
    assert sign_test_p(8, 1) == pytest.approx(2 * (9 + 1) / 512)
    assert sign_test_p(4, 4) == 1.0


def test_chance_of_passing_the_gate_is_exact():
    from reps.strategy import sign_test_pass_probability
    from train.evidence import summarize

    assert sign_test_pass_probability(5) == 0.0                     # 5-0 is p = 0.0625: cannot pass
    assert sign_test_pass_probability(6) == pytest.approx(2 / 64)   # only 6-0 / 0-6
    assert sign_test_pass_probability(8) == pytest.approx(2 / 256)  # only 8-0 / 0-8 (7-1 is p = 0.07)
    records = [
        _record(0, evidence=_evidence(LOSE8, WIN8)),                          # 8 discordant, passes
        _record(1, evidence=_evidence(LOSE8, [1.0] * 3 + [0.0] * 5)),         # 3 discordant, cannot pass
        _record(2, evidence=_evidence(WIN8, WIN8)),                           # no discordant pair
        _record(3),                                                           # no evidence
    ]
    summary = summarize(records)
    assert (summary["with_evidence"], summary["gate_eligible"], summary["verified"]) == (3, 3, 1)
    assert summary["can_pass"] == 1 and summary["no_discordant_pair"] == 1
    assert summary["expected_by_chance"] == pytest.approx(2 / 256, abs=1e-3)


def test_paired_comparison_pairs_by_rollout_and_skips_discarded():
    cmp = paired_comparison([1.0, None, 1.0, 0.0], [0.0, 0.0, None, 0.0], option_index=3, baseline_index=1)
    assert (cmp.n_pairs, cmp.wins, cmp.losses) == (2, 1, 0)   # only rollouts 0 and 3 are valid for both
    assert cmp.mean_diff == pytest.approx(0.5)
    empty = paired_comparison([None], [1.0], option_index=3, baseline_index=1)
    assert empty.n_pairs == 0 and reliability(empty) == 0.0


def test_gate_separates_verified_from_search_estimates():
    better = verdict(_evidence(LOSE8, WIN8))
    assert better.status == "alternative_supported" and better.option_index == 1 and better.verified
    worse = verdict(_evidence(WIN8, LOSE8))
    assert worse.status == "expert_supported" and worse.option_index == 0 and worse.verified
    # 5 wins / 0 losses is p = 0.0625 two-sided: an estimate, not a verified conclusion
    close = verdict(_evidence([0.0] * 8, [1.0] * 5 + [0.0] * 3))
    assert close.status == "inconclusive" and not close.verified and close.option_index == 0
    # too few pairs, however lopsided
    assert verdict(_evidence([0.0] * 6, [1.0] * 6)).status == "inconclusive"
    assert verdict(_evidence([0.0] * 6, [1.0] * 6), min_pairs=6).status == "alternative_supported"


def test_evidence_that_used_hidden_truth_is_never_verified():
    for information in ({"root": "true_state", "empty_prefix": True},
                        {"root": "public_belief", "empty_prefix": False}, {}):
        evidence = _evidence(LOSE8, WIN8, information=information)
        assert not evidence.is_information_legal
        assert verdict(evidence).status == "inconclusive"
        assert target_for(_record(evidence=evidence), TargetSpec(mode="evidence_gated")) is None
        assert target_for(_record(evidence=evidence), TargetSpec(mode="evidence_soft")) is None


def test_supervision_round_trip_and_schema_check(tmp_path):
    records = [_record(0, evidence=_evidence(LOSE8, [1.0, None] * 4), knowledge=("S01-P2",)), _record(5, side=1)]
    path = tmp_path / "sup.jsonl"
    assert write_supervision(path, records) == 2
    back = list(read_supervision(path))
    assert [r.as_dict() for r in back] == [r.as_dict() for r in records]
    assert back[0].evidence.candidates[1].scores == (1.0, None) * 4
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["schema"] == SCHEMA and row["expert_kind"] == "expert_action"
    assert row["evidence"]["kind"] == "search_estimate" and "verified" not in row["evidence"]
    row["schema"] = "masd.supervision/0"
    with pytest.raises(ValueError):
        DecisionSupervision.from_dict(row)


def test_store_key_layout_matches_the_trainer():
    from scripts.train_bc_scale import _game_key

    for side in (0, 1):
        record = _record(4, side=side)
        game = _game_key({"deck": "deck", "opponent": "opp", "seed": 1, "side": side})
        assert record.store_key == game + (4,)


# --------------------------------------------------------------------------- #
# knowledge + data adapters
# --------------------------------------------------------------------------- #
def _fixture_kb(root):
    derived = root / "data" / "derived"
    derived.mkdir(parents=True)
    (root / "README.md").write_text("---\nversion: 9.9\n---\n", encoding="utf-8")
    units = [
        {"id": "S01-P2", "title": "回合后期", "condition": "对方已结束", "recommendation": "先算再结束",
         "evidence_types": ["机制"], "confidence": "高", "limits": "", "doc": "S01", "version_baseline": "6.3"},
        {"id": "S99-P1", "title": "无检测器", "condition": "c", "recommendation": "r",
         "evidence_types": ["推断"], "confidence": "低", "limits": "", "doc": "S99", "version_baseline": "6.3"},
    ]
    rules = [{"ref": "R03 §3", "heading": "宣布结束", "text": "宣布回合结束 的规则", "evidence": ["官方"],
              "doc": "R03", "version_baseline": "6.3"}]
    (derived / "strategy_units.jsonl").write_text("\n".join(json.dumps(u, ensure_ascii=False) for u in units), encoding="utf-8")
    (derived / "rule_sections.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rules), encoding="utf-8")
    return root


def test_knowledge_base_loads_with_provenance(tmp_path):
    from reps.knowledge import KnowledgeBase, detector_coverage, render_units

    kb = KnowledgeBase.load(_fixture_kb(tmp_path / "kb"))
    unit = kb.unit("S01-P2")
    assert kb.version == "9.9" and unit.provenance.source == "GITCG_KB" and unit.provenance.version == "9.9"
    assert unit.kind == "language_strategy" and unit.confidence == "高" and unit.evidence_types == ("机制",)
    assert [r.ref for r in kb.rules_for_option_kind("action_declare_end")] == ["R03 §3"]
    assert kb.search("宣布回合结束")[0].ref == "R03 §3"
    coverage = detector_coverage(kb)
    assert coverage["units"] == 2 and coverage["detector_ids"] == ["S01-P2"]
    assert "S01-P2" in render_units(kb, ["S01-P2", "missing"])
    with pytest.raises(FileNotFoundError):
        KnowledgeBase.load(tmp_path / "nowhere")


@pytest.mark.skipif(not os.environ.get("GITCG_KB_DIR"), reason="GITCG_KB_DIR not set")
def test_real_knowledge_base_matches_the_adapter():
    from reps.knowledge import RULE_REFS_BY_OPTION_KIND, KnowledgeBase, detector_coverage

    kb = KnowledgeBase.load()
    coverage = detector_coverage(kb)
    assert coverage["detectors_without_unit"] == []          # every detector names a real unit
    missing = [ref for refs in RULE_REFS_BY_OPTION_KIND.values() for ref in refs if ref not in kb.rules]
    assert missing == []


def _fixture_release(root):
    games = root / "games"
    games.mkdir(parents=True)
    side = lambda code, valid=True, cards=30: {"deckCode": code, "deckValid": valid,
                                               "lineup": [1, 2, 3], "cards": list(range(cards))}
    rows = [
        {"gameId": "g1", "gameVersion": "6.1", "engineVersion": "v6.1.0", "winner": "A", "starter": "B",
         "qualityTier": "A", "split": "train", "tournament": {"name": "T"}, "A": side("AAA"), "B": side("BBB")},
        {"gameId": "g2", "gameVersion": "5.0", "engineVersion": "v5.0.0", "winner": None, "starter": "A",
         "qualityTier": "B", "split": "test", "A": side("AAA"), "B": side("CCC", valid=False)},
        {"gameId": "g3", "gameVersion": "6.1", "engineVersion": "v6.1.0", "winner": "B", "starter": "A",
         "qualityTier": "A", "split": "train", "A": side("DDD", cards=29), "B": side("EEE")},
    ]
    (games / "games_master.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return root


def test_tournament_decks_are_outcome_level_and_filtered(tmp_path):
    from envs.tournament_decks import iter_tournament_decks, unique_decks

    release = _fixture_release(tmp_path / "v1.0")
    decks = list(iter_tournament_decks(release))
    assert [d.deck_code for d in decks] == ["AAA", "BBB", "AAA", "EEE"]    # invalid / short decks dropped
    first = decks[0]
    assert first.won is True and first.started is False and first.engine_version == "v6.1.0"
    assert decks[2].won is None
    assert first.provenance.version == "v1.0" and first.provenance.extra["gameId"] == "g1"
    assert first.provenance.extra["evidence"] == "human_deck_choice_and_outcome_only"
    spec = first.spec("x")
    assert len(spec.cards) == 30 and len(spec.characters) == 3
    assert [d.deck_code for d in unique_decks(decks)] == ["AAA", "BBB", "EEE"]
    assert [d.deck_code for d in iter_tournament_decks(release, versions=["5.0"])] == ["AAA"]
    assert [d.deck_code for d in iter_tournament_decks(release, splits=["train"], tiers=["A"])] == ["AAA", "BBB", "EEE"]
    with pytest.raises(FileNotFoundError):
        list(iter_tournament_decks(tmp_path / "missing"))


@pytest.mark.skipif(not os.environ.get("GITCG_DATA_RELEASE"), reason="GITCG_DATA_RELEASE not set")
def test_real_release_decks_are_well_formed():
    from envs.tournament_decks import iter_tournament_decks, unique_decks

    decks = unique_decks(iter_tournament_decks())
    assert len(decks) > 1000
    assert all(len(d.cards) == 30 and len(d.characters) == 3 for d in decks)


# --------------------------------------------------------------------------- #
# strategy targets + training hook
# --------------------------------------------------------------------------- #
def test_target_modes_keep_evidence_classes_apart():
    verified = _record(evidence=_evidence(LOSE8, WIN8))
    unsure = _record(evidence=_evidence([0.0] * 8, [1.0] * 4 + [0.0] * 4))
    plain = _record()

    assert target_for(plain, TargetSpec(mode="expert")).probs == (1.0, 0.0)
    assert target_for(plain, TargetSpec(mode="evidence_gated")) is None       # no evidence -> no target
    gated = target_for(verified, TargetSpec(mode="evidence_gated"))
    assert gated.probs == (0.0, 1.0) and gated.source == "verified:alternative_supported"
    assert gated.weight == pytest.approx(1 - sign_test_p(8, 0))
    assert target_for(verified, TargetSpec(mode="evidence_gated", weighting="uniform")).weight == 1.0
    assert target_for(unsure, TargetSpec(mode="evidence_gated")) is None      # inconclusive -> no target
    soft = target_for(unsure, TargetSpec(mode="evidence_soft", temperature=0.5))
    assert soft.source == "search_estimate" and soft.probs[1] > soft.probs[0] > 0
    assert sum(soft.probs) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        TargetSpec(mode="language")       # no mode turns strategy text into an action label


def test_targets_align_by_key_and_reject_mismatches():
    store = _store(6, teachers=[0, 0, 0, 1, 0, 0])
    good = _evidence(LOSE8, WIN8)
    records = [
        _record(0, evidence=good),                      # matches
        _record(1, evidence=good, n_options=3),          # option count differs
        _record(3, evidence=good),                       # expert index differs (store says 1)
        _record(9, evidence=good),                       # not in the store
        _record(4, evidence=_evidence([0.0] * 8, [1.0] * 4 + [0.0] * 4)),   # inconclusive
        _record(0, evidence=good),                       # duplicate
    ]
    targets = DecisionTargets.for_store(store, records, TargetSpec())
    assert sorted(targets.probs) == [0]
    stats = targets.stats
    assert (stats["targets"], stats["mismatched_records"], stats["unmatched_records"],
            stats["records_without_target"], stats["duplicate_records"]) == (1, 2, 1, 1, 1)
    assert stats["target_differs_from_expert"] == 1
    with pytest.raises(ValueError):
        DecisionTargets.for_store(store, records, TargetSpec(), strict=True)
    # a seat-1 corpus only matches seat-1 records
    assert len(DecisionTargets.for_store(_store(6, side=1), records, TargetSpec())) == 0
    assert len(DecisionTargets.for_store(_store(6, side=1), [_record(0, evidence=good, side=1)], TargetSpec())) == 1


def test_one_hot_expert_kl_equals_cross_entropy():
    store = _store(8, teachers=[0, 1] * 4)
    records = [_record(i, expert_index=store.teacher[i]) for i in range(8)]
    targets = DecisionTargets.for_store(store, records, TargetSpec(mode="expert"), strict=True)
    index = list(range(8))
    model = _model()
    _, plain = run_batch(model, store, index, "cpu", 0.0, 0.0, False, Config())
    loss, info = run_batch(model, store, index, "cpu", 0.0, 0.0, False, Config(distill_coef=1.0),
                           decision_targets=targets)
    assert info["distill_n"] == 8
    assert info["distill"] == pytest.approx(plain["ce"], rel=1e-5)
    assert float(loss.detach()) == pytest.approx(2 * plain["ce"], rel=1e-5)


def test_kl_term_handles_padding_and_partial_coverage():
    store = _store(4)
    store.options[1] = torch.randn(5, 3)            # ragged option counts -> padded batch
    records = [_record(1, n_options=5, expert_index=0,
                       evidence=_evidence(LOSE8, WIN8, alt_index=4))]
    targets = DecisionTargets.for_store(store, records, TargetSpec(weighting="uniform"), strict=True)
    model = _model()
    loss, info = run_batch(model, store, [0, 1, 2, 3], "cpu", 0.0, 0.0, False, Config(distill_coef=2.0),
                           decision_targets=targets)
    assert torch.isfinite(loss) and info["distill_n"] == 1 and info["distill"] > 0
    loss.backward()
    assert all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None)
    # a batch without supervised rows contributes exactly nothing
    _, none = run_batch(model, store, [0, 2], "cpu", 0.0, 0.0, False, Config(distill_coef=2.0),
                        decision_targets=targets)
    assert none["distill"] == 0.0 and none["distill_n"] == 0


def _train(store, *, coef=0.0, targets=None, seed=0):
    model = _model(seed)
    history, _ = train(store, store.subset([0, 1]), model, Config(epochs=3, batch_size=4, seed=seed, distill_coef=coef),
                       False, decision_targets=targets)
    return model.state_dict(), history


def _same(a, b) -> bool:
    return all(torch.equal(a[k], b[k]) for k in a)


def test_training_hook_is_off_by_default_and_deterministic():
    store = _store(12, teachers=[0, 1] * 6)
    records = [_record(i, expert_index=store.teacher[i],
                       evidence=_evidence(LOSE8, WIN8, expert_index=store.teacher[i], alt_index=1 - store.teacher[i]))
               for i in range(12)]
    targets = DecisionTargets.for_store(store, records, TargetSpec(), strict=True)
    assert len(targets) == 12

    base, base_history = _train(store)
    # targets present but coefficient 0, or coefficient set but no targets: the legacy run
    assert _same(base, _train(store, coef=0.0, targets=targets)[0])
    assert _same(base, _train(store, coef=1.0, targets=None)[0])
    assert all("distill" not in row for row in base_history)

    on, on_history = _train(store, coef=1.0, targets=targets)
    assert not _same(base, on)
    assert all(row["distill"] > 0 for row in on_history)
    assert _same(on, _train(store, coef=1.0, targets=targets)[0])        # fixed seed -> same weights


def test_trainer_cli_wires_supervision(tmp_path):
    from scripts import datafirst_bc_train

    store = _store(12, teachers=[0, 1] * 6)
    # the CLI checks the store against an encoder; give it matching dims
    from envs.observation import default_encoder

    encoder = default_encoder()
    torch.manual_seed(0)
    store.tokens = [torch.randn(2, encoder.token_dim) for _ in range(12)]
    store.options = [torch.randn(2, encoder.option_dim) for _ in range(12)]
    cache = tmp_path / "store.pt"
    torch.save({"train": store, "val": store.subset([0, 1]), "meta": {"encoder_config": encoder.to_dict()}}, cache)
    records = [_record(i, expert_index=store.teacher[i],
                       evidence=_evidence(LOSE8, WIN8, expert_index=store.teacher[i], alt_index=1 - store.teacher[i]))
               for i in range(0, 12, 2)]
    sup = tmp_path / "sup.jsonl"
    write_supervision(sup, records)

    def run(name, *extra):
        report = tmp_path / f"{name}.json"
        argv = ["--store-cache", str(cache), "--d-model", "16", "--epochs", "2", "--batch-size", "4",
                "--out", str(tmp_path / f"{name}.pt"), "--report", str(report), *extra]
        assert datafirst_bc_train.main(argv) == 0
        return torch.load(tmp_path / f"{name}.pt", weights_only=False)["state_dict"], json.loads(report.read_text())

    base, base_report = run("base")
    off, off_report = run("off", "--supervision", str(sup))                 # no --distill-coef -> ignored
    on, on_report = run("on", "--supervision", str(sup), "--distill-coef", "1.0")
    assert _same(base, off) and "distill" not in off_report and base_report["config"]["distill_coef"] == 0.0
    assert not _same(base, on)
    assert on_report["distill"]["targets"] == 6 and on_report["distill"]["by_source"] == {"verified:alternative_supported": 6}
    assert on_report["history"][-1]["distill"] > 0


# --------------------------------------------------------------------------- #
# gates, students, metrics
# --------------------------------------------------------------------------- #
def test_adaptive_gates():
    from envs.adaptive import DisagreementGate, PriorUncertaintyGate, build_gate

    gate = build_gate("disagreement")
    assert isinstance(gate, DisagreementGate)
    assert gate(None, [0.1, 0.9], 0) is True and gate(None, [0.1, 0.9], 1) is False
    assert gate(None, None, 0) is False and (gate.seen, gate.passed) == (3, 1)
    margin = build_gate("margin:0.2")
    assert isinstance(margin, PriorUncertaintyGate)
    assert margin(None, [0.55, 0.45], 0) is True and margin(None, [0.9, 0.1], 0) is False
    assert margin(None, None, 0) is True
    entropy = build_gate("entropy:0.9")
    assert entropy(None, [0.5, 0.5], 0) is True and entropy(None, [0.99, 0.01], 0) is False
    assert build_gate("none") is None and build_gate(None) is None
    with pytest.raises(ValueError):
        build_gate("oracle")


def test_gate_only_allocates_budget_in_fork_search():
    from envs.fork_search import ForkSearchPolicy, SearchContext

    class Ctx:
        legal_low_level_codes = (10, 11, 12)
        request_type = "action"

    class Built:
        context = Ctx()

    class Base:
        name = "base"

        def choose(self, built):
            return 11

    class Bridge:
        workers = 1
        calls = 0

        def evaluate(self, tasks):
            from envs.fork_bridge import ForkResult

            Bridge.calls += 1
            return [ForkResult(index=t.index, winner=0 if t.inject_option == 2 else 1, rounds=1) for t in tasks]

    def policy(**kwargs):
        context = SearchContext(bridge=Bridge(), game_attrs={}, rollout_specs=(None, None), base_seed=1)
        context.update_boundary("{}")
        return ForkSearchPolicy(player=0, context=context, base=Base(), rollouts=2, top_k=None, **kwargs), context

    acting, _ = policy()
    assert acting.choose(Built()) == 12                       # historical behaviour: plays the best candidate
    label_only, context = policy(act_on_search=False)
    assert label_only.choose(Built()) == 11                   # label-only: always the base action
    decision = context.searches[0]
    assert decision.acted_on is False and decision.scores[2] == (1.0, 1.0) and decision.scores[1] == (0.0, 0.0)
    calls = Bridge.calls
    gated, context = policy(gate=lambda built, prior, base: False)
    assert gated.choose(Built()) == 11 and context.searches == [] and Bridge.calls == calls
    filtered, context = policy(request_types=("reroll_dice",))
    assert filtered.choose(Built()) == 11 and context.searches == []


def test_text_student_reads_only_record_text():
    from train.student import TextStudent, evidence_agreement, render_record

    seen = {}

    def scorer(prompt, options):
        seen["prompt"], seen["options"] = prompt, list(options)
        return [0.0, 2.0]

    record = _record(evidence=_evidence(LOSE8, WIN8))
    student = TextStudent(scorer)
    probs = student.record_distribution(record)
    assert probs[1] > probs[0] and sum(probs) == pytest.approx(1.0)
    assert seen["prompt"] == render_record(record) and "state text" in seen["prompt"]
    assert seen["options"] == ["[0] option 0", "[1] option 1"]
    # nothing outcome- or evidence-derived reaches the prompt
    assert "1.0" not in seen["prompt"] and "scores" not in seen["prompt"]
    with pytest.raises(ValueError):
        TextStudent(lambda prompt, options: [0.0]).record_distribution(record)

    records = [record, _record(1, evidence=_evidence(WIN8, LOSE8)), _record(2)]
    follows = evidence_agreement({r.store_key: (1 if i == 0 else 0) for i, r in enumerate(records)}, records)
    assert follows == {"n": 3, "expert_agreement": pytest.approx(2 / 3, abs=1e-4), "verified_n": 2,
                       "verified_agreement": 1.0, "dq_n": 2, "mean_dq_of_choice": 0.5}
    expert_only = evidence_agreement({r.store_key: 0 for r in records}, records)
    assert expert_only["verified_agreement"] == 0.5 and expert_only["mean_dq_of_choice"] == 0.0


def test_network_student_matches_training_features():
    from train.student import NetworkStudent

    store = _store(5)
    store.options[2] = torch.randn(4, 3)
    model = _model()
    student = NetworkStudent(model=model, encoder=None)
    dists = student.store_distributions(store, [0, 2, 4], batch_size=2)
    assert [len(d) for d in dists] == [2, 4, 2]
    assert all(sum(d) == pytest.approx(1.0, abs=1e-5) for d in dists)
    tokens, options = store.tokens[2].unsqueeze(0), store.options[2].unsqueeze(0)
    logits, _ = model(tokens, torch.ones(1, 2, dtype=torch.bool), options, torch.ones(1, 4, dtype=torch.bool))
    assert dists[1] == pytest.approx(torch.softmax(logits, -1)[0].tolist(), abs=1e-5)


def test_distillation_term_composes_with_policy_gradient():
    store = _store(8, teachers=[0, 1] * 4)
    records = [_record(i, expert_index=store.teacher[i],
                       evidence=_evidence(LOSE8, WIN8, expert_index=store.teacher[i], alt_index=1 - store.teacher[i]))
               for i in range(8)]
    targets = DecisionTargets.for_store(store, records, TargetSpec(), strict=True)
    index = list(range(8))
    model = _model()
    plain, _ = run_batch(model, store, index, "cpu", 0.5, 0.0, False, Config(loss="pg"))
    loss, info = run_batch(model, store, index, "cpu", 0.5, 0.0, False, Config(loss="pg", distill_coef=0.5),
                           decision_targets=targets)
    assert torch.isfinite(loss) and info["distill_n"] == 8
    assert float(loss.detach()) == pytest.approx(float(plain.detach()) + 0.5 * info["distill"], rel=1e-5)


def test_students_load_both_architectures(tmp_path):
    from train.model import TransformerCVPN, TransformerCVPNConfig
    from train.resolver import prior_resolver_from_checkpoint
    from train.student import NetworkStudent, Student

    cvpn = _model()
    transformer = TransformerCVPN(TransformerCVPNConfig(token_dim=4, option_dim=3, d_model=16, n_layers=1, n_heads=2))
    store = _store(3)
    for name, model in (("cvpn", cvpn), ("transformer", transformer)):
        path = tmp_path / f"{name}.pt"
        model.save(str(path))
        student = NetworkStudent.from_checkpoint(str(path))
        assert isinstance(student, Student) and type(student.model) is type(model)
        dists = student.store_distributions(store, [0, 1, 2])
        assert all(len(d) == 2 and sum(d) == pytest.approx(1.0, abs=1e-5) for d in dists)
        # the search prior loader used to assume the mean-pool CVPN
        assert type(prior_resolver_from_checkpoint(str(path)).model) is type(model)


def test_evidence_cli_resumes_and_refuses_spec_drift(tmp_path, monkeypatch):
    import envs.fork_bridge
    import train.evidence
    from scripts import collect_evidence

    played = []

    def fake_game(spec, **kwargs):
        played.append((spec.opponent, spec.seed, spec.side))
        record = dataclasses.replace(_record(len(played), evidence=_evidence(LOSE8, WIN8)),
                                     deck=spec.deck, opponent=spec.opponent, seed=spec.seed, side=spec.side)
        return train.evidence.EvidenceGame(spec=spec, supervision=[record], winner=0, error=None,
                                           teacher_decisions=5, searched=1, wall_seconds=0.0)

    class FakeBridge:
        def __init__(self, workers):
            self.workers = workers

        def close(self):
            pass

    monkeypatch.setattr(train.evidence, "collect_evidence_game", fake_game)
    monkeypatch.setattr(train.evidence, "default_describer", lambda name: None)
    monkeypatch.setattr(envs.fork_bridge, "ForkBridge", FakeBridge)
    monkeypatch.delenv("GITCG_KB_DIR", raising=False)
    out = tmp_path / "ev"
    base = ["--deck", DECK, "--opponents", OPPONENT, "dvalin_bonk", "--seed-start", "1", "--seed-count", "2",
            "--rollouts", "8", "--tag", "t", "--out-dir", str(out)]

    assert collect_evidence.main(base + ["--max-decisions", "2"]) == 0        # budget stops after 2 games
    assert len(played) == 2
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["spec"]["rollouts"] == 8 and manifest["engine_lock"] is not None
    assert manifest["summary"]["verdicts"]["alternative_supported"] == 2

    # an unfinished game leaves records without a done-marker: resume drops exactly those
    orphan = dataclasses.replace(_record(99), deck=DECK, opponent="dvalin_bonk", seed=2)
    write_supervision(out / "supervision.jsonl", [orphan], append=True)
    assert collect_evidence.main(base) == 0
    assert len(played) == 4 and len(set(played)) == 4                         # finished games are not replayed
    records = list(read_supervision(out / "supervision.jsonl"))
    assert len(records) == 4 and all(r.step_index != 99 for r in records)
    assert len((out / "games.jsonl").read_text(encoding="utf-8").splitlines()) == 4

    assert collect_evidence.main(base) == 0 and len(played) == 4               # nothing left to do
    with pytest.raises(SystemExit):
        collect_evidence.main(base[:-6] + ["--rollouts", "16", "--tag", "t", "--out-dir", str(out)])


# --------------------------------------------------------------------------- #
# fork alignment + belief roots
# --------------------------------------------------------------------------- #
def test_fork_task_carries_the_injection_key():
    from envs.fork_bridge import ForkTask

    task = ForkTask(index=0, snapshot="{}", game_attrs={}, deck0="a", deck1="b", inject_key=("skill", (1, 2)))
    payload = task.as_dict()
    assert payload["inject_key"] == ["skill", [1, 2]]
    assert ForkTask.from_dict(json.loads(json.dumps(payload))).inject_key == ["skill", [1, 2]]
    assert "inject_key" not in ForkTask(index=0, snapshot="{}", game_attrs={}, deck0="a", deck1="b").as_dict()


def test_belief_roots_accept_an_inline_hidden_zone():
    """The engine serialises ``hands`` inline in ~1% of boundary snapshots (2026-11)."""
    from reps.belief import sample_belief_roots
    from tests.test_belief_root import _hidden_content, _mk_state_json

    scaffold = json.loads(_mk_state_json())
    store = scaffold["store"]
    inlined = 0
    for node in store:
        if isinstance(node, dict) and "hands" in node and isinstance(node["hands"], dict):
            node["hands"] = list(store[int(node["hands"]["$"])])       # inline copy of the zone
            inlined += 1
    assert inlined == 2
    deck = (4, 5, 6, 7, 8, 9, 10, 11, 12, 13)
    roots = sample_belief_roots(json.dumps(scaffold), root_player=0, opponent_deck_cards=deck, samples=2)
    reference = sample_belief_roots(_mk_state_json(), root_player=0, opponent_deck_cards=deck, samples=2)
    assert len(roots) == 2

    def opp_hand_defs(root_json):
        s = json.loads(root_json)["store"]
        root = next(n for n in reversed(s) if isinstance(n, dict) and "players" in n)
        opponent = s[int(s[int(root["players"]["$"])][1]["$"])]
        zone = opponent["hands"] if isinstance(opponent["hands"], list) else s[int(opponent["hands"]["$"])]
        ids = [int(s[int(ref["$"])]["id"]) for ref in zone]
        defs = sorted(int(s[int(s[int(ref["$"])]["definition"]["$"])].get("id", 0)) for ref in zone)
        return ids, defs

    for inline_root, ref_root in zip(roots, reference):
        ids, defs = opp_hand_defs(inline_root)
        assert all(i < 0 for i in ids)                                   # synthetic ids, no true identity
        assert defs == _hidden_content(ref_root)["opp_hand_defs"]         # same particle either way


def test_belief_roots_keep_what_the_player_sees_on_its_own_hand():
    """Attachments / variables on the root player's hand cards change cost and legality."""
    from reps.belief import sample_belief_roots
    from tests.test_belief_root import _mk_state_json

    def players(store):
        root = next(n for n in reversed(store) if isinstance(n, dict) and "players" in n)
        return [store[int(ref["$"])] for ref in store[int(root["players"]["$"])]]

    scaffold = json.loads(_mk_state_json())
    store = scaffold["store"]
    # any entity node can stand in for an attachment; reuse the root player's first pile card
    marker = dict(store[int(players(store)[0]["pile"]["$"])][0])
    for player in players(store):
        card = store[int(store[int(player["hands"]["$"])][0]["$"])]
        card["attachments"] = [dict(marker)]
        card["variables"] = {"costDelta": 1}
    deck = (4, 5, 6, 7, 8, 9, 10, 11, 12, 13)
    for root_json in sample_belief_roots(json.dumps(scaffold), root_player=0, opponent_deck_cards=deck, samples=2):
        out = json.loads(root_json)["store"]
        mine, theirs = players(out)
        own_first = out[int(out[int(mine["hands"]["$"])][0]["$"])]
        assert own_first["attachments"] == [marker] and own_first["variables"] == {"costDelta": 1}
        # the opponent's hand is resampled: nothing of the true cards survives
        for ref in out[int(theirs["hands"]["$"])]:
            assert out[int(ref["$"])]["attachments"] == [] and out[int(ref["$"])]["variables"] == {}


# --------------------------------------------------------------------------- #
# engine tests
# --------------------------------------------------------------------------- #
class _SpyBridge:
    """Records every fork task and the boundary snapshots the live game produced."""

    def __init__(self, inner):
        self.inner, self.workers, self.tasks = inner, inner.workers, []

    def evaluate(self, tasks):
        self.tasks.extend(tasks)
        return self.inner.evaluate(tasks)


@pytest.fixture(scope="module")
def evidence_game():
    from envs.fork_bridge import ForkBridge
    from reps.knowledge import matching_units
    from train.evidence import EvidenceSpec, collect_evidence_game, default_describer

    spec = EvidenceSpec(DECK, OPPONENT, seed=SEED, side=1, rollouts=2, top_k=1, max_searches=3)
    with ForkBridge(workers=2) as inner:
        bridge = _SpyBridge(inner)
        game = collect_evidence_game(spec, bridge=bridge, describer=default_describer(OPPONENT),
                                     annotate=matching_units, provenance_extra={"tag": "test"})
    return spec, game, bridge


@pytest.mark.slow
def test_evidence_game_is_the_collected_game(evidence_game):
    from envs.observation import encoder_for_profile
    from train.data import collect_samples

    spec, game, _ = evidence_game
    assert game.error is None and game.searched == 3 and len(game.supervision) == 3
    samples = collect_samples(DECK, OPPONENT, [SEED], encoder=encoder_for_profile("v2"), teacher_side=1)
    assert game.trace == [(s.step_index, s.n_options, s.teacher_index) for s in samples]
    by_step = {s.step_index: s for s in samples}
    for record in game.supervision:
        sample = by_step[record.step_index]
        assert record.store_key == (DECK, OPPONENT, SEED, 1, record.step_index)
        assert (len(record.options), record.expert_index) == (sample.n_options, sample.teacher_index)
        assert record.request_type == "action" and record.outcome == sample.value_target


@pytest.mark.slow
def test_evidence_is_information_legal_by_construction(evidence_game):
    from reps.knowledge import detector_ids

    spec, game, bridge = evidence_game
    assert bridge.tasks
    for task in bridge.tasks:
        assert task.prefix0 == () and task.prefix1 == ()      # the fork starts at the decision itself
        # ...and checks that it injects the same action into the same legal option list
        assert set(task.inject_key) == {"option", "legal"}
        assert task.inject_player == 1
        store = json.loads(task.snapshot)["store"]
        root = next(n for n in reversed(store) if isinstance(n, dict) and "players" in n)
        opponent = store[int(store[int(root["players"]["$"])][0]["$"])]
        hands = opponent["hands"] if isinstance(opponent["hands"], list) else store[int(opponent["hands"]["$"])]
        # opponent hand cards of a determinized root carry synthetic (negative) ids
        assert all(int(store[int(ref["$"])]["id"]) < 0 for ref in hands)
    for record in game.supervision:
        evidence = record.evidence
        assert evidence.is_information_legal
        assert evidence.information["assumptions"] == ["opponent_decklist_known"]
        assert evidence.baseline_index == record.expert_index
        assert evidence.candidate(record.expert_index) is not None and len(evidence.candidates) == 2
        assert all(len(c.scores) == spec.rollouts for c in evidence.candidates)
        assert evidence.continuation == {"self": f"expert:{DECK}", "opponent": f"expert:{OPPONENT}"}
        assert evidence.errors == {}
        assert set(record.knowledge) <= set(detector_ids())
        assert record.text and all(option.text for option in record.options)
        assert DecisionSupervision.from_dict(json.loads(json.dumps(record.as_dict()))).as_dict() == record.as_dict()
    # same root particle and rollout seed across the candidates of one decision
    by_decision: dict[tuple, list] = {}
    for task in bridge.tasks:
        by_decision.setdefault((task.snapshot, task.rollout_seed), []).append(task.inject_option)
    assert all(len(options) == 2 and len(set(options)) == 2 for options in by_decision.values())


@pytest.mark.slow
def test_evidence_is_reproducible(evidence_game):
    from envs.fork_bridge import ForkBridge
    from train.evidence import collect_evidence_game

    spec, game, _ = evidence_game
    again_spec = dataclasses.replace(spec, max_searches=1)
    with ForkBridge(workers=1) as bridge:                      # a different worker count on purpose
        again = collect_evidence_game(again_spec, bridge=bridge)
    first, repeat = game.supervision[0], again.supervision[0]
    assert repeat.store_key == first.store_key
    assert repeat.evidence.as_dict() == first.evidence.as_dict()


@pytest.mark.slow
def test_annotations_and_text_do_not_read_the_full_state():
    from envs.decks import deck_spec
    from envs.match import run_match
    from envs.policy import expert_policy
    from reps.knowledge import matching_units
    from train.evidence import default_describer, option_refs
    from train.student import render_context

    class Capture:
        name = "capture"

        def __init__(self, inner):
            self.inner, self.contexts = inner, []

        def choose(self, built):
            self.contexts.append(built.context)
            return self.inner.choose(built)

    capture = Capture(expert_policy(DECK))
    record = run_match(deck_spec(DECK), deck_spec(OPPONENT), capture, expert_policy(OPPONENT),
                       seed=SEED, full_state_for_agents=True)
    assert record.error is None
    describer = default_describer(OPPONENT)
    matched = set()
    for context in capture.contexts:
        assert context.full_state is not None
        blind = dataclasses.replace(context, full_state=None)
        assert matching_units(context) == matching_units(blind)
        assert render_context(context, describer=describer) == render_context(blind, describer=describer)
        assert option_refs(context, describer) == option_refs(blind, describer)
        matched.update(matching_units(context))
        # the opponent's dice faces are hidden in the view; the text shows only the public count
        opponent = context.player_view.players[1]
        assert f"dice={len(opponent.dice) if len(opponent.dice) else getattr(opponent, 'dice_count', 0)}" in \
            describer.describe_state(context) or "dice=" in describer.describe_state(context)
    assert len(matched) >= 5        # the detectors do fire on real decisions


@pytest.mark.slow
def test_misaligned_injection_is_reported_not_scored():
    from envs.fork_bridge import ForkTask, run_fork_task
    from envs.match import _build_create_param
    from envs.decks import deck_spec
    from envs.snapshot import capture_snapshot
    from gitcg import Game

    game = Game(create_param=_build_create_param(deck_spec(DECK), deck_spec(OPPONENT), seed=SEED, version=None))
    snapshot = capture_snapshot(game)
    common = dict(snapshot=snapshot, game_attrs={}, deck0=DECK, deck1=OPPONENT, inject_player=0,
                  inject_ordinal=1, inject_option=0, rollout0=f"expert:{DECK}", rollout1=f"expert:{OPPONENT}",
                  rollout_seed=5)
    plain = run_fork_task(ForkTask(index=0, **common))
    assert plain["error"] is None
    wrong = run_fork_task(ForkTask(index=1, inject_key=["not", "this", "action"], **common))
    assert wrong["error"] is not None and wrong["error"].startswith("inject key mismatch")
    # ForkSearchPolicy(verify_inject_key=True) discards such a result instead of scoring it
    from envs.fork_bridge import ForkResult

    assert ForkResult.from_dict(wrong).error == wrong["error"]


@pytest.mark.slow
def test_fork_must_offer_the_legal_options_the_player_saw(evidence_game):
    from envs.fork_bridge import run_fork_task

    _, _, bridge = evidence_game
    task = bridge.tasks[0]
    assert run_fork_task(task)["error"] is None
    other_world = dataclasses.replace(task, inject_key={**task.inject_key, "legal": "0" * 16})
    error = run_fork_task(other_world)["error"]
    assert error is not None and error.startswith("inject legal-list mismatch")
