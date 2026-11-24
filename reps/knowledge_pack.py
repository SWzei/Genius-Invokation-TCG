"""Configurable knowledge for knowledge-augmented decisions.

A :class:`KnowledgeProfile` says *which* knowledge may be shown to a model; a
:class:`KnowledgeSelector` turns one decision into a :class:`KnowledgePack` -- the
text that goes into the prompt plus the list of items it was built from, so every
decision can be traced back to its sources.

Four source classes, kept apart in the pack and in the rendered text:

==================  ==========================================================
``rule``            rule sections of ``GITCG_KB`` (``reps.knowledge``). Facts.
                    Only sections whose evidence includes an allowed class
                    (default: 官方 / 引擎) are eligible; a section that also
                    carries 待核 is labelled as containing unverified parts.
``strategy``        strategy units of ``GITCG_KB``. **Opinions**: rendered under
                    an explicit "unverified" heading with the KB's own
                    confidence label, never mixed into the rules block.
``expert_example``  decisions of the scripted experts from supervision files
                    (``reps.strategy``): what an expert *did* in a similar spot.
                    Behaviour, not proof that the move is best.
``custom``          the user's own notes. Each file must declare ``kind: rule``
                    or ``kind: strategy`` in its front matter; a file that does
                    not is refused, so nothing enters a prompt unclassified.
==================  ==========================================================

Information boundary: selection reads the acting player's ``player_view`` and the
legal options only (through ``reps.knowledge.matching_units`` and
``reps.describe``). Expert examples are stored from the acting player's view in
the first place.

Version consistency: the pack records the KB version and, per item, the KB's
``version_baseline``; rule items whose baseline names a game version other than
the installed card data's are reported in ``KnowledgePack.warnings``.
"""

from __future__ import annotations

import json
import os
import re
try:
    import tomllib
except ModuleNotFoundError:  # Python <=3.10 (e.g. the cluster): tomli backport
    import tomli as tomllib  # type: ignore
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from common.paths import REPO_ROOT

from .knowledge import KB_ENV, KnowledgeBase, matching_units
from .schema import DecisionContext

KNOWLEDGE_ENV = "GITCG_KNOWLEDGE_CONFIG"
DEFAULT_KNOWLEDGE_FILE = REPO_ROOT / "configs" / "knowledge.toml"
LOCAL_KNOWLEDGE_FILE = REPO_ROOT / "configs" / "knowledge.local.toml"

RULE = "rule"
STRATEGY = "strategy"
EXPERT_EXAMPLE = "expert_example"
CUSTOM_RULE = "custom_rule"
CUSTOM_STRATEGY = "custom_strategy"
FACT_KINDS = (RULE, CUSTOM_RULE)

_HEADINGS = {
    RULE: "【规则事实】来自规则知识库，可直接作为依据。",
    CUSTOM_RULE: "【自定义资料·规则】由使用者提供并标注为规则。",
    STRATEGY: "【策略观点（未经验证）】来自策略知识库，是经验性建议而非规则；"
              "与规则事实或合法动作列表冲突时，以后者为准。",
    CUSTOM_STRATEGY: "【自定义资料·策略（未经验证）】由使用者提供并标注为策略观点。",
    EXPERT_EXAMPLE: "【专家对局示例】脚本专家在相似局面的实际选择；是行为记录，不保证最优。",
}
_ORDER = (RULE, CUSTOM_RULE, STRATEGY, CUSTOM_STRATEGY, EXPERT_EXAMPLE)
_VERSION = re.compile(r"v(\d+)\.(\d+)(?:\.(\d+))?")


