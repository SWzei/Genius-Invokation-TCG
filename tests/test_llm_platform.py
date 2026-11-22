"""Decision rendering, knowledge packs and the LLM player (PLAN D29).

One local game supplies real decision contexts of every request type. No network:
models are scripted clients or the built-in ``mock`` provider.

Covered: what a model is shown (complete for the acting seat, nothing hidden);
every legal option is describable and every reply format maps onto a legal option;
knowledge selection by profile with facts and opinions kept apart, provenance and
version checks; the player's legality / fallback / budget / trace guarantees; full
games through the ``llm:`` policy spec.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from agents.llm_policy import (LLMPolicy, LLMPolicyConfig, build_messages, discuss, parse_llm_spec,
                               parse_reply)
from common.llm_providers import ChatResult, build_client
from envs.decks import deck_spec
from envs.match import run_match
from envs.policy import build_policy, expert_policy
from reps.describe import DecisionDescriber, find_mask_option
from reps.knowledge_pack import (KnowledgeProfile, KnowledgeSelector, load_custom,
                                 load_knowledge_profiles, profile_from_mapping)
from reps.strategy import DecisionSupervision, OptionRef, Provenance, write_supervision

DECK, OPPONENT, SEED = "natlan_battleship", "superconduct_aggro", 5


class _Capture:
    name = "capture"

    def __init__(self, inner):
        self.inner, self.built = inner, []

    def choose(self, built):
        self.built.append(built)
        return self.inner.choose(built)


@pytest.fixture(scope="module")
def game():
    capture = _Capture(expert_policy(DECK))
    record = run_match(deck_spec(DECK), deck_spec(OPPONENT), capture, expert_policy(OPPONENT),
                       seed=SEED, full_state_for_agents=True)
    assert record.error is None
    return capture.built


@pytest.fixture(scope="module")
def by_request(game):
    out = {}
    for built in game:
        context = built.context
        request = context.request_type.value
        view = context.player_view
        richness = (len(view.players[0].summons) + len(view.players[0].supports) + len(view.players[1].summons)
                    + len(context.legal_low_level_specs))
        if len(context.legal_low_level_specs) > 1 and (request not in out or richness > out[request][1]):
            out[request] = (built, richness)
    return {request: built for request, (built, _) in out.items()}


@pytest.fixture(scope="module")
def describer():
    return DecisionDescriber()


# --------------------------------------------------------------------------- #
# what the model is shown
# --------------------------------------------------------------------------- #
def test_state_is_complete_for_the_acting_seat_and_hides_the_rest(game, describer):
    assert len(describer.assets.entries) > 1000
    for built in game[::7]:
        context = built.context
        view = context.player_view
        me, opponent = view.players[0], view.players[1]
        state = describer.state(context)
        text = describer.state_text(context)
        # own side: every character, hand card, die, summon, support is present by name
        assert [c["name"] for c in state["me"]["characters"]] == [describer.assets.name(c.definition_id) for c in me.characters]
        assert [c["hp"] for c in state["me"]["characters"]] == [c.health for c in me.characters]
        assert len(state["me"]["hand"]) == len(me.hand_cards) and len(state["me"]["dice"]) == len(me.dice)
        for card in me.hand_cards:
            assert describer.assets.name(card.definition_id) in text
        for entity in (*me.summons, *me.supports, *opponent.summons, *opponent.supports):
            assert describer.assets.name(entity.definition_id) in text
        assert not any(name.startswith("#") for name in (c["name"] for c in state["me"]["hand"]))
        # opponent side: counts only
        assert "hand" not in state["opponent"] and "dice" not in state["opponent"]
        assert state["opponent"]["hand_count"] == len(opponent.hand_cards)
        assert state["opponent"]["pile_count"] == len(opponent.pile_cards)
        # nothing is read from the full state
        blind = dataclasses.replace(context, full_state=None)
        assert describer.state(blind) == state and describer.options(blind) == describer.options(context)


def test_opponent_hidden_cards_never_reach_the_text(game, describer):
    """The opponent's true hand comes from the full state; none of it may leak."""
    leaks = 0
    for built in game[::5]:
        context = built.context
        assert context.full_state is not None
        truth = context.full_state.players[1]
        visible = context.player_view.players[1]
        assert all(int(card.definition_id) == 0 for card in visible.hand_cards)       # masked in the view
        public_names = describer.state_text(context)
        own_names = {describer.assets.name(c.definition_id) for c in context.player_view.players[0].hand_cards}
        for card in truth.hand_cards:
            name = describer.assets.name(card.definition_id)
            # a name may legitimately appear if we hold the same card or it is on the board
            if name in own_names or name in json.dumps(describer.state(context)["opponent"], ensure_ascii=False):
                continue
            leaks += int(name in public_names and f"【{name}】" in public_names)
    assert leaks == 0


