"""Model-agnostic rendering of a decision: the acting player's view and its legal options.

One place turns a ``DecisionContext`` into (a) a JSON-safe structure and (b) text,
for every consumer that is not a tensor encoder: LLM prompts (``agents.llm_policy``),
the web lab (``lab.server``), replays and exports.

Information boundary: everything here is derived from ``context.player_view`` (the
masked ``notification.state`` of the acting seat) and the legal option specs. The
opponent's hand is rendered as a count, its dice as the public count, both piles as
counts. ``context.full_state`` is never read.

Names, costs and card text come from the cached assets payload
(``agents.scripted.assets``); an id that is not in the payload renders as ``#<id>``
rather than failing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping, Sequence

from .schema import DecisionContext, DecisionType, OptionKind, public_dice_count

DICE_NAMES = {1: "冰", 2: "水", 3: "火", 4: "雷", 5: "风", 6: "岩", 7: "草", 8: "万能"}
# Cost requirement codes used by the action adapter (``required_cost``).
COST_NAMES = {0: "任意", 1: "冰", 2: "水", 3: "火", 4: "雷", 5: "风", 6: "岩", 7: "草",
              8: "同色", 9: "充能", 10: "秘传"}
_ASSET_COST_NAMES = {
    "GCG_COST_DICE_VOID": "任意", "GCG_COST_DICE_SAME": "同色", "GCG_COST_ENERGY": "充能",
    "GCG_COST_LEGEND": "秘传", "GCG_COST_DICE_CRYO": "冰", "GCG_COST_DICE_HYDRO": "水",
    "GCG_COST_DICE_PYRO": "火", "GCG_COST_DICE_ELECTRO": "雷", "GCG_COST_DICE_ANEMO": "风",
    "GCG_COST_DICE_GEO": "岩", "GCG_COST_DICE_DENDRO": "草",
}
AURA_NAMES = {0: "无", 1: "冰", 2: "水", 3: "火", 4: "雷", 7: "草", 113: "冰+草"}
PHASE_NAMES = {"init_hands": "起手换牌", "init_actives": "选择出战", "roll": "掷骰",
               "action": "行动", "end": "结束", "game_end": "对局结束"}
REQUEST_NAMES = {"action": "行动", "choose_active": "选择出战角色", "reroll_dice": "重掷骰子",
                 "switch_hands": "替换起始手牌", "select_card": "挑选卡牌"}
_SKILL_TYPES = {"GCG_SKILL_TAG_A": "普通攻击", "GCG_SKILL_TAG_E": "元素战技",
                "GCG_SKILL_TAG_Q": "元素爆发", "GCG_SKILL_TAG_PASSIVE": "被动", "GCG_SKILL_TAG_VEHICLE": "特技"}
_ENTITY_TYPES = {"GCG_CARD_EVENT": "事件", "GCG_CARD_MODIFY": "装备", "GCG_CARD_ASSIST": "支援",
                 "GCG_CARD_SUMMON": "召唤物", "GCG_CARD_STATE": "状态", "GCG_CARD_ONSTAGE": "出战状态",
                 "GCG_CARD_ATTACHMENT": "附着"}
_SHOWN_VARIABLES = ("usage", "usagePerRound", "duration", "shield", "hintText")


@dataclass(frozen=True)
class AssetEntry:
    id: int
    name: str
    kind: str = ""             # 角色 / 技能类型 / 事件 / 装备 / 支援 / 召唤物 / 状态 ...
    cost: str = ""
    description: str = ""
    element: str = ""          # characters only: 冰 / 水 / 火 / 雷 / 风 / 岩 / 草 (from the asset tags)


class AssetText:
    """id -> display name / cost / rules text, from the cached assets payload."""

    def __init__(self, entries: Mapping[int, AssetEntry] | None = None) -> None:
        self.entries = dict(entries or {})

    @staticmethod
    def _cost(raw: Any) -> str:
        parts = []
        for item in raw or ():
            count = int(item.get("count", 0) or 0)
            if count <= 0:
                continue
            kind = str(item.get("type", ""))
            parts.append(f"{count}{_ASSET_COST_NAMES.get(kind, kind.replace('GCG_COST_', ''))}")
        return "+".join(parts) if parts else "0"

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "AssetText":
        entries: dict[int, AssetEntry] = {}
        for item in payload.get("data", ()):
            definition_id = item.get("id")
            if not isinstance(definition_id, int) or definition_id < 0:
                continue
            name = str(item.get("name") or item.get("englishName") or definition_id)
            if isinstance(item.get("skills"), list) and "hp" in item:
                element = next((_ELEMENT_TAGS[t] for t in item.get("tags") or () if t in _ELEMENT_TAGS), "")
                entries[definition_id] = AssetEntry(definition_id, name, "角色", element=element)
                for skill in item["skills"]:
                    if isinstance(skill.get("id"), int):
                        entries[int(skill["id"])] = AssetEntry(
                            int(skill["id"]), str(skill.get("name", skill["id"])),
                            _SKILL_TYPES.get(str(skill.get("type", "")), "技能"),
                            cls._cost(skill.get("playCost")), str(skill.get("description") or ""),
                        )
                continue
            raw_type = str(item.get("type", ""))
            kind = _SKILL_TYPES.get(raw_type) or _ENTITY_TYPES.get(raw_type, "")
            if definition_id in entries and not kind:
                continue
            entries[definition_id] = AssetEntry(
                definition_id, name, kind, cls._cost(item.get("playCost")),
                str(item.get("description") or ""),
            )
        return cls(entries)

    @classmethod
    def load(cls) -> "AssetText":
        return _cached_assets()

    def get(self, definition_id: int) -> AssetEntry:
        entry = self.entries.get(int(definition_id))
        return entry if entry is not None else AssetEntry(int(definition_id), f"#{int(definition_id)}")

    def name(self, definition_id: int) -> str:
        return self.get(definition_id).name


_ELEMENT_TAGS = {"GCG_TAG_ELEMENT_CRYO": "冰", "GCG_TAG_ELEMENT_HYDRO": "水", "GCG_TAG_ELEMENT_PYRO": "火",
                 "GCG_TAG_ELEMENT_ELECTRO": "雷", "GCG_TAG_ELEMENT_ANEMO": "风", "GCG_TAG_ELEMENT_GEO": "岩",
                 "GCG_TAG_ELEMENT_DENDRO": "草"}


@lru_cache(maxsize=1)
def _cached_assets() -> AssetText:
    from agents.scripted.assets import _cache_path

    path = _cache_path()
    if not path.exists():
        return AssetText()
    return AssetText.from_payload(json.loads(path.read_text(encoding="utf-8")))


def _one_line(text: str) -> str:
    return " ".join(part.strip() for part in str(text).splitlines() if part.strip())


def _dice(dice: Sequence[int]) -> list[str]:
    return [DICE_NAMES.get(int(d), f"骰#{int(d)}") for d in dice]


def _variables(variables: Mapping[str, Any]) -> dict[str, int]:
    out = {}
    for key in _SHOWN_VARIABLES:
        if key in variables and isinstance(variables[key], (int, float)) and key != "hintText":
            out[key] = int(variables[key])
    return out


class DecisionDescriber:
    """Structured + text description of decisions for one acting seat."""

    def __init__(self, assets: AssetText | None = None, *, elements: bool = False, facts: bool = False,
                 cards: bool = False) -> None:
        self.assets = assets if assets is not None else AssetText.load()
        # D35: name each character's element in the state text (opt-in: the default text is unchanged,
        # so earlier runs stay comparable). D34 train games showed the model guessing elements at reroll.
        self.elements = elements
        # D37: derived facts (skill previews, public thresholds) before the options; see reps.facts.
        self.facts = facts
        # D37: per-game character cards of both sides first in the prompt; see reps.dossier.
        self.cards = cards

    def cards_text(self, context: DecisionContext) -> str:
        from .dossier import dossier_text

        return dossier_text(context, self.assets)

    def facts_text(self, context: DecisionContext, listed: int) -> str:
        from .facts import facts_text

        return facts_text(context, self.assets, listed)

    # -- state ---------------------------------------------------------------- #
    def _entity(self, entity: Any, *, with_text: bool = True) -> dict[str, Any]:
        entry = self.assets.get(int(entity.definition_id))
        out: dict[str, Any] = {"id": int(entity.definition_id), "name": entry.name, "kind": entry.kind}
        variables = _variables(getattr(entity, "variables", {}) or {})
        if variables:
            out["vars"] = variables
        if with_text and entry.description:
            out["text"] = entry.description
        return out

    def _character(self, character: Any) -> dict[str, Any]:
        entry = self.assets.get(int(character.definition_id))
        return {
            "id": int(character.definition_id), "name": entry.name, "element": entry.element,
            "hp": int(character.health), "max_hp": int(character.max_health),
            "energy": int(character.energy), "max_energy": int(character.max_energy),
            "aura": AURA_NAMES.get(int(character.aura), f"附着#{int(character.aura)}"),
            "active": bool(character.is_active), "defeated": bool(character.defeated),
            "entities": [self._entity(e) for e in character.entities],
        }

    def _side(self, player: Any, *, own: bool) -> dict[str, Any]:
        side: dict[str, Any] = {
            "characters": [self._character(c) for c in player.characters],
            "combat_statuses": [self._entity(e) for e in player.combat_statuses],
            "summons": [self._entity(e) for e in player.summons],
            "supports": [self._entity(e) for e in player.supports],
            "pile_count": len(player.pile_cards),
            "declared_end": bool(player.declared_end),
            "legend_used": bool(player.legend_used),
        }
        if own:
            side["dice"] = _dice(player.dice)
            hand = []
            for card in player.hand_cards:
                entry = self.assets.get(int(card.definition_id))
                item = {"id": int(card.definition_id), "name": entry.name, "kind": entry.kind,
                        "cost": entry.cost, "text": entry.description}
                attachments = [self.assets.name(int(a.definition_id)) for a in getattr(card, "attachments", ())]
                if attachments:
                    item["attachments"] = attachments
                hand.append(item)
            side["hand"] = hand
        else:
            # Hidden zones of the opponent: counts only.
            side["hand_count"] = len(player.hand_cards)
            side["dice_count"] = int(public_dice_count(player))
        return side

    def view(self, view: Any, seat: int) -> dict[str, Any]:
        """Seat ``seat``'s masked view (a ``notification.state`` snapshot) as a structure."""
        seat = int(seat)
        return {
            "seat": seat,
            "round": int(view.round_number),
            "phase": PHASE_NAMES.get(str(view.phase), str(view.phase)),
            "my_turn": int(view.current_turn) == seat,
            # ``view.winner`` is only meaningful once the game is over (the snapshot
            # reports 0 for "no winner yet"; see reports/review/2026-11_benchmark.md).
            "winner": view.winner if str(view.phase) in ("game_end", "PHASE_TYPE_GAME_END") else None,
            "me": self._side(view.players[seat], own=True),
            "opponent": self._side(view.players[1 - seat], own=False),
        }

    def state(self, context: DecisionContext) -> dict[str, Any]:
        if context.player_view is None:
            raise ValueError("decision context has no player_view")
        state = self.view(context.player_view, int(context.acting_player))
        state["request"] = str(context.request_type.value)
        return state

    # -- options -------------------------------------------------------------- #
    def _target(self, context: DecisionContext, slot: Any) -> str:
        view = context.player_view
        seat = int(context.acting_player)
        owner = seat if str(slot.owner) == "self" else 1 - seat
        who = "我方" if owner == seat else "对方"
        player = view.players[owner] if view is not None else None
        zone, index = str(slot.zone), int(slot.index)
        try:
            if zone == "character":
                return f"{who}角色 {self.assets.name(player.characters[index].definition_id)}"
            if zone == "summon":
                return f"{who}召唤物 {self.assets.name(player.summons[index].definition_id)}"
            if zone == "support":
                return f"{who}支援 {self.assets.name(player.supports[index].definition_id)}"
            if zone in ("combat_status", "combatStatus"):
                return f"{who}出战状态 {self.assets.name(player.combat_statuses[index].definition_id)}"
        except (AttributeError, IndexError, TypeError):
            pass
        return f"{who}{zone}[{index}]"

    def option(self, context: DecisionContext, spec: Any, index: int) -> dict[str, Any]:
        kind = spec.kind
        view = context.player_view
        seat = int(context.acting_player)
        me = view.players[seat] if view is not None else None
        out: dict[str, Any] = {"index": int(index), "code": int(spec.action_code), "kind": str(kind.value)}
        subject = int(spec.subject_definition_id or 0)
        if subject:
            out["subject_id"] = subject
        targets = [self._target(context, slot) for slot in spec.target_slots]
        if targets:
            out["targets"] = targets
        paid = _dice(spec.used_dice)
        if kind in (OptionKind.ACTION_USE_SKILL, OptionKind.ACTION_PLAY_CARD,
                    OptionKind.ACTION_SWITCH_ACTIVE, OptionKind.ACTION_ELEMENTAL_TUNING):
            out["pay"] = paid
            metadata = getattr(spec, "metadata", {}) or {}
            if "is_fast" in metadata:
                out["fast"] = bool(metadata["is_fast"])
        pay = f"，支付 {''.join(paid) if paid else '无'}" if "pay" in out else ""
        speed = "" if "fast" not in out else ("（快速行动）" if out["fast"] else "（战斗行动）")
        target_text = f" → {'、'.join(targets)}" if targets else ""

        if kind == OptionKind.ACTION_USE_SKILL:
            entry = self.assets.get(subject)
            text = f"使用技能【{entry.name}】{entry.kind and '(' + entry.kind + ')'}{target_text}{pay}{speed}"
        elif kind == OptionKind.ACTION_PLAY_CARD:
            text = f"打出手牌【{self.assets.name(subject)}】{target_text}{pay}{speed}"
        elif kind == OptionKind.ACTION_SWITCH_ACTIVE:
            name = self.assets.name(subject) if subject else (targets[0] if targets else "?")
            text = f"切换出战角色为【{name}】{pay}{speed}"
        elif kind == OptionKind.ACTION_ELEMENTAL_TUNING:
            target_die = DICE_NAMES.get(int(getattr(spec, "target_dice", 0) or 0), "")
            text = f"元素调和：弃置手牌【{self.assets.name(subject)}】，将 1 个{''.join(paid) or '骰子'}转为{target_die or '出战角色元素'}骰{speed}"
        elif kind == OptionKind.ACTION_DECLARE_END:
            text = "宣布回合结束"
        elif kind == OptionKind.CHOOSE_ACTIVE:
            out["slot"] = int(spec.choose_active_slot)
            text = f"选择【{self.assets.name(subject)}】出战"
        elif kind == OptionKind.SELECT_CARD:
            card = int(spec.select_card_definition_id or subject)
            out["subject_id"] = card
            text = f"挑选【{self.assets.name(card)}】"
        elif kind == OptionKind.REROLL_DICE:
            mask = int(spec.reroll_dice_mask)
            out["mask"] = mask
            dice = list(me.dice) if me is not None else []
            picked = [i for i in range(len(dice)) if mask >> i & 1]
            out["positions"] = picked
            text = "不重掷" if not picked else "重掷 " + "".join(_dice(dice[i] for i in picked))
        elif kind == OptionKind.SWITCH_HANDS:
            mask = int(spec.switch_hand_slot_mask)
            out["mask"] = mask
            hand = list(me.hand_cards) if me is not None else []
            picked = [i for i in range(len(hand)) if mask >> i & 1]
            out["positions"] = picked
            text = "不替换" if not picked else "替换 " + "、".join(
                self.assets.name(hand[i].definition_id) for i in picked)
        else:
            text = str(getattr(spec, "label", kind.value))
        out["text"] = text
        out["public_text"] = self._public_text(kind, out, subject, target_text)
        return out

    def _public_text(self, kind: OptionKind, option: Mapping[str, Any], subject: int, target_text: str) -> str:
        """What the *opponent* learns from this action (no hand identities, no dice faces)."""
        if kind == OptionKind.ACTION_USE_SKILL:
            return f"使用技能【{self.assets.name(subject)}】{target_text}"
        if kind == OptionKind.ACTION_PLAY_CARD:
            return f"打出手牌【{self.assets.name(subject)}】{target_text}"
        if kind == OptionKind.ACTION_SWITCH_ACTIVE:
            return str(option["text"]).split("，支付")[0]
        if kind == OptionKind.ACTION_ELEMENTAL_TUNING:
            return "元素调和（弃置 1 张手牌）"
        if kind == OptionKind.ACTION_DECLARE_END:
            return "宣布回合结束"
        if kind == OptionKind.CHOOSE_ACTIVE:
            return str(option["text"])
        if kind == OptionKind.REROLL_DICE:
            return f"重掷 {len(option.get('positions', ()))} 个骰子"
        if kind == OptionKind.SWITCH_HANDS:
            return f"替换 {len(option.get('positions', ()))} 张起始手牌"
        if kind == OptionKind.SELECT_CARD:
            return "挑选了 1 张牌"
        return str(kind.value)

    def options(self, context: DecisionContext) -> list[dict[str, Any]]:
        return [self.option(context, spec, i) for i, spec in enumerate(context.legal_low_level_specs)]

    # -- text ----------------------------------------------------------------- #
    @staticmethod
    def _entity_text(entity: Mapping[str, Any], detail: bool) -> str:
        variables = entity.get("vars") or {}
        tail = "(" + ",".join(f"{k}={v}" for k, v in variables.items()) + ")" if variables else ""
        text = f"{entity['name']}{tail}"
        if detail and entity.get("text"):
            text += f"：{_one_line(entity['text'])}"
        return text

    def _side_text(self, side: Mapping[str, Any], label: str, *, own: bool, detail: bool) -> list[str]:
        lines = [f"【{label}】"]
        for i, c in enumerate(side["characters"]):
            flags = ("（出战）" if c["active"] else "") + ("（已倒下）" if c["defeated"] else "")
            name = f"{c['name']}［{c['element']}］" if self.elements and c.get("element") else c["name"]
            line = (f"  角色{i + 1} {name}{flags} 生命 {c['hp']}/{c['max_hp']} "
                    f"充能 {c['energy']}/{c['max_energy']} 附着 {c['aura']}")
            if c["entities"]:
                line += " | 装备/状态：" + "；".join(self._entity_text(e, False) for e in c["entities"])
            lines.append(line)
        for key, name in (("combat_statuses", "出战状态"), ("summons", "召唤物"), ("supports", "支援区")):
            if side[key]:
                lines.append(f"  {name}：" + "；".join(self._entity_text(e, detail) for e in side[key]))
        if own:
            dice = side["dice"]
            lines.append(f"  骰子（{len(dice)}）：{' '.join(dice) if dice else '无'}")
            lines.append(f"  手牌（{len(side['hand'])}）：")
            for i, card in enumerate(side["hand"]):
                extra = f" [附着:{'/'.join(card['attachments'])}]" if card.get("attachments") else ""
                text = f"：{_one_line(card['text'])}" if detail and card.get("text") else ""
                lines.append(f"    {i + 1}. {card['name']}（{card['kind'] or '牌'}，费用 {card['cost']}）{extra}{text}")
            lines.append(f"  牌库 {side['pile_count']} 张")
        else:
            lines.append(f"  手牌 {side['hand_count']} 张（不可见） 骰子 {side['dice_count']} 个（不可见） "
                         f"牌库 {side['pile_count']} 张")
        lines.append(f"  已宣布结束：{'是' if side['declared_end'] else '否'}  秘传牌已用：{'是' if side['legend_used'] else '否'}")
        return lines

    def state_text(self, context: DecisionContext, *, detail: bool = True) -> str:
        state = self.state(context)
        lines = [f"第 {state['round']} 回合，阶段：{state['phase']}，"
                 f"{'轮到我方行动' if state['my_turn'] else '当前行动方为对方'}，"
                 f"本次需要决定：{REQUEST_NAMES.get(state['request'], state['request'])}"]
        lines += self._side_text(state["me"], "我方", own=True, detail=detail)
        lines += self._side_text(state["opponent"], "对方", own=False, detail=detail)
        return "\n".join(lines)

    def options_text(self, context: DecisionContext, indices: Sequence[int] | None = None) -> str:
        options = self.options(context)
        chosen = options if indices is None else [options[i] for i in indices]
        return "\n".join(f"[{n}] {option['text']}" for n, option in enumerate(chosen))

    def active_skills_text(self, context: DecisionContext) -> str:
        """Rules text of the skills that appear among the legal options."""
        seen: dict[int, AssetEntry] = {}
        for spec in context.legal_low_level_specs:
            if spec.kind == OptionKind.ACTION_USE_SKILL and int(spec.subject_definition_id) not in seen:
                seen[int(spec.subject_definition_id)] = self.assets.get(int(spec.subject_definition_id))
        return "\n".join(f"  {e.name}（{e.kind}，费用 {e.cost}）：{_one_line(e.description)}" for e in seen.values())