@dataclass(frozen=True)
class KnowledgeProfile:
    name: str = "none"
    rules: bool = False
    rule_evidence: tuple[str, ...] = ("官方", "引擎")     # a section needs one of these
    max_rules: int = 3
    rule_chars: int = 420
    strategy: bool = False
    strategy_confidence: tuple[str, ...] = ()            # () = any KB confidence label
    strategy_docs: tuple[str, ...] = ()                  # () = all; e.g. ("S01", "S06")
    max_strategy: int = 4
    # How a strategy unit is rendered: "brief" = condition + recommendation (+ limits),
    # the short labels used since D29; "full" = the unit's conclusion + key variables +
    # limits from the KB (the substance of the unit; several times longer).
    strategy_detail: str = "brief"
    strategy_chars: int = 360
    # How rule sections are chosen: "kind_map" = the fixed option-kind -> section map
    # (since D29); "retrieve" = BM25 over the sections against the visible decision
    # (options + public state), skipping documents that do not describe play.
    rule_selection: str = "kind_map"
    rule_exclude_docs: tuple[str, ...] = ("R00", "R11", "R12", "R13")
    # Situation-triggered rule sections (reps.kb_retrieval.RULE_TRIGGERS): when a visible
    # situation holds (the opponent has declared end, the opponent's active character
    # carries an element, ...) its governing sections come first; the rest is filled by
    # ``rule_selection``.
    rule_triggers: bool = False
    # which trigger table (reps.kb_retrieval.TRIGGER_SETS); "d32" is the original one
    rule_trigger_set: str = "d32"
    # Strategy units whose detector fires on more than this share of decisions in the
    # frequency table (measured on training data) carry no information about the
    # decision and are dropped. 1.0 = keep everything.
    unit_frequency_file: str = ""
    max_unit_frequency: float = 1.0
    expert_examples: tuple[str, ...] = ()                # supervision JSONL files
    max_examples: int = 2
    custom: tuple[str, ...] = ()                         # files or directories
    max_custom: int = 2
    custom_chars: int = 500
    max_chars: int = 3200                                # whole pack
    kb_root: str = ""                                    # "" = $GITCG_KB_DIR
    # KB version (D34, reps.kb_versions): "" = v1.0 at kb_root / $GITCG_KB_DIR
    kb_version: str = ""
    # D36: strategy units that, when their detector fires, take the first slots and are
    # exempt from max_unit_frequency (a principle meant to apply at most action decisions).
    strategy_priority: tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        return bool(self.rules or self.strategy or self.expert_examples or self.custom)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "rules": self.rules, "rule_evidence": list(self.rule_evidence),
            "max_rules": self.max_rules, "strategy": self.strategy,
            "strategy_confidence": list(self.strategy_confidence),
            "strategy_docs": list(self.strategy_docs), "max_strategy": self.max_strategy,
            "expert_examples": list(self.expert_examples), "max_examples": self.max_examples,
            "custom": list(self.custom), "max_custom": self.max_custom, "max_chars": self.max_chars,
            # only when changed, so manifests written before these options existed stay identical
            **({"strategy_detail": self.strategy_detail} if self.strategy_detail != "brief" else {}),
            **({"strategy_chars": self.strategy_chars} if self.strategy_chars != 360 else {}),
            **({"rule_selection": self.rule_selection} if self.rule_selection != "kind_map" else {}),
            **({"rule_triggers": True} if self.rule_triggers else {}),
            **({"rule_trigger_set": self.rule_trigger_set} if self.rule_triggers and self.rule_trigger_set != "d32" else {}),
            **({"kb_version": self.kb_version} if self.kb_version else {}),
            **({"strategy_priority": list(self.strategy_priority)} if self.strategy_priority else {}),
            **({"unit_frequency_file": self.unit_frequency_file,
                "max_unit_frequency": self.max_unit_frequency} if self.unit_frequency_file else {}),
        }


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(str(v) for v in value)


def profile_from_mapping(name: str, raw: Mapping[str, Any]) -> KnowledgeProfile:
    known = set(KnowledgeProfile.__dataclass_fields__) - {"name"}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"knowledge profile {name!r}: unknown keys {sorted(unknown)}")
    if str(raw.get("strategy_detail", "brief")) not in ("brief", "full"):
        raise ValueError(f"knowledge profile {name!r}: strategy_detail must be 'brief' or 'full'")
    if str(raw.get("rule_selection", "kind_map")) not in ("kind_map", "retrieve"):
        raise ValueError(f"knowledge profile {name!r}: rule_selection must be 'kind_map' or 'retrieve'")
    from reps.kb_retrieval import TRIGGER_SETS

    if str(raw.get("rule_trigger_set", "d32")) not in TRIGGER_SETS:
        raise ValueError(f"knowledge profile {name!r}: rule_trigger_set must be one of {sorted(TRIGGER_SETS)}")
    values: dict[str, Any] = {}
    for key, value in raw.items():
        default = KnowledgeProfile.__dataclass_fields__[key].default
        values[key] = _tuple(value) if isinstance(default, tuple) else type(default)(value)
    return KnowledgeProfile(name=name, **values)