def test_every_option_of_every_request_type_is_described(by_request, describer):
    assert set(by_request) >= {"action", "choose_active", "reroll_dice", "switch_hands"}
    for request, built in by_request.items():
        options = describer.options(built.context)
        assert [o["index"] for o in options] == list(range(len(built.context.legal_low_level_specs)))
        assert all(o["text"] and o["public_text"] for o in options)
        assert [o["code"] for o in options] == [int(c) for c in built.context.legal_low_level_codes]
        if request == "action":
            kinds = {o["kind"] for o in options}
            assert "action_declare_end" in kinds and any("pay" in o for o in options)
            assert any(o.get("fast") is True for o in options) or any(o.get("fast") is False for o in options)
        else:
            assert not any("宣布回合结束" in o["text"] for o in options)
    # reroll / switch-hands texts never reveal identities to the opponent
    assert all(o["public_text"].startswith("重掷") and "冰" not in o["public_text"]
               for o in describer.options(by_request["reroll_dice"].context))


def test_legacy_describer_no_longer_calls_everything_declare_end(by_request):
    from agents.llm_assist import ContextDescriber
    from envs.policy import _asset_catalog

    legacy = ContextDescriber(_asset_catalog())
    for request in ("choose_active", "reroll_dice", "switch_hands"):
        context = by_request[request].context
        texts = [legacy.describe_candidate(context, spec, i) for i, spec in enumerate(context.legal_low_level_specs[:5])]
        assert not any("declare end" in text for text in texts)
    action = by_request["action"].context
    assert any("declare end" in legacy.describe_candidate(action, spec, i)
               for i, spec in enumerate(action.legal_low_level_specs))
    assert "opponent hand size=" in legacy.describe_state(action)


def test_position_answers_map_onto_legal_options(by_request, describer):
    reroll = by_request["reroll_dice"].context
    dice = list(reroll.player_view.players[0].dice)
    for positions in ([], [0], [0, 1], list(range(len(dice)))):
        index = find_mask_option(reroll, positions)
        assert index is not None
        mask = reroll.legal_low_level_specs[index].reroll_dice_mask
        assert sorted(dice[i] for i in range(len(dice)) if mask >> i & 1) == sorted(dice[p] for p in positions)
    assert find_mask_option(reroll, [99]) is None
    swap = by_request["switch_hands"].context
    index = find_mask_option(swap, [1, 3])
    assert swap.legal_low_level_specs[index].switch_hand_slot_mask == 0b1010
    assert find_mask_option(by_request["action"].context, [0]) is None


