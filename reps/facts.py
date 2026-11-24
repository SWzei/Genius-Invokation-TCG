"""Derived facts for the acting seat (D37, ``facts=1``): skill previews and public thresholds.

The engine attaches a *preview* to every action of an ``ActionRequest`` it sends to the
acting player (the same data the official client shows as its damage preview). We keep
only the parts of a **skill's** preview that are public consequences on characters:

* damage: target character, value, element, reaction, health before / after, defeated;
* heal: target, value;
* elemental application without damage: target, element, reaction.

Everything else in a preview (entities created or removed, variables, cards moved or
drawn, dice) is dropped at the source by :func:`sanitize_preview`, so hand cards, pile
order and random outcomes never reach the model. Card and switch previews are not kept
at all (cards can have random or draw effects).

On top of the previews, :func:`facts_text` adds facts computed from the seat's own view:
which options defeat the opponent's active character, the highest-damage skill option,
an opponent active character with full energy (can use its burst), own characters at
3 HP or less.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .schema import OptionKind

ELEMENT_OF_DAMAGE = {0: "物理", 1: "冰", 2: "水", 3: "火", 4: "雷", 5: "风", 6: "岩", 7: "草", 8: "穿透"}
HEAL = 9
REACTION_NAMES = {
    101: "融化", 102: "蒸发", 103: "超载", 104: "超导", 105: "感电", 106: "冻结",
    107: "扩散（冰）", 108: "扩散（水）", 109: "扩散（火）", 110: "扩散（雷）",
    111: "结晶（冰）", 112: "结晶（水）", 113: "结晶（火）", 114: "结晶（雷）",
    115: "燃烧", 116: "绽放", 117: "激化", 3001: "月感电", 3002: "月绽放",
}
AURA_ELEMENT = {1: "冰", 2: "水", 3: "火", 4: "雷", 7: "草"}


def sanitize_preview(action: Any) -> list[dict[str, int]]:
    """Public consequences on characters from one action's engine preview (skills only)."""
    if not action.HasField("use_skill"):
        return []
    out: list[dict[str, int]] = []
    for item in getattr(action, "preview", ()):
        which = item.WhichOneof("mutation")
        if which == "damage":
            d = item.damage
            out.append({"kind": "heal" if int(d.damage_type) == HEAL else "damage",
                        "target": int(d.target_id), "target_def": int(d.target_definition_id),
                        "value": int(d.value), "element": int(d.damage_type), "reaction": int(d.reaction_type),
                        "old_hp": int(d.old_health), "new_hp": int(d.new_health),
                        "defeated": int(bool(d.cause_defeated))})
        elif which == "apply_aura":
            a = item.apply_aura
            out.append({"kind": "aura", "target": int(a.target_id), "target_def": int(a.target_definition_id),
                        "element": int(a.element_type), "reaction": int(a.reaction_type)})
    return out


def _owner(view: Any, seat: int, entity_id: int) -> tuple[str, Any] | None:
    for who, label in ((seat, "我方"), (1 - seat, "对方")):
        for character in view.players[who].characters:
            if int(character.id) == int(entity_id):
                return label, character
    return None


def option_effects(context: Any, spec: Any) -> list[dict[str, Any]]:
    """The kept preview entries of one option, with the target resolved on the seat's view."""
    if spec.kind != OptionKind.ACTION_USE_SKILL:
        return []
    previews = (context.request_payload or {}).get("previews") or {}
    index = (getattr(spec, "metadata", {}) or {}).get("action_index")
    view, seat = context.player_view, int(context.acting_player)
    out = []
    for entry in previews.get(index, ()) if index is not None else ():
        found = _owner(view, seat, entry["target"])
        if found is None:
            continue
        side, character = found
        out.append({**entry, "side": side, "active": bool(character.is_active), "character": character})
    return out


def _effect_text(entry: Mapping[str, Any], name: str) -> str:
    who = f"{entry['side']}{name}"
    if entry["kind"] == "heal":
        return f"治疗{who} {entry['value']} 点"
    reaction = REACTION_NAMES.get(entry["reaction"])
    if entry["kind"] == "aura":
        element = ELEMENT_OF_DAMAGE.get(entry["element"], "?")
        return f"{who}附着{element}" + (f"（{reaction}）" if reaction else "")
    element = ELEMENT_OF_DAMAGE.get(entry["element"], "?")
    text = f"对{who} {entry['value']} 点{element}伤害" + (f"（{reaction}）" if reaction else "")
    text += f"，生命 {entry['old_hp']}→{entry['new_hp']}" + ("，击倒" if entry["defeated"] else "")
    return text


def facts_text(context: Any, assets: Any, listed: int) -> str:
    """The derived-facts block for an action decision (empty when there is nothing to say)."""
    view, seat = context.player_view, int(context.acting_player)
    if view is None:
        return ""
    lines: list[str] = []
    ko, best = [], None
    for i, spec in enumerate(context.legal_low_level_specs[:listed]):
        effects = option_effects(context, spec)
        if not effects:
            continue
        skill = assets.name(int(spec.subject_definition_id))
        parts = [_effect_text(e, assets.name(int(e["character"].definition_id))) for e in effects]
        lines.append(f"  [{i}] {skill}：" + "；".join(parts))
        if any(e["kind"] == "damage" and e["side"] == "对方" and e["active"] and e["defeated"] for e in effects):
            ko.append(i)
        dealt = sum(e["value"] for e in effects if e["kind"] == "damage" and e["side"] == "对方")
        if dealt and (best is None or dealt > best[1]):
            best = (i, dealt)
    out: list[str] = []
    if lines:
        out.append("技能预演（引擎按当前局面结算本方这一次技能；不含对方之后的回应）：")
        out += lines
        if ko:
            out.append("  能击倒对方出战角色的选项：" + "、".join(f"[{i}]" for i in ko))
        if best is not None:
            out.append(f"  对对方伤害最高的技能选项：[{best[0]}]（{best[1]} 点）")
    opponent = view.players[1 - seat]
    threat = [c for c in opponent.characters if c.is_active and not c.defeated
              and int(c.max_energy) > 0 and int(c.energy) >= int(c.max_energy)]
    low = [c for c in view.players[seat].characters if not c.defeated and int(c.health) <= 3]
    if threat or low:
        out.append("局面提示：")
        for c in threat:
            out.append(f"  对方出战角色 {assets.name(int(c.definition_id))} 充能已满，下次行动可使用元素爆发")
        for c in low:
            out.append(f"  我方 {assets.name(int(c.definition_id))} 生命只剩 {int(c.health)}")
    return "\n".join(out)


def skill_previews(request: Any) -> dict[int, list[dict[str, int]]]:
    """``{action_index: kept entries}`` for the skill actions of an ``ActionRequest``."""
    out: dict[int, list[dict[str, int]]] = {}
    for index, action in enumerate(getattr(request, "action", ())):
        kept = sanitize_preview(action)
        if kept:
            out[index] = kept
    return out


def summarize(entries: Sequence[Mapping[str, Any]]) -> list[tuple[int, int, int, int]]:
    """Comparable form of damage entries: (target, value, reaction, defeated)."""
    return sorted((e["target"], e["value"], e["reaction"], e["defeated"]) for e in entries if e["kind"] == "damage")