def load_knowledge_profiles(paths: Sequence[str | Path] | None = None) -> dict[str, KnowledgeProfile]:
    """Configured profiles; ``none`` (no knowledge) always exists."""
    profiles = {"none": KnowledgeProfile()}
    if paths is None:
        candidates = [DEFAULT_KNOWLEDGE_FILE, LOCAL_KNOWLEDGE_FILE]
        if os.environ.get(KNOWLEDGE_ENV):
            candidates.append(Path(os.environ[KNOWLEDGE_ENV]))
        paths = [p for p in candidates if p.exists()]
    for path in paths:
        with Path(path).open("rb") as handle:
            data = tomllib.load(handle)
        for name, raw in (data.get("profiles") or {}).items():
            profiles[str(name)] = profile_from_mapping(str(name), raw)
    return profiles


def get_knowledge_profile(name: str | None) -> KnowledgeProfile:
    if not name or name == "none":
        return KnowledgeProfile()
    profiles = load_knowledge_profiles()
    if name not in profiles:
        raise KeyError(f"unknown knowledge profile {name!r} (configured: {sorted(profiles)})")
    return profiles[name]


@dataclass(frozen=True)
class KnowledgeItem:
    id: str
    kind: str                 # rule | strategy | expert_example | custom_rule | custom_strategy
    title: str
    text: str
    source: str               # GITCG_KB | <file path> | <supervision file>
    version: str = ""         # KB / file version
    baseline: str = ""        # game-version statement of the item
    trust: str = ""           # evidence classes or KB confidence label

    @property
    def is_fact(self) -> bool:
        return self.kind in FACT_KINDS

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "title": self.title, "source": self.source,
                "version": self.version, "baseline": self.baseline, "trust": self.trust,
                "chars": len(self.text)}