# --------------------------------------------------------------------------- #
# knowledge packs
# --------------------------------------------------------------------------- #
def _fixture_kb(root):
    from reps.knowledge import KnowledgeBase

    derived = root / "data" / "derived"
    derived.mkdir(parents=True)
    (root / "README.md").write_text("---\nversion: 3.1\n---\n", encoding="utf-8")
    units = [
        {"id": "S04-P1", "title": "切人的代价", "condition": "考虑切换出战角色", "recommendation": "先算清切人占用的骰子与行动",
         "evidence_types": ["机制"], "confidence": "高", "limits": "不含快速切换", "doc": "S04", "version_baseline": "通用"},
        {"id": "S02-P1", "title": "继续还是结束", "condition": "可以宣布结束", "recommendation": "比较继续行动的收益与先手价值",
         "evidence_types": ["推断"], "confidence": "低", "limits": "", "doc": "S02", "version_baseline": "通用"},
    ]
    rules = [
        {"ref": "R03 §1", "heading": "战斗行动与快速行动【官方】", "text": "战斗行动结束后轮到对方。\n快速行动之后仍可继续行动。",
         "evidence": ["官方", "引擎"], "doc": "R03", "version_baseline": "v7.2.0"},
        {"ref": "R03 §2", "heading": "切换角色", "text": "切换角色消耗 1 个任意元素骰。", "evidence": ["官方", "待核"],
         "doc": "R03", "version_baseline": "v3.3.0–v6.0.0"},
        {"ref": "R03 §3", "heading": "宣布结束", "text": "先宣布结束的一方下回合先手。", "evidence": ["派生"],
         "doc": "R03", "version_baseline": "v7.2.0"},
    ]
    (derived / "strategy_units.jsonl").write_text("\n".join(json.dumps(u, ensure_ascii=False) for u in units), encoding="utf-8")
    (derived / "rule_sections.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rules), encoding="utf-8")
    return KnowledgeBase.load(root)


def test_profiles_select_sources_and_keep_fact_and_opinion_apart(by_request, tmp_path):
    kb = _fixture_kb(tmp_path / "kb")
    context = by_request["action"].context
    assert KnowledgeSelector(KnowledgeProfile(), kb=kb).select(context).items == []

    rules = KnowledgeSelector(KnowledgeProfile(name="rules", rules=True), kb=kb).select(context)
    assert {item.kind for item in rules.items} == {"rule"} and rules.kb_version == "3.1"
    ids = [item.id for item in rules.items]
    assert "R03 §1" in ids and "R03 §2" in ids
    assert "R03 §3" not in ids                                   # evidence is only 派生: not official / engine
    flagged = next(item for item in rules.items if item.id == "R03 §2")
    assert "待核" in flagged.trust and "\n" not in next(i for i in rules.items if i.id == "R03 §1").text
    assert any("R03 §2" in w and "v6.0.0" in w for w in rules.warnings)      # written for an older game version
    assert not any("R03 §1" in w for w in rules.warnings)

    strategy = KnowledgeSelector(KnowledgeProfile(name="s", strategy=True), kb=kb).select(context)
    assert {item.kind for item in strategy.items} == {"strategy"}
    assert {"S04-P1", "S02-P1"} >= {item.id for item in strategy.items} and strategy.items
    assert all("KB 置信度" in item.trust for item in strategy.items)
    high_only = KnowledgeSelector(KnowledgeProfile(strategy=True, strategy_confidence=("高",)), kb=kb).select(context)
    assert all(item.id != "S02-P1" for item in high_only.items)

    both = KnowledgeSelector(KnowledgeProfile(name="both", rules=True, strategy=True), kb=kb).select(context)
    text = both.text
    assert text.index("【规则事实】") < text.index("【策略观点（未经验证）】")
    facts, opinions = text.split("【策略观点（未经验证）】")
    assert "R03 §1" in facts and "S04-P1" not in facts and "S04-P1" in opinions and "R03 §1" not in opinions
    assert [i["kind"] for i in both.as_dict()["items"]].count("rule") == 2
    # a tight budget keeps facts and drops opinions first
    tight = KnowledgeSelector(KnowledgeProfile(rules=True, strategy=True, max_chars=150), kb=kb).select(context)
    assert tight.items and all(item.is_fact for item in tight.items)
    # selection reads the player's view only
    blind = dataclasses.replace(context, full_state=None)
    again = KnowledgeSelector(KnowledgeProfile(name="both", rules=True, strategy=True), kb=kb).select(blind)
    assert again.as_dict() == both.as_dict()


def test_custom_notes_must_declare_their_kind(by_request, tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "house_rules.md").write_text("---\nkind: rule\nversion: 7.2\ntitle: 赛事补充规则\n---\n# 切换限制\n每回合切换角色不限次数。\n",
                                          encoding="utf-8")
    (notes / "my_ideas.md").write_text("---\nkind: strategy\n---\n# 切人心得\n残血角色尽量不要留在出战位。\n# 骰子\n万能骰留到最后。\n",
                                       encoding="utf-8")
    (notes / "unlabelled.md").write_text("# 随手记\n不知道是规则还是经验。\n", encoding="utf-8")
    chunks, warnings = load_custom([str(notes), str(tmp_path / "missing")])
    assert sorted(c.kind for c in chunks) == ["custom_rule", "custom_strategy", "custom_strategy"]
    assert any("unlabelled.md" in w and "refused" in w for w in warnings)
    assert any("my_ideas.md" in w and "version" in w for w in warnings)
    assert any("missing" in w for w in warnings)

    selector = KnowledgeSelector(KnowledgeProfile(name="c", custom=(str(notes),), max_custom=3))
    pack = selector.select(by_request["action"].context, query="切换 出战 角色")
    kinds = {item.kind for item in pack.items}
    assert kinds == {"custom_rule", "custom_strategy"} and "随手记" not in pack.text
    assert pack.text.index("【自定义资料·规则】") < pack.text.index("【自定义资料·策略（未经验证）】")
    assert any(item.trust.endswith("未标版本") for item in pack.items if item.kind == "custom_strategy")
    assert selector.summary()["custom_chunks"] == 3


def test_expert_examples_and_profile_files(by_request, tmp_path):
    record = DecisionSupervision(
        deck=DECK, opponent=OPPONENT, seed=2, side=0, step_index=9, ordinal=9, round_number=2, request_type="action",
        options=(OptionRef(0, "action_use_skill", ["s"], "[0] use skill 流天射术"), OptionRef(1, "action_declare_end", ["e"], "[1] declare end")),
        expert_index=0, expert_policy=f"expert:{DECK}", outcome=1.0, text="round=2 my dice=...",
        provenance=Provenance(source="genshin-gitcg/evidence", version="train.evidence/1"))
    other = dataclasses.replace(record, request_type="reroll_dice", step_index=3)
    sup = tmp_path / "sup.jsonl"
    write_supervision(sup, [record, other])
    pack = KnowledgeSelector(KnowledgeProfile(name="ex", expert_examples=(str(sup),))).select(by_request["action"].context)
    assert [item.kind for item in pack.items] == ["expert_example"]          # only the same request type
    assert "专家选择" in pack.text and "行为记录，不保证最优" in pack.text and pack.items[0].trust == "expert_action"

    config = tmp_path / "knowledge.toml"
    config.write_text('[profiles.mine]\nrules = true\nstrategy = true\nstrategy_docs = ["S04"]\nmax_chars = 999\n', encoding="utf-8")
    profiles = load_knowledge_profiles([config])
    assert profiles["mine"].strategy_docs == ("S04",) and profiles["mine"].max_chars == 999 and "none" in profiles
    with pytest.raises(ValueError):
        profile_from_mapping("bad", {"rulez": True})
    # a missing knowledge base is reported, not fatal
    lost = KnowledgeSelector(KnowledgeProfile(name="lost", rules=True, kb_root=str(tmp_path / "nowhere")))
    pack = lost.select(by_request["action"].context)
    assert pack.items == [] and any("unavailable" in w for w in pack.warnings)


# --------------------------------------------------------------------------- #
# the LLM player
# --------------------------------------------------------------------------- #
class _Scripted:
    """A client that replies from a list and records what it was sent."""

    available = True

    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def complete(self, messages, **kwargs):
        self.sent.append(list(messages))
        reply = self.replies.pop(0) if self.replies else '{"choice": 0}'
        if isinstance(reply, ChatResult):
            return reply
        return ChatResult(reply, attempts=1, prompt_tokens=100, completion_tokens=10, latency_seconds=0.25, cost=0.001)


class _First:
    name = "first"

    def choose(self, built):
        return int(built.context.legal_low_level_codes[0])


def test_prompt_is_built_from_the_view_only(by_request, describer):
    for request, built in by_request.items():
        messages, protocol, listed = build_messages(built.context, describer)
        blind, _, _ = build_messages(dataclasses.replace(built.context, full_state=None), describer)
        assert messages == blind
        assert protocol == {"reroll_dice": "reroll_dice", "switch_hands": "switch_hands"}.get(request, "index")
        user = messages[1]["content"]
        assert "对方" in user and "不可见" in user and "回复格式" in user
        assert messages[0]["role"] == "system" and "合法选项" in messages[0]["content"]
    action = by_request["action"]
    messages, _, listed = build_messages(action.context, describer, max_options=3)
    assert listed == 3 and "仅列出前 3 个" in messages[1]["content"]
    with_knowledge, _, _ = build_messages(action.context, describer, knowledge_text="【规则事实】x")
    assert "规则事实与策略观点已分开标注" in with_knowledge[1]["content"]
    # reply=reason_first (D32): the justification comes before the choice; replies parse the same
    first, _, _ = build_messages(action.context, describer, reply="reason_first")
    tail = first[1]["content"].rsplit("回复格式", 1)[1]
    assert tail.index('"reason"') < tail.index('"choice"')
    listed, _, _ = build_messages(action.context, describer, reply="checklist")
    tail = listed[1]["content"].rsplit("回复格式", 1)[1]
    assert "对方是否已宣布回合结束" in tail and tail.index('"reason"') < tail.index('"choice"')
    plain_tail = messages[1]["content"].rsplit("回复格式", 1)[1]
    assert plain_tail.index('"choice"') < plain_tail.index('"reason"')


def test_replies_are_validated_against_the_legal_options(by_request):
    action = by_request["action"].context
    n = len(action.legal_low_level_specs)
    assert parse_reply(action, "index", n, '{"choice": 2, "reason": "r"}') == (2, "r", None)
    assert parse_reply(action, "index", n, '```json\n{"choice": "1"}\n```')[0] == 1
    assert parse_reply(action, "index", n, f'{{"choice": {n}}}')[2] == "choice_out_of_range"
    assert parse_reply(action, "index", n, '{"choice": -1}')[2] == "choice_out_of_range"
    assert parse_reply(action, "index", n, "I would attack")[2] == "unparseable"
    assert parse_reply(action, "index", n, '{"reason": "x"}')[2] == "no_choice"
    reroll = by_request["reroll_dice"].context
    index, _, error = parse_reply(reroll, "reroll_dice", 8, '{"reroll": [0, 2]}')
    assert error is None and index == find_mask_option(reroll, [0, 2])
    assert parse_reply(reroll, "reroll_dice", 8, '{"reroll": [42]}')[2] == "positions_out_of_range"
    assert parse_reply(reroll, "reroll_dice", 8, '{"choice": 0}')[2] == "no_reroll"
    swap = by_request["switch_hands"].context
    assert parse_reply(swap, "switch_hands", 5, '{"swap": []}')[0] == find_mask_option(swap, [])


def test_player_always_returns_a_legal_action_and_traces_why(by_request):
    built = by_request["action"]
    codes = [int(c) for c in built.context.legal_low_level_codes]
    # a usable answer is played
    client = _Scripted(['{"choice": 2, "reason": "压血线"}'])
    policy = LLMPolicy(client, _First())
    assert policy.choose(built) == codes[2]
    trace = policy.traces[-1]
    assert (trace.source, trace.llm_index, trace.reason, trace.calls) == ("llm", 2, "压血线", 1)
    assert trace.latency_seconds == 0.25 and trace.prompt_tokens == 100 and trace.cost == 0.001 and trace.final_text
    # an unusable answer is re-asked once, with the reason, then falls back
    client = _Scripted(["attack!", '{"choice": 999}'])
    policy = LLMPolicy(client, _First())
    assert policy.choose(built) == codes[0]
    trace = policy.traces[-1]
    assert (trace.source, trace.error, trace.calls) == ("fallback", "choice_out_of_range", 2)
    assert "无法使用（unparseable）" in client.sent[1][-1]["content"] and trace.cost == 0.002
    # ... and a corrected second answer is accepted
    policy = LLMPolicy(_Scripted(["oops", '{"choice": 1}']), _First())
    assert policy.choose(built) == codes[1] and policy.traces[-1].source == "llm"
    # an API failure does not burn a second call
    client = _Scripted([ChatResult(None, error="rate_limit", attempts=3)])
    policy = LLMPolicy(client, _First())
    assert policy.choose(built) == codes[0] and policy.traces[-1].error == "api:rate_limit" and len(client.sent) == 1
    # per-game budget, then fallback without calling
    client = _Scripted(['{"choice": 1}'] * 5)
    policy = LLMPolicy(client, _First(), config=LLMPolicyConfig(budget_per_game=1))
    assert [policy.choose(built), policy.choose(built)] == [codes[1], codes[0]]
    assert policy.traces[-1].error == "budget" and len(client.sent) == 1
    # request types can be left to the base policy
    policy = LLMPolicy(_Scripted([]), _First(), config=LLMPolicyConfig(request_types=("reroll_dice",)))
    assert policy.choose(built) == codes[0] and policy.traces[-1].error == "request_type_not_enabled"
    # a broken fallback still yields a legal code
    class Broken:
        def choose(self, built):
            raise RuntimeError("boom")

    assert LLMPolicy(_Scripted(["nope", "nope"]), Broken()).choose(built) in codes
    summary = LLMPolicy(_Scripted(['{"choice": 0}']), _First())
    summary.choose(built)
    assert summary.summary()["llm_rate"] == 1.0


def test_knowledge_reaches_the_prompt_and_the_trace(by_request, tmp_path):
    kb = _fixture_kb(tmp_path / "kb")
    built = by_request["action"]
    plain_client, kb_client = _Scripted(['{"choice": 0}']), _Scripted(['{"choice": 0}'])
    LLMPolicy(plain_client, _First()).choose(built)
    selector = KnowledgeSelector(KnowledgeProfile(name="rs", rules=True, strategy=True), kb=kb)
    policy = LLMPolicy(kb_client, _First(), selector=selector)
    policy.choose(built)
    plain, augmented = plain_client.sent[0][1]["content"], kb_client.sent[0][1]["content"]
    assert "【规则事实】" not in plain and "【规则事实】" in augmented and "【策略观点（未经验证）】" in augmented
    assert len(augmented) > len(plain)
    knowledge = policy.traces[-1].knowledge
    assert knowledge["profile"] == "rs" and knowledge["kb_version"] == "3.1"
    assert {i["id"] for i in knowledge["items"]} >= {"R03 §1", "S04-P1"}
    assert all(i["source"] == "GITCG_KB" and i["version"] == "3.1" for i in knowledge["items"])
    # the two configurations are distinguishable after the fact
    assert policy.traces[-1].prompt_chars == sum(len(m["content"]) for m in kb_client.sent[0])
    bare = LLMPolicy(_Scripted(['{"choice": 0}']), _First())
    bare.choose(built)
    assert bare.traces[-1].prompt_sha != policy.traces[-1].prompt_sha and bare.traces[-1].knowledge == {}


def test_discussion_uses_the_same_view_and_knowledge(by_request, tmp_path):
    kb = _fixture_kb(tmp_path / "kb")
    client = _Scripted(["先切人更稳。"])
    selector = KnowledgeSelector(KnowledgeProfile(name="r", rules=True), kb=kb)
    result, pack = discuss(client, by_request["action"], "先切人还是先打牌？", selector=selector,
                           history=[{"role": "user", "content": "上一问"}, {"role": "assistant", "content": "上一答"}])
    assert result.text == "先切人更稳。" and pack["profile"] == "r"
    sent = client.sent[0]
    assert [m["role"] for m in sent] == ["system", "user", "user", "assistant", "user"]
    assert "合法选项" in sent[1]["content"] and "【规则事实】" in sent[1]["content"] and "不可见" in sent[1]["content"]
    assert sent[-1]["content"] == "先切人还是先打牌？"


def test_spec_strings():
    assert parse_llm_spec("deepseek-chat#kb=rules,fallback=expert:x,budget=9") == (
        "deepseek-chat", {"kb": "rules", "fallback": "expert:x", "budget": "9"})
    assert parse_llm_spec("mock") == ("mock", {})
    with pytest.raises(KeyError):
        parse_llm_spec("mock#oops")
    policy = build_policy("llm:mock:last#fallback=legal_random,budget=3,model=first", seed=1, role="p0")
    assert policy.config.budget_per_game == 3 and policy.client.profile.model == "first" and policy.selector is None
    assert policy.name == "llm:mock:last"
    reasoned = build_policy("llm:mock:last#reply=reason_first", seed=1, role="p0")
    assert reasoned.config.reply == "reason_first" and reasoned.name == "llm:mock:last+reason_first"
    assert reasoned.config.as_dict()["reply"] == "reason_first" and "reply" not in policy.config.as_dict()
    with pytest.raises(KeyError):
        build_policy("llm:mock#reply=sideways", seed=1, role="p0")
    checklist = build_policy("llm:mock#reply=checklist", seed=1, role="p0")
    assert checklist.name == "llm:mock+checklist" and checklist.config.as_dict()["reply"] == "checklist"
    with pytest.raises(Exception):
        build_policy("llm:no-such-profile", seed=1, role="p0")
    with pytest.raises(KeyError):
        build_policy("llm:mock#kb=no-such-knowledge", seed=1, role="p0")
    assist = build_policy(f"llm-assist:mock#base=expert:{DECK},budget=2", seed=1, role="p0")
    assert assist.config.budget_per_game == 2


@pytest.mark.parametrize("spec,expect_llm", [("llm:mock:random", True), ("llm:mock:invalid", False),
                                              ("llm:mock:out_of_range", False), ("llm:mock:error", False)])
def test_full_games_stay_legal_whatever_the_model_says(spec, expect_llm):
    policy = build_policy(spec, seed=3, role="p0")
    record = run_match(deck_spec(DECK), deck_spec(OPPONENT), policy, expert_policy(OPPONENT), seed=3)
    assert record.error is None and record.winner in (0, 1) and record.fallbacks0 == 0   # the engine never had to step in
    summary = policy.summary()
    assert summary["decisions"] == record.decisions0
    assert (summary["llm_rate"] == 1.0) is expect_llm
    if not expect_llm:
        assert summary["by_source"].get("llm", 0) == 0 and summary["errors"]
        # an API failure costs one call per decision, an unusable reply two (one re-ask)
        decided = summary["by_source"]["fallback"]
        assert summary["calls"] == decided * (1 if spec.endswith("error") else 2)