def find_mask_option(context: DecisionContext, positions: Sequence[int]) -> int | None:
    """Index of the reroll / switch-hands option equivalent to choosing ``positions``.

    The adapter keeps one option per *multiset* of faces (reroll) or per id subset
    (switch hands), so the requested positions are matched by content.
    """
    view = context.player_view
    if view is None:
        return None
    me = view.players[int(context.acting_player)]
    picked = sorted({int(p) for p in positions})
    if context.request_type == DecisionType.REROLL_DICE:
        dice = list(me.dice)
        if any(p < 0 or p >= len(dice) for p in picked):
            return None
        want = sorted(int(dice[p]) for p in picked)
        for index, spec in enumerate(context.legal_low_level_specs):
            mask = int(spec.reroll_dice_mask)
            have = sorted(int(dice[i]) for i in range(len(dice)) if mask >> i & 1)
            if spec.kind == OptionKind.REROLL_DICE and have == want:
                return index
        return None
    if context.request_type == DecisionType.SWITCH_HANDS:
        hand = list(me.hand_cards)
        if any(p < 0 or p >= len(hand) for p in picked):
            return None
        want_mask = sum(1 << p for p in picked)
        want_defs = sorted(int(hand[p].definition_id) for p in picked)
        fallback = None
        for index, spec in enumerate(context.legal_low_level_specs):
            if spec.kind != OptionKind.SWITCH_HANDS:
                continue
            mask = int(spec.switch_hand_slot_mask)
            if mask == want_mask:
                return index
            have_defs = sorted(int(hand[i].definition_id) for i in range(len(hand)) if mask >> i & 1)
            if have_defs == want_defs and fallback is None:
                fallback = index
        return fallback
    return None
