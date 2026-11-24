"""Knowledge-base adapter: rules / strategy units <-> decisions and legal actions.

Reads the external ``GITCG_KB`` (rules + strategy knowledge base; *not* vendored
into this repo) and exposes three things the rest of the pipeline can rely on:

1. :class:`KnowledgeBase` -- strategy units and rule sections with provenance
   (source, KB version, document, evidence classes, KB confidence label) and a
   plain keyword search;
2. **condition detectors** -- for the subset of strategy units whose
   applicability condition ``phi`` can be decided from the acting player's public
   view and legal options, a predicate over a ``DecisionContext``
   (:func:`matching_units`). They read ``context.player_view`` only, never
   ``full_state``;
3. :data:`RULE_REFS_BY_OPTION_KIND` -- which rule sections govern each kind of
   legal option, so a student (or a prompt) can be shown the relevant rule text.

What this is *not*: a detector says "this unit's stated condition holds here". It
does not say the unit's recommendation is correct, and nothing in this module
turns a recommendation into an action label. Units without a detector are simply
not annotated (see :func:`detector_coverage`).

Locating the KB: pass a path, or set ``GITCG_KB_DIR``; the expected layout is
``<root>/data/derived/{strategy_units,rule_sections}.jsonl`` (built by the KB's
``tools/build_index.py``).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .schema import DecisionContext, DecisionType, OptionKind, public_dice_count
from .strategy import Provenance, StrategyUnit

KB_ENV = "GITCG_KB_DIR"
KB_SOURCE = "GITCG_KB"


@dataclass(frozen=True)
class RuleSection:
    ref: str                 # e.g. "R03 §3"
    heading: str
    text: str
    evidence: tuple[str, ...]        # 官方 / 引擎 / 派生 / 待核 ...
    doc: str
    version_baseline: str
    provenance: Provenance


def _kb_version(root: Path) -> str:
    readme = root / "README.md"
    if readme.exists():
        match = re.search(r"^version:\s*(\S+)", readme.read_text(encoding="utf-8"), re.M)
        if match:
            return match.group(1)
    return ""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class KnowledgeBase:
    """Strategy units and rule sections of one KB release."""

    def __init__(self, units: Sequence[StrategyUnit], rules: Sequence[RuleSection],
                 *, root: str = "", version: str = "") -> None:
        self.units = {unit.id: unit for unit in units}
        self.rules = {rule.ref: rule for rule in rules}
        self.root = root
        self.version = version

    @classmethod
    def load(cls, root: str | Path | None = None) -> "KnowledgeBase":
        root = Path(root or os.environ.get(KB_ENV, ""))
        derived = root / "data" / "derived"
        units_path, rules_path = derived / "strategy_units.jsonl", derived / "rule_sections.jsonl"
        if not units_path.exists() or not rules_path.exists():
            raise FileNotFoundError(
                f"knowledge base not found under {str(root)!r}: expected {units_path} and "
                f"{rules_path} (pass the GITCG_KB root or set {KB_ENV})"
            )
        version = _kb_version(root)
        units = [
            StrategyUnit(
                id=str(row["id"]), concept=str(row.get("title", "")),
                condition=str(row.get("condition", "")),
                recommendation=str(row.get("recommendation", "")),
                evidence_types=tuple(str(v) for v in row.get("evidence_types", ())),
                confidence=str(row.get("confidence", "")), limits=str(row.get("limits", "")),
                doc=str(row.get("doc", "")), version_baseline=str(row.get("version_baseline", "")),
                provenance=Provenance(source=KB_SOURCE, version=version, generator="tools/build_index.py",
                                      extra={"doc": row.get("doc", ""), "unit": row["id"]}),
            )
            for row in _read_jsonl(units_path)
        ]
        rules = [
            RuleSection(
                ref=str(row["ref"]), heading=str(row.get("heading", "")), text=str(row.get("text", "")),
                evidence=tuple(str(v) for v in row.get("evidence", ())), doc=str(row.get("doc", "")),
                version_baseline=str(row.get("version_baseline", "")),
                provenance=Provenance(source=KB_SOURCE, version=version, generator="tools/build_index.py",
                                      extra={"doc": row.get("doc", ""), "ref": row["ref"]}),
            )
            for row in _read_jsonl(rules_path)
        ]
        return cls(units, rules, root=str(root), version=version)

    def unit(self, unit_id: str) -> StrategyUnit:
        return self.units[unit_id]

    def rule(self, ref: str) -> RuleSection:
        return self.rules[ref]

    def search(self, query: str, *, limit: int = 5) -> list[StrategyUnit | RuleSection]:
        """Rank units and rule sections by how many query terms they contain."""
        terms = [t for t in re.split(r"\s+", query.strip()) if t]
        scored: list[tuple[int, int, Any]] = []
        for order, item in enumerate([*self.units.values(), *self.rules.values()]):
            if isinstance(item, StrategyUnit):
                blob = " ".join((item.id, item.concept, item.condition, item.recommendation))
            else:
                blob = " ".join((item.ref, item.heading, item.text))
            hits = sum(blob.count(term) for term in terms)
            if hits:
                scored.append((-hits, order, item))
        if not scored and query.strip():
            # Chinese has no spaces: a natural question is one "term" and matches nothing.
            # Fall back to character-bigram BM25 over the same texts.
            from reps.kb_retrieval import BM25

            items = [*self.units.values(), *self.rules.values()]
            index = BM25((i, " ".join((item.id, item.concept, item.condition, item.recommendation))
                          if isinstance(item, StrategyUnit) else " ".join((item.ref, item.heading, item.heading, item.text)))
                         for i, item in enumerate(items))
            return [items[i] for i in index.rank(query, int(limit))]
        return [item for _hits, _order, item in sorted(scored, key=lambda row: row[:2])[: int(limit)]]

    def rules_for_option_kind(self, kind: str | OptionKind) -> list[RuleSection]:
        refs = RULE_REFS_BY_OPTION_KIND.get(str(getattr(kind, "value", kind)), ())
        return [self.rules[ref] for ref in refs if ref in self.rules]


# Which rule sections govern a legal option of each kind (KB rule refs).
RULE_REFS_BY_OPTION_KIND: dict[str, tuple[str, ...]] = {
    OptionKind.ACTION_USE_SKILL.value: ("R03 §1", "R04 §2", "R04 §3", "R05 §2"),
    OptionKind.ACTION_PLAY_CARD.value: ("R03 §1", "R08 §1", "R02 §4"),
    OptionKind.ACTION_SWITCH_ACTIVE.value: ("R03 §2", "R04 §3"),
    OptionKind.ACTION_ELEMENTAL_TUNING.value: ("R02 §5",),
    OptionKind.ACTION_DECLARE_END.value: ("R03 §3",),
    OptionKind.CHOOSE_ACTIVE.value: ("R01 §3", "R05 §4"),
    OptionKind.REROLL_DICE.value: ("R02 §1",),
    OptionKind.SWITCH_HANDS.value: ("R01 §3",),
    OptionKind.SELECT_CARD.value: ("R08 §1",),
}


# --------------------------------------------------------------------------- #
# condition detectors (public view + legal options only)
# --------------------------------------------------------------------------- #
Detector = Callable[[DecisionContext], bool]


def _me(context: DecisionContext):
    return context.player_view.players[context.acting_player]


def _opp(context: DecisionContext):
    return context.player_view.players[1 - context.acting_player]


def _kinds(context: DecisionContext) -> set[str]:
    return {spec.kind.value for spec in context.legal_low_level_specs}


def _is(context: DecisionContext, request: DecisionType) -> bool:
    return context.request_type == request


def _alive(player) -> int:
    return sum(1 for c in player.characters if not c.defeated)


def _own_defeated(context: DecisionContext) -> bool:
    return any(c.defeated for c in _me(context).characters)


_DETECTORS: dict[str, Detector] = {
    # 回合后期仍有骰子：对方已宣布结束，本方还有骰子且可以宣布结束
    "S01-P2": lambda c: _is(c, DecisionType.ACTION) and _opp(c).declared_end
    and len(_me(c).dice) > 0 and OptionKind.ACTION_DECLARE_END.value in _kinds(c),
    # 充能已满
    "S01-P7": lambda c: _is(c, DecisionType.ACTION)
    and any((not ch.defeated) and ch.max_energy > 0 and ch.energy >= ch.max_energy
            for ch in _me(c).characters),
    # 比较继续行动与宣布结束：双方都未结束，本方可以宣布结束
    "S02-P1": lambda c: _is(c, DecisionType.ACTION) and not _opp(c).declared_end
    and OptionKind.ACTION_DECLARE_END.value in _kinds(c) and len(_kinds(c)) > 1,
    # 对方未宣布结束（对方骰子数是公开信息）
    "S02-P5": lambda c: _is(c, DecisionType.ACTION) and not _opp(c).declared_end
    and public_dice_count(_opp(c)) > 0,
    # 考虑切人
    "S04-P1": lambda c: _is(c, DecisionType.ACTION)
    and OptionKind.ACTION_SWITCH_ACTIVE.value in _kinds(c),
    # 本方角色被击倒后的选人
    "S04-P4": lambda c: _is(c, DecisionType.CHOOSE_ACTIVE) and _own_defeated(c),
    # 开局换牌
    "S05-P1": lambda c: _is(c, DecisionType.SWITCH_HANDS),
    # 选择首发
    "S05-P3": lambda c: _is(c, DecisionType.CHOOSE_ACTIVE) and not _own_defeated(c)
    and int(c.player_view.round_number) <= 1,
    # 投掷阶段
    "S06-P1": lambda c: _is(c, DecisionType.REROLL_DICE),
    # 需要调和（存在调和选项）
    "S06-P4": lambda c: _is(c, DecisionType.ACTION)
    and OptionKind.ACTION_ELEMENTAL_TUNING.value in _kinds(c),
    # 手牌近 10
    "S07-P4": lambda c: len(_me(c).hand_cards) >= 9,
    # 区域接近 4 个
    "S09-P4": lambda c: _is(c, DecisionType.ACTION)
    and (len(_me(c).supports) >= 3 or len(_me(c).summons) >= 3),
    # 对方有召唤物
    "S10-P3": lambda c: _is(c, DecisionType.ACTION) and len(_opp(c).summons) > 0,
    # 残局：任一方只剩 1–2 名存活角色
    "S12-P4": lambda c: _is(c, DecisionType.ACTION)
    and min(_alive(_me(c)), _alive(_opp(c))) <= 2,
}


def _active(player):
    return next((c for c in player.characters if c.is_active and not c.defeated), None)


def _full_energy(player) -> bool:
    ch = _active(player)
    return ch is not None and ch.max_energy > 0 and ch.energy >= ch.max_energy


# Strategy-layer KB versions (D34, ``reps.kb_versions``) may add or re-condition units.
# Their detectors live here, keyed by the KB version string (the ``version:`` line of the
# built KB's README), so v1.0 -- and every other caller of ``matching_units`` (students,
# replay annotations, frequency tables) -- keeps exactly the original table.
_VERSION_DETECTORS: dict[str, dict[str, Detector]] = {
    "1.0-s1": {
        # 出战角色充能已满且还要打牌：先为爆发留骰
        "S01-P9": lambda c: _is(c, DecisionType.ACTION) and _full_energy(_me(c))
        and OptionKind.ACTION_PLAY_CARD.value in _kinds(c) and len(_me(c).dice) >= 3,
        # 对方未结束、回合中后段我方还剩 3–5 骰且有技能可用：别带骰空过
        "S02-P7": lambda c: _is(c, DecisionType.ACTION) and not _opp(c).declared_end
        and 3 <= len(_me(c).dice) <= 5 and OptionKind.ACTION_USE_SKILL.value in _kinds(c)
        and OptionKind.ACTION_DECLARE_END.value in _kinds(c),
        # 区域已满（4 个）且可以打牌（原条件 ">= 3" 在 v1.0 的训练对局里几乎总是触发）
        "S09-P4": lambda c: _is(c, DecisionType.ACTION) and OptionKind.ACTION_PLAY_CARD.value in _kinds(c)
        and (len(_me(c).supports) >= 4 or len(_me(c).summons) >= 4),
    },
}


# v1.0-s2 (D36 round 1): s1 minus S01-P9 (it made skipped bursts more frequent), plus S02-P8.
_VERSION_DETECTORS["1.0-s2"] = {
    "S02-P7": _VERSION_DETECTORS["1.0-s1"]["S02-P7"],
    "S09-P4": _VERSION_DETECTORS["1.0-s1"]["S09-P4"],
    # 攻击优先：行动阶段、技能可用、手上 >= 3 骰
    "S02-P8": lambda c: _is(c, DecisionType.ACTION) and OptionKind.ACTION_USE_SKILL.value in _kinds(c)
    and len(_me(c).dice) >= 3,
}


def detector_table(version: str = "") -> dict[str, Detector]:
    """The detectors in force for a KB version ("" / "1.0" = the original table)."""
    return {**_DETECTORS, **_VERSION_DETECTORS.get(str(version), {})}


def detector_ids() -> tuple[str, ...]:
    return tuple(sorted(_DETECTORS))


def matching_units(context: DecisionContext, *, allowed: Sequence[str] | None = None,
                   version: str = "") -> tuple[str, ...]:
    """Ids of strategy units whose formalised condition holds at this decision.

    Reads the acting player's ``player_view`` and the legal options only. A
    context without a player view yields no annotation. ``version``: the KB version
    whose detector table applies (D34); default = the original v1.0 table.
    """
    if context.player_view is None:
        return ()
    table = detector_table(version)
    ids = sorted(table) if allowed is None else [i for i in sorted(allowed) if i in table]
    out = []
    for unit_id in ids:
        try:
            if table[unit_id](context):
                out.append(unit_id)
        except (AttributeError, IndexError, TypeError):
            continue
    return tuple(out)


def detector_coverage(kb: KnowledgeBase) -> dict[str, Any]:
    """How much of the KB has a decidable condition (for reports; no claims)."""
    have = [i for i in kb.units if i in _DETECTORS]
    unknown = [i for i in _DETECTORS if i not in kb.units]
    return {"units": len(kb.units), "with_detector": len(have),
            "detector_ids": sorted(have), "detectors_without_unit": sorted(unknown)}


def render_units(kb: KnowledgeBase, unit_ids: Sequence[str]) -> str:
    """Compact text for prompts/reports: id, concept, condition, recommendation, KB labels."""
    lines = []
    for unit_id in unit_ids:
        unit = kb.units.get(unit_id)
        if unit is None:
            continue
        lines.append(
            f"[{unit.id}] {unit.concept} | 条件: {unit.condition} | 建议: {unit.recommendation} "
            f"| KB 证据: {'/'.join(unit.evidence_types)} 置信度: {unit.confidence}"
        )
    return "\n".join(lines)


def as_mapping(unit: StrategyUnit) -> Mapping[str, Any]:
    from dataclasses import asdict

    payload = asdict(unit)
    payload["provenance"] = unit.provenance.as_dict()
    return payload
