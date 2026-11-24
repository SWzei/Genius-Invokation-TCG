"""Derived facts and character cards (D37, ``facts=1`` / ``cards=1``): what is shown, and no leaks. Fast, offline.

* the preview sanitizer keeps only damage / heal / aura entries of **skill** actions;
* the facts text is built from the seat view and the request only (full state unused);
* engine leak test: two games whose opponents hold different hidden hands but show the
  same public board give the acting seat the same facts and the same prompt.
"""

from __future__ import annotations

import dataclasses
import random
from types import SimpleNamespace as NS

import pytest

from agents.human import HumanQuit
from agents.llm_policy import build_messages
from envs.decks import deck_spec
from envs.match import run_match
from envs.policy import expert_policy
from reps import facts
from reps.describe import DecisionDescriber
from reps.schema import OptionKind

DECK, OPPONENT, SEED = "natlan_battleship", "superconduct_aggro", 11


class _Item:
    def __init__(self, which, **fields):
        self.which, self.payload = which, NS(**fields)
        setattr(self, which, self.payload)

    def WhichOneof(self, _):                      # noqa: N802 - protobuf API
        return self.which


class _Action:
    def __init__(self, kind, preview):
        self.kind, self.preview = kind, preview

    def HasField(self, name):                     # noqa: N802 - protobuf API
        return name == self.kind


def _damage(**kw):
    base = dict(damage_type=3, value=2, target_id=-5, target_definition_id=1101, reaction_type=102,
                old_health=10, new_health=8, cause_defeated=False)
    return _Item("damage", **{**base, **kw})


def test_sanitizer_keeps_only_public_effects_of_skills():
    preview = [_damage(), _damage(damage_type=9, value=1, reaction_type=0),
               _Item("apply_aura", element_type=1, target_id=-6, target_definition_id=1102, reaction_type=0),
               _Item("create_entity", who=0, where=1, entity=NS(definition_id=311101)),   # e.g. a drawn card
               _Item("modify_entity_var", entity_id=1, variable_name="usage")]
    kept = facts.sanitize_preview(_Action("use_skill", preview))
    assert [e["kind"] for e in kept] == ["damage", "heal", "aura"]
    assert all(set(e) <= {"kind", "target", "target_def", "value", "element", "reaction", "old_hp", "new_hp",
                          "defeated"} for e in kept)
    assert facts.sanitize_preview(_Action("play_card", preview)) == []          # cards can draw or roll
    assert facts.sanitize_preview(_Action("switch_active", preview)) == []


class _Capture:
    name = "capture"

    def __init__(self, inner, stop_after_action=False):
        self.inner, self.built, self.stop = inner, [], stop_after_action

    def choose(self, built):
        self.built.append(built)
        if self.stop and built.context.request_type.value == "action":
            raise HumanQuit("captured")
        return self.inner.choose(built)


class _Passive:
    """Public-only behaviour: keep the hand and dice, first character, declare end."""

    name = "passive"

    def choose(self, built):
        ctx = built.context
        for code, spec in zip(ctx.legal_low_level_codes, ctx.legal_low_level_specs):
            if spec.kind in (OptionKind.SWITCH_HANDS, OptionKind.REROLL_DICE) and \
                    not (spec.switch_hand_slot_mask or spec.reroll_dice_mask):
                return code
            if spec.kind == OptionKind.ACTION_DECLARE_END:
                return code
        return ctx.legal_low_level_codes[0]


@pytest.fixture(scope="module")
def game():
    capture = _Capture(expert_policy(DECK))
    record = run_match(deck_spec(DECK), deck_spec(OPPONENT), capture, expert_policy(OPPONENT), seed=SEED,
                       full_state_for_agents=True)
    assert record.error is None and record.outcome is not None
    return capture.built


def test_facts_come_from_the_view_and_the_request_only(game):
    describer = DecisionDescriber(facts=True)
    shown = 0
    for built in game:
        context = built.context
        if context.request_type.value != "action":
            continue
        text = describer.facts_text(context, len(context.legal_low_level_specs))
        blind = dataclasses.replace(context, full_state=None, full_state_json=None)
        assert describer.facts_text(blind, len(blind.legal_low_level_specs)) == text
        shown += "技能预演" in text
        for spec in context.legal_low_level_specs:
            if spec.kind != OptionKind.ACTION_USE_SKILL:
                assert facts.option_effects(context, spec) == []
    assert shown > 5


def test_prompt_shows_facts_only_when_asked(game):
    context = next(b.context for b in game if b.context.request_type.value == "action"
                   and "技能预演" in DecisionDescriber(facts=True).facts_text(b.context, 40))
    plain, _, _ = build_messages(context, DecisionDescriber(), reply="reason_first")
    with_facts, _, _ = build_messages(context, DecisionDescriber(facts=True), reply="reason_first")
    assert "派生事实" not in plain[1]["content"] and "技能预演" in with_facts[1]["content"]
    assert with_facts[1]["content"].index("派生事实") < with_facts[1]["content"].index("合法选项")


def _first_action(opponent_cards):
    opponent = dataclasses.replace(deck_spec(OPPONENT), cards=tuple(opponent_cards))
    capture = _Capture(expert_policy(DECK), stop_after_action=True)
    run_match(deck_spec(DECK), opponent, capture, _Passive(), seed=SEED, full_state_for_agents=True)
    return capture.built[-1].context


def test_engine_leak_test_hidden_opponent_hand_does_not_change_facts():
    cards = list(deck_spec(OPPONENT).cards)
    shuffled = cards[:]
    random.Random(5).shuffle(shuffled)
    a, b = _first_action(cards), _first_action(shuffled)
    assert a.request_type.value == b.request_type.value == "action"
    hand = lambda ctx: sorted(int(c.definition_id) for c in ctx.full_state.players[1].hand_cards)   # noqa: E731
    assert hand(a) != hand(b)                                       # the hidden hands really differ
    describer = DecisionDescriber(elements=True, facts=True, cards=True)
    assert describer.state_text(a) == describer.state_text(b)       # same public board
    assert describer.cards_text(a) == describer.cards_text(b)
    fa = describer.facts_text(a, len(a.legal_low_level_specs))
    assert "技能预演" in fa and fa == describer.facts_text(b, len(b.legal_low_level_specs))
    pa, _, _ = build_messages(a, describer, reply="reason_first")
    pb, _, _ = build_messages(b, describer, reply="reason_first")
    assert pa == pb


def test_character_cards_list_all_six_characters_from_the_card_data(game):
    from reps.dossier import _characters

    describer = DecisionDescriber(cards=True)
    context = next(b.context for b in game if b.context.request_type.value == "action")
    text = describer.cards_text(context)
    view = context.player_view
    assert text.index("对方") < text.index("我方")
    for player in view.players:
        for c in player.characters:
            item = _characters()[int(c.definition_id)]
            assert describer.assets.name(c.definition_id) in text
            for skill in item["skills"]:
                if skill.get("type") != "GCG_SKILL_TAG_PASSIVE":
                    assert f"【{skill['name']}】" in text
    message, _, _ = build_messages(context, describer, reply="reason_first")
    assert message[1]["content"].startswith("本局角色卡")
    blind = dataclasses.replace(context, full_state=None, full_state_json=None)
    assert describer.cards_text(blind) == text