@dataclass
class KnowledgePack:
    profile: str
    items: list[KnowledgeItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    kb_version: str = ""

    @property
    def text(self) -> str:
        blocks = []
        for kind in _ORDER:
            members = [item for item in self.items if item.kind == kind]
            if not members:
                continue
            lines = [_HEADINGS[kind]]
            for item in members:
                label = f"（{item.trust}）" if item.trust else ""
                lines.append(f"- [{item.id}] {item.title}{label}：{item.text}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def as_dict(self) -> dict[str, Any]:
        return {"profile": self.profile, "kb_version": self.kb_version,
                "items": [item.as_dict() for item in self.items], "warnings": list(self.warnings),
                "chars": len(self.text)}


def _squash(text: str, limit: int) -> str:
    flat = re.sub(r"\s*\n\s*", " ", str(text)).strip()
    return flat if len(flat) <= limit else flat[: max(0, limit - 1)].rstrip() + "…"


def installed_game_version() -> str:
    """Newest ``sinceVersion`` in the cached card data, e.g. ``v7.2.0`` ("" if unknown)."""
    return _installed_game_version()


@lru_cache(maxsize=1)
def _installed_game_version() -> str:
    try:
        from agents.scripted.assets import _cache_path

        payload = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    best: tuple[int, ...] = ()
    for item in payload.get("data", ()):
        match = _VERSION.fullmatch(str(item.get("sinceVersion", "")))
        if match:
            best = max(best, tuple(int(g or 0) for g in match.groups()))
    return "v" + ".".join(str(n) for n in best) if best else ""


@dataclass(frozen=True)
class CustomChunk:
    id: str
    kind: str
    title: str
    text: str
    source: str
    version: str
    when: str = ""          # a situation name (reps.kb_retrieval.SITUATIONS): shown exactly when it holds


def load_custom(paths: Iterable[str]) -> tuple[list[CustomChunk], list[str]]:
    """Read custom notes. Returns (chunks, warnings); unclassified files are refused."""
    chunks: list[CustomChunk] = []
    warnings: list[str] = []
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute() and not path.exists():
            from common.paths import REPO_ROOT

            path = REPO_ROOT / path               # profiles name repo-relative paths
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*") if p.suffix.lower() in (".md", ".txt")))
        elif path.exists():
            files.append(path)
        else:
            warnings.append(f"custom source not found: {raw}")
    for path in files:
        text = path.read_text(encoding="utf-8")
        meta: dict[str, str] = {}
        body = text
        if text.startswith("---"):
            head, _, rest = text[3:].partition("\n---")
            body = rest.lstrip("\n")
            for line in head.splitlines():
                key, sep, value = line.partition(":")
                if sep:
                    meta[key.strip().lower()] = value.strip().strip('"').strip("'")
        kind = meta.get("kind", "").lower()
        if kind not in ("rule", "strategy"):
            warnings.append(f"{path}: refused -- front matter must declare 'kind: rule' or 'kind: strategy'")
            continue
        if not meta.get("version"):
            warnings.append(f"{path}: no 'version' in front matter (loaded as unversioned)")
        when = meta.get("when", "")
        if when:
            from reps.kb_retrieval import SITUATIONS

            if when not in SITUATIONS:
                warnings.append(f"{path}: refused -- unknown 'when: {when}' (known: {sorted(SITUATIONS)})")
                continue
        sections = re.split(r"(?m)^(?=#{1,3} )", body)
        for n, section in enumerate(s for s in sections if s.strip()):
            first, _, remainder = section.strip().partition("\n")
            title = first.lstrip("# ").strip() if first.startswith("#") else (meta.get("title") or path.stem)
            content = remainder.strip() if first.startswith("#") else section.strip()
            if not content:
                continue
            chunks.append(CustomChunk(
                id=f"{path.stem}#{n + 1}", kind=CUSTOM_RULE if kind == "rule" else CUSTOM_STRATEGY,
                title=title, text=content, source=str(path), version=meta.get("version", ""), when=when,
            ))
    return chunks, warnings


def _terms(text: str) -> set[str]:
    """Search terms: CJK bigrams plus latin words (no tokenizer dependency)."""
    terms = {w.lower() for w in re.findall(r"[A-Za-z0-9]{2,}", text)}
    for run in re.findall(r"[一-鿿]{2,}", text):
        terms.update(run[i : i + 2] for i in range(len(run) - 1))
    return terms


class KnowledgeSelector:
    """Builds the :class:`KnowledgePack` for decisions under one profile."""

    def __init__(self, profile: KnowledgeProfile, *, kb: KnowledgeBase | None = None) -> None:
        self.profile = profile
        self.kb = kb
        self.load_warnings: list[str] = []
        self._examples: list[Any] = []
        self._custom: list[CustomChunk] = []
        if (profile.rules or profile.strategy) and self.kb is None:
            try:
                if profile.kb_version:
                    from .kb_versions import resolve

                    try:
                        root = resolve(profile.kb_version)
                    except FileNotFoundError as exc:   # a named version must exist: never play without it
                        raise RuntimeError(str(exc)) from exc
                    self.kb = KnowledgeBase.load(root)
                else:
                    self.kb = KnowledgeBase.load(profile.kb_root or None)
            except FileNotFoundError as exc:
                self.load_warnings.append(
                    f"knowledge base unavailable ({exc}); rules/strategy are not injected. "
                    f"Set {KB_ENV} or 'kb_root'.")
        if profile.expert_examples:
            from .strategy import read_supervision

            for path in profile.expert_examples:
                try:
                    self._examples.extend(read_supervision(path))
                except (OSError, ValueError) as exc:
                    self.load_warnings.append(f"expert examples {path}: {exc}")
        if profile.custom:
            self._custom, warnings = load_custom(profile.custom)
            self.load_warnings.extend(warnings)
        self._game_version = installed_game_version()
        self._unit_detail: dict[str, Mapping[str, Any]] | None = None
        self._rule_index: Any = None
        self._describer: Any = None
        self._unit_frequency: dict[str, float] | None = None

    def _frequency(self) -> dict[str, float]:
        """Unit id -> share of training decisions its detector fired on (empty = no pruning)."""
        if self._unit_frequency is None:
            self._unit_frequency = {}
            name = self.profile.unit_frequency_file
            if name:
                path = Path(name)
                if not path.is_absolute():
                    from common.paths import REPO_ROOT

                    path = REPO_ROOT / path
                payload = json.loads(path.read_text(encoding="utf-8"))
                self._unit_frequency = {str(k): float(v) for k, v in payload["frequency"].items()}
        return self._unit_frequency

    def _detail(self, unit_id: str) -> Mapping[str, Any]:
        """Fields of a strategy unit that ``StrategyUnit`` does not carry (conclusion,
        key variables), read once from the KB's ``strategy_units.jsonl``."""
        if self._unit_detail is None:
            self._unit_detail = {}
            if self.kb is not None and self.kb.root:
                path = Path(self.kb.root) / "data" / "derived" / "strategy_units.jsonl"
                if path.exists():
                    for line in path.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            row = json.loads(line)
                            self._unit_detail[str(row["id"])] = row
        return self._unit_detail.get(unit_id, {})

    def summary(self) -> dict[str, Any]:
        """What was loaded (for run manifests and the UI)."""
        return {
            "profile": self.profile.as_dict(),
            "kb_version": self.kb.version if self.kb is not None else "",
            "kb_units": len(self.kb.units) if self.kb is not None else 0,
            "kb_rules": len(self.kb.rules) if self.kb is not None else 0,
            "expert_examples": len(self._examples),
            "custom_chunks": len(self._custom),
            "game_version": self._game_version,
            "warnings": list(self.load_warnings),
        }

    # -- per-source selection --------------------------------------------------- #
    def _rules(self, context: DecisionContext, warnings: list[str]) -> list[KnowledgeItem]:
        kb, profile = self.kb, self.profile
        if kb is None or not profile.rules:
            return []
        seen: list[Any] = []
        if profile.rule_triggers:
            from reps.kb_retrieval import triggered_rules

            seen = [kb.rules[ref] for ref in triggered_rules(context, profile.rule_trigger_set) if ref in kb.rules]
        if profile.rule_selection == "retrieve":
            from reps.kb_retrieval import decision_query, section_index

            if self._rule_index is None:
                self._rule_index = section_index(list(kb.rules.values()), exclude_docs=profile.rule_exclude_docs)
            if self._describer is None:
                from reps.describe import DecisionDescriber

                self._describer = DecisionDescriber()
            query = decision_query(context, self._describer)
            seen += [kb.rules[ref] for ref in self._rule_index.rank(query, max(profile.max_rules * 2, 6))
                     if ref in kb.rules and kb.rules[ref] not in seen]
        else:
            for kind in dict.fromkeys(spec.kind.value for spec in context.legal_low_level_specs):
                for rule in kb.rules_for_option_kind(kind):
                    if rule not in seen:
                        seen.append(rule)
        items = []
        for rule in seen:
            evidence = set(rule.evidence)
            if profile.rule_evidence and not evidence & set(profile.rule_evidence):
                continue
            trust = "/".join(rule.evidence)
            if "待核" in evidence:
                trust += "；含待核内容"
            # A rule is checked against the installed card data by the newest game
            # version its baseline names ("v3.3.0–v7.2.0" -> v7.2.0).
            named = [tuple(int(g or 0) for g in m) for m in _VERSION.findall(rule.version_baseline)]
            if self._game_version and named:
                newest = "v" + ".".join(str(n) for n in max(named))
                if newest != self._game_version:
                    warnings.append(f"rule {rule.ref}: written for {newest}, "
                                    f"installed card data is {self._game_version}")
            items.append(KnowledgeItem(
                id=rule.ref, kind=RULE, title=rule.heading, text=_squash(rule.text, profile.rule_chars),
                source=rule.provenance.source, version=rule.provenance.version,
                baseline=rule.version_baseline, trust=trust,
            ))
            if len(items) >= profile.max_rules:
                break
        return items

    def _strategy(self, context: DecisionContext) -> list[KnowledgeItem]:
        kb, profile = self.kb, self.profile
        if kb is None or not profile.strategy:
            return []
        items = []
        frequency = self._frequency()
        # a versioned KB (D34) brings its own detector table; v1.0 keeps the original call
        units = matching_units(context, version=kb.version) if profile.kb_version else matching_units(context)
        if profile.strategy_priority:                # D36: listed units first, in the listed order
            first = [u for u in profile.strategy_priority if u in units]
            units = tuple(first) + tuple(u for u in units if u not in first)
        for unit_id in units:
            unit = kb.units.get(unit_id)
            if unit is None:
                continue
            if frequency and frequency.get(unit_id, 0.0) > profile.max_unit_frequency \
                    and unit_id not in profile.strategy_priority:
                continue
            if profile.strategy_docs and not any(tag in unit.doc for tag in profile.strategy_docs):
                continue
            if profile.strategy_confidence and unit.confidence not in profile.strategy_confidence:
                continue
            detail = self._detail(unit.id) if profile.strategy_detail == "full" else {}
            if detail.get("conclusion"):
                text = f"结论：{detail['conclusion']}"
                if detail.get("key_variables"):
                    text += f"。关键变量：{detail['key_variables']}"
                if unit.limits:
                    text += f"。局限：{_squash(unit.limits, 200)}"
            else:
                text = f"适用条件：{unit.condition}。建议：{unit.recommendation}"
                if unit.limits:
                    text += f"。局限：{_squash(unit.limits, 120)}"
            items.append(KnowledgeItem(
                id=unit.id, kind=STRATEGY, title=unit.concept, text=_squash(text, profile.strategy_chars),
                source=unit.provenance.source, version=unit.provenance.version,
                baseline=unit.version_baseline,
                trust=f"KB 置信度 {unit.confidence}；证据 {'/'.join(unit.evidence_types)}",
            ))
            if len(items) >= profile.max_strategy:
                break
        return items

    def _expert_examples(self, context: DecisionContext) -> list[KnowledgeItem]:
        if not self._examples or self.profile.max_examples <= 0:
            return []
        request = context.request_type.value
        kinds = {spec.kind.value for spec in context.legal_low_level_specs}
        view = context.player_view
        round_number = int(view.round_number) if view is not None else 0
        scored = []
        for order, record in enumerate(self._examples):
            if record.request_type != request or not record.options:
                continue
            record_kinds = {option.kind for option in record.options}
            overlap = len(kinds & record_kinds) / max(1, len(kinds | record_kinds))
            score = overlap + (0.5 if int(record.round_number) == round_number else 0.0)
            scored.append((-score, order, record))
        items = []
        for _score, _order, record in sorted(scored, key=lambda row: row[:2])[: self.profile.max_examples]:
            chosen = record.options[record.expert_index]
            text = (f"第 {record.round_number} 回合，{record.deck} 对 {record.opponent}。"
                    f"局面：{_squash(record.text, 260)} → 专家选择：{chosen.text or chosen.kind}")
            items.append(KnowledgeItem(
                id=f"{record.deck}:{record.seed}:{record.side}:{record.step_index}",
                kind=EXPERT_EXAMPLE, title=f"{record.expert_policy}", text=text,
                source=record.provenance.source, version=record.provenance.version,
                trust="expert_action",
            ))
        return items

    def _custom_items(self, query: str, context: DecisionContext | None = None) -> list[KnowledgeItem]:
        if not self._custom or self.profile.max_custom <= 0:
            return []
        items: list[KnowledgeItem] = []
        from reps.kb_retrieval import SITUATIONS

        for chunk in self._custom:                 # situation-triggered notes: shown exactly when they apply
            if chunk.when and context is not None and SITUATIONS[chunk.when](context):
                items.append(KnowledgeItem(
                    id=chunk.id, kind=chunk.kind, title=chunk.title,
                    text=_squash(chunk.text, self.profile.custom_chars), source=chunk.source,
                    version=chunk.version, trust="自定义" + ("" if chunk.version else "；未标版本"),
                ))
        wanted = _terms(query)
        scored = []
        for order, chunk in enumerate(c for c in self._custom if not c.when):
            hits = len(wanted & _terms(chunk.title + " " + chunk.text))
            scored.append((-hits, order, chunk))
        plain = [c for c in self._custom if not c.when]
        for hits, _order, chunk in sorted(scored, key=lambda row: row[:2])[: self.profile.max_custom]:
            if hits == 0 and len(plain) > self.profile.max_custom:
                continue        # nothing in common with this decision
            items.append(KnowledgeItem(
                id=chunk.id, kind=chunk.kind, title=chunk.title,
                text=_squash(chunk.text, self.profile.custom_chars), source=chunk.source,
                version=chunk.version, trust="自定义" + ("" if chunk.version else "；未标版本"),
            ))
        return items

    def select(self, context: DecisionContext, *, query: str = "") -> KnowledgePack:
        """Knowledge for one decision. ``query`` is extra visible text to match custom notes on."""
        pack = KnowledgePack(profile=self.profile.name,
                             kb_version=self.kb.version if self.kb is not None else "",
                             warnings=list(self.load_warnings))
        if not self.profile.enabled or context.player_view is None:
            return pack
        candidates = (self._rules(context, pack.warnings) + self._custom_items(query, context)
                      + self._strategy(context) + self._expert_examples(context))
        budget = int(self.profile.max_chars)
        for kind in _ORDER:               # facts first: they survive a tight budget
            for item in candidates:
                if item.kind != kind:
                    continue
                cost = len(item.text) + len(item.title) + 24
                if cost > budget:
                    continue
                pack.items.append(item)
                budget -= cost
        return pack
