"""Per-game character cards (D37, ``cards=1``): what every character on the board can do.

The state text names the six characters and shows the skills of the acting seat's
*active* character only. A card lists, for each character of both sides, its element,
max HP, max energy and every skill (type, cost, rules text), copied from the game's
card data (the same source as all other rules text in the prompt). Character identities
are public, so the card uses nothing hidden. The opponent's cards answer "what can the
other side do next" (e.g. what its burst does when its energy is full).

The text depends only on the six character definition ids, so it is identical for
every decision of a game and goes first in the prompt (cacheable prefix).
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Mapping

_SKILL_TYPES = {"GCG_SKILL_TAG_A": "普攻", "GCG_SKILL_TAG_E": "战技", "GCG_SKILL_TAG_Q": "爆发",
                "GCG_SKILL_TAG_PASSIVE": "被动", "GCG_SKILL_TAG_VEHICLE": "特技"}
MAX_TEXT = 90


@lru_cache(maxsize=1)
def _characters() -> dict[int, Mapping[str, Any]]:
    from agents.scripted.assets import _cache_path

    path = _cache_path()
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(item["id"]): item for item in payload.get("data", ())
            if isinstance(item.get("id"), int) and isinstance(item.get("skills"), list) and "hp" in item}


def _cost(raw: Any) -> str:
    from .describe import AssetText

    return AssetText._cost(raw)


def _short(text: str) -> str:
    text = " ".join(part.strip() for part in str(text).splitlines() if part.strip())
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "…"


def character_card(definition_id: int, assets: Any) -> str:
    item = _characters().get(int(definition_id))
    entry = assets.get(int(definition_id))
    if item is None:
        return f"  {entry.name}：（无卡牌数据）"
    head = f"  {entry.name}［{entry.element or '?'}］ 生命上限 {item.get('hp')} 充能上限 {item.get('maxEnergy')}"
    skills, seen = [], set()
    for skill in item["skills"]:
        kind = _SKILL_TYPES.get(str(skill.get("type", "")), "技能")
        key = (skill.get("name"), skill.get("description"))
        if (kind == "被动" and not skill.get("description")) or key in seen:
            continue
        seen.add(key)
        cost = "" if kind == "被动" else f"（{_cost(skill.get('playCost'))}）"
        skills.append(f"    {kind}【{skill.get('name')}】{cost}：{_short(skill.get('description') or '')}")
    return "\n".join([head, *skills])


def dossier_text(context: Any, assets: Any) -> str:
    view, seat = context.player_view, int(context.acting_player)
    if view is None:
        return ""
    lines = ["本局角色卡（卡牌数据，双方角色都是公开信息）："]
    for who, label in ((1 - seat, "对方"), (seat, "我方")):
        lines.append(f" {label}：")
        lines += [character_card(int(c.definition_id), assets) for c in view.players[who].characters]
    return "\n".join(lines)
