"""Model-agnostic strategy supervision records (MASD-ADM / VCSD interface layer).

This module is the *shared data contract* between knowledge sources, evidence
generators, trainers and student models. It deliberately contains no tensors, no
encoder layout and no network code: a record describes one decision by its
identity, its legal options (semantic keys + text), what the expert did, and --
optionally -- counterfactual evidence about some candidate actions. Network
students join it to encoded features by decision key
(``train.strategy_targets``); text/LLM students read ``text`` and ``options``.

Evidence boundary (never blur these):

* ``expert_action``     -- what an expert policy actually played. A behaviour label.
* ``language_strategy`` -- a knowledge-base unit (concept + applicability
  condition). Text-derived and unverified; attached as an annotation only, never
  written into an action label or a value by this layer.
* ``search_estimate``   -- a Monte-Carlo value estimate *relative to the stated
  continuation policies and information assumption*; not a game-theoretic value.
* ``verified``          -- not stored. It is a *derived* status: a search estimate
  that passes an explicit statistical gate (:func:`verdict`), recomputed from the
  raw rollout scores whenever needed so the gate stays auditable.

The unit ``k = (c, phi, pi_k, dQ, rho)`` of the research note maps to:
``c``/``phi`` = :class:`StrategyUnit` (+ ``reps.knowledge`` detectors),
``pi_k`` = a target built at training time (``train.strategy_targets.TargetSpec``),
``dQ`` = :class:`PairedComparison`, ``rho`` = :func:`reliability`.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

SCHEMA = "masd.supervision/1"


class EvidenceKind(str, Enum):
    EXPERT_ACTION = "expert_action"
    LANGUAGE_STRATEGY = "language_strategy"
    SEARCH_ESTIMATE = "search_estimate"
    # 2026-11 (D29): what a person did or said they prefer. A demonstration is an
    # action label like ``expert_action``; a preference is an unverified opinion
    # until counterfactual evidence backs it.
    HUMAN_DEMONSTRATION = "human_demonstration"
    HUMAN_PREFERENCE = "human_preference"


@dataclass(frozen=True)
class Provenance:
    """Where a record came from. ``source`` is a stable id, ``version`` its version."""

    source: str
    version: str = ""
    generator: str = ""
    created: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "version": self.version, "generator": self.generator,
                "created": self.created, "extra": dict(self.extra)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "Provenance":
        payload = payload or {}
        return cls(source=str(payload.get("source", "")), version=str(payload.get("version", "")),
                   generator=str(payload.get("generator", "")), created=str(payload.get("created", "")),
                   extra=dict(payload.get("extra") or {}))


@dataclass(frozen=True)
class StrategyUnit:
    """A knowledge-base strategy unit: concept ``c`` and applicability ``phi`` as text.

    ``confidence`` is the knowledge base's own label (e.g. 高/中/低) and
    ``evidence_types`` its evidence classes (机制/计算/统计/解说/推断). Neither is a
    probability; they are carried verbatim for filtering and reporting.
    """

    id: str
    concept: str
    condition: str
    recommendation: str
    evidence_types: tuple[str, ...] = ()
    confidence: str = ""
    limits: str = ""
    doc: str = ""
    version_baseline: str = ""
    provenance: Provenance = field(default_factory=lambda: Provenance(source=""))
    kind: str = EvidenceKind.LANGUAGE_STRATEGY.value


@dataclass(frozen=True)
class OptionRef:
    """One legal option of a decision, in the engine/encoder option order."""

    index: int
    kind: str
    semantic_key: Any            # JSON-safe (nested lists) semantic action key
    text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"index": self.index, "kind": self.kind, "semantic_key": self.semantic_key,
                "text": self.text}


@dataclass(frozen=True)
class CandidateEstimate:
    """Rollout outcomes of one candidate (acting player's perspective, in [0, 1]).

    ``scores[r]`` is rollout ``r`` (``None`` = fork discarded); rollout ``r`` shares
    its root particle and rollout seed with rollout ``r`` of every other candidate.
    """

    option_index: int
    scores: tuple[float | None, ...]

    @property
    def valid(self) -> list[float]:
        return [float(v) for v in self.scores if v is not None]

    @property
    def n(self) -> int:
        return len(self.valid)

    @property
    def mean(self) -> float | None:
        values = self.valid
        return sum(values) / len(values) if values else None

    def as_dict(self) -> dict[str, Any]:
        return {"option_index": self.option_index, "scores": list(self.scores),
                "n": self.n, "mean": self.mean}


@dataclass(frozen=True)
class PairedComparison:
    """``dQ`` of ``option_index`` against ``baseline_index`` from paired rollouts.

    ``wins``/``losses`` count the pairs in which the option did strictly better /
    worse than the baseline; ``p_sign`` is the exact two-sided sign-test p-value on
    those discordant pairs (1.0 when there are none). ``z`` is descriptive only:
    with a handful of pairs a normal approximation overstates certainty, so the
    gate (:func:`verdict`) uses ``p_sign``.
    """

    option_index: int
    baseline_index: int
    n_pairs: int
    mean_diff: float
    se: float
    z: float
    wins: int = 0
    losses: int = 0
    p_sign: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# A paired outcome difference lies in {-1, -0.5, 0, 0.5, 1}. With a handful of
# pairs the sample variance is often exactly 0 (all pairs agree), which would make
# z infinite; the floor only keeps the descriptive z finite.
DEFAULT_VAR_FLOOR = 0.05


def sign_test_p(wins: int, losses: int) -> float:
    """Exact two-sided sign test: P(a split at least this lopsided | fair coin)."""
    discordant = int(wins) + int(losses)
    if discordant <= 0:
        return 1.0
    extreme = max(int(wins), int(losses))
    tail = sum(math.comb(discordant, k) for k in range(extreme, discordant + 1)) / 2.0 ** discordant
    return min(1.0, 2.0 * tail)


def sign_test_pass_probability(discordant: int, alpha: float = 0.05) -> float:
    """P(sign-test p <= alpha) for ``discordant`` pairs when the two actions are equal.

    Under that null each discordant pair is a fair coin whatever their number, so
    this is the exact chance that a comparison passes the gate by luck. It is 0
    below 6 discordant pairs at ``alpha = 0.05``: such a comparison cannot pass.
    """
    d = int(discordant)
    return sum(math.comb(d, k) for k in range(d + 1) if sign_test_p(k, d - k) <= float(alpha)) / 2.0 ** d


def paired_comparison(
    scores: Sequence[float | None],
    baseline: Sequence[float | None],
    *,
    option_index: int,
    baseline_index: int,
    var_floor: float = DEFAULT_VAR_FLOOR,
) -> PairedComparison:
    """Paired difference ``scores[r] - baseline[r]`` over rollouts valid for both."""
    diffs = [float(a) - float(b) for a, b in zip(scores, baseline) if a is not None and b is not None]
    n = len(diffs)
    if n == 0:
        return PairedComparison(option_index, baseline_index, 0, 0.0, float("inf"), 0.0)
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1) if n > 1 else 0.0
    se = math.sqrt(max(var, float(var_floor)) / n)
    wins = sum(1 for d in diffs if d > 0)
    losses = sum(1 for d in diffs if d < 0)
    return PairedComparison(option_index, baseline_index, n, mean, se, mean / se if se > 0 else 0.0,
                            wins, losses, sign_test_p(wins, losses))


def reliability(comparison: PairedComparison) -> float:
    """``rho`` in [0, 1): ``1 - p_sign``, how sure the *sign* of ``dQ`` is.

    0 = no information (no pairs, or no discordant pair). It is a statement about
    the Monte-Carlo estimate under its stated continuation policies and belief
    model, not about optimal play.
    """
    if comparison.n_pairs <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - float(comparison.p_sign)))


@dataclass(frozen=True)
class CounterfactualEvidence:
    """Candidate values for one decision plus everything needed to audit them."""

    candidates: tuple[CandidateEstimate, ...]
    baseline_index: int                   # the expert's action (always evaluated)
    continuation: Mapping[str, str]       # {"self": spec, "opponent": spec} rollout policies
    information: Mapping[str, Any]        # root kind, belief samples, assumptions
    rollouts: int
    base_seed: int
    errors: Mapping[str, int] = field(default_factory=dict)
    kind: str = EvidenceKind.SEARCH_ESTIMATE.value

    def candidate(self, option_index: int) -> CandidateEstimate | None:
        for item in self.candidates:
            if item.option_index == int(option_index):
                return item
        return None

    def comparisons(self, *, var_floor: float = DEFAULT_VAR_FLOOR) -> list[PairedComparison]:
        """``dQ(a, expert)`` for every evaluated alternative ``a``."""
        base = self.candidate(self.baseline_index)
        if base is None:
            return []
        return [
            paired_comparison(item.scores, base.scores, option_index=item.option_index,
                              baseline_index=self.baseline_index, var_floor=var_floor)
            for item in self.candidates if item.option_index != self.baseline_index
        ]

    @property
    def is_information_legal(self) -> bool:
        """True when the estimate used only what the acting player could know."""
        info = self.information
        return info.get("root") == "public_belief" and bool(info.get("empty_prefix", False))

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "candidates": [c.as_dict() for c in self.candidates],
            "baseline_index": self.baseline_index,
            "paired": [c.as_dict() for c in self.comparisons()],
            "continuation": dict(self.continuation),
            "information": dict(self.information),
            "rollouts": self.rollouts,
            "base_seed": self.base_seed,
            "errors": dict(self.errors),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CounterfactualEvidence":
        return cls(
            candidates=tuple(
                CandidateEstimate(int(c["option_index"]),
                                  tuple(None if v is None else float(v) for v in c["scores"]))
                for c in payload["candidates"]
            ),
            baseline_index=int(payload["baseline_index"]),
            continuation=dict(payload.get("continuation") or {}),
            information=dict(payload.get("information") or {}),
            rollouts=int(payload.get("rollouts", 0)),
            base_seed=int(payload.get("base_seed", 0)),
            errors=dict(payload.get("errors") or {}),
            kind=str(payload.get("kind", EvidenceKind.SEARCH_ESTIMATE.value)),
        )


@dataclass(frozen=True)
class Verdict:
    """Outcome of the statistical gate for one decision."""

    status: str                 # "expert_supported" | "alternative_supported" | "inconclusive"
    option_index: int           # the supported action (expert's when inconclusive)
    comparison: PairedComparison | None
    reliability: float

    @property
    def verified(self) -> bool:
        return self.status != "inconclusive"


def verdict(
    evidence: CounterfactualEvidence,
    *,
    alpha: float = 0.05,
    min_pairs: int = 8,
    require_information_legal: bool = True,
) -> Verdict:
    """Apply the gate that turns a search estimate into a *verified* preference.

    * ``alternative_supported``: some alternative beats the expert's action with
      sign-test ``p <= alpha`` on at least ``min_pairs`` paired rollouts (the one
      with the smallest p);
    * ``expert_supported``: every evaluated alternative is worse with ``p <= alpha``;
    * ``inconclusive``: anything else -- including evidence that used hidden truth
      when ``require_information_legal`` (such evidence is never "verified").

    "Verified" is per decision at level ``alpha``: over ``N`` tested decisions about
    ``alpha * N`` verdicts are expected by chance alone, so a batch of verdicts
    must be read against that number (``train.evidence.summarize``).
    """
    comparisons = evidence.comparisons()
    base = evidence.baseline_index
    if not comparisons or (require_information_legal and not evidence.is_information_legal):
        return Verdict("inconclusive", base, None, 0.0)
    usable = [c for c in comparisons if c.n_pairs >= int(min_pairs)]
    better = [c for c in usable if c.mean_diff > 0 and c.p_sign <= float(alpha)]
    if better:
        best = min(better, key=lambda c: (c.p_sign, -c.mean_diff, c.option_index))
        return Verdict("alternative_supported", best.option_index, best, reliability(best))
    if usable and len(usable) == len(comparisons) and all(
        c.mean_diff < 0 and c.p_sign <= float(alpha) for c in usable
    ):
        weakest = max(usable, key=lambda c: c.p_sign)   # the least certain alternative
        return Verdict("expert_supported", base, weakest, reliability(weakest))
    closest = min(comparisons, key=lambda c: c.p_sign)
    return Verdict("inconclusive", base, closest, reliability(closest))


HUMAN_KINDS = ("demonstration", "override", "correction", "rating")


@dataclass(frozen=True)
class HumanSignal:
    """A person's input on one decision (``lab``).

    * ``demonstration`` -- the person played this decision (``preferred_index`` is
      what they played);
    * ``override``      -- the person replaced a policy's proposal before it was
      played (``rejected_index`` is the proposal);
    * ``correction``    -- after the fact, the person marked another option as
      better than the one played (``rejected_index`` is the played one);
    * ``rating``        -- a verdict on the played action only (``rating`` -1/0/+1).
    """

    kind: str
    preferred_index: int | None = None
    rejected_index: int | None = None
    rating: int = 0
    comment: str = ""
    annotator: str = ""
    # False when the person could see hidden information while deciding.
    information_clean: bool = True

    def __post_init__(self) -> None:
        if self.kind not in HUMAN_KINDS:
            raise ValueError(f"unknown human signal kind {self.kind!r} (expected one of {HUMAN_KINDS})")

    @property
    def evidence_kind(self) -> str:
        return (EvidenceKind.HUMAN_DEMONSTRATION if self.kind == "demonstration"
                else EvidenceKind.HUMAN_PREFERENCE).value

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "evidence_kind": self.evidence_kind,
                "preferred_index": self.preferred_index, "rejected_index": self.rejected_index,
                "rating": int(self.rating), "comment": self.comment, "annotator": self.annotator,
                "information_clean": bool(self.information_clean)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HumanSignal":
        return cls(kind=str(payload["kind"]), preferred_index=payload.get("preferred_index"),
                   rejected_index=payload.get("rejected_index"), rating=int(payload.get("rating", 0)),
                   comment=str(payload.get("comment", "")), annotator=str(payload.get("annotator", "")),
                   information_clean=bool(payload.get("information_clean", True)))


@dataclass(frozen=True)
class DecisionSupervision:
    """One decision with its options, the expert's action and optional evidence."""

    deck: str
    opponent: str
    seed: int
    side: int
    step_index: int
    ordinal: int
    round_number: int
    request_type: str
    options: tuple[OptionRef, ...]
    expert_index: int
    expert_policy: str                     # policy spec that produced the action
    outcome: float | None = None           # episode score of the acting player
    text: str = ""                         # public-view rendering (info-safe)
    knowledge: tuple[str, ...] = ()        # ids of StrategyUnits whose condition matched
    evidence: CounterfactualEvidence | None = None
    provenance: Provenance = field(default_factory=lambda: Provenance(source=""))
    schema: str = SCHEMA
    # Additive (D29): set only on records that carry a person's input. Records
    # without it serialise exactly as before.
    human: HumanSignal | None = None

    @property
    def game_key(self) -> tuple[Any, ...]:
        """Same layout as ``scripts.train_bc_scale._game_key`` (side only if non-zero)."""
        key: tuple[Any, ...] = (self.deck, self.opponent, int(self.seed))
        return key + (int(self.side),) if int(self.side) else key

    @property
    def store_key(self) -> tuple[Any, ...]:
        """The key of this decision's sample in a ``Store`` (game key + step)."""
        return self.game_key + (int(self.step_index),)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": self.schema,
            "deck": self.deck, "opponent": self.opponent, "seed": int(self.seed),
            "side": int(self.side), "step_index": int(self.step_index),
            "ordinal": int(self.ordinal), "round_number": int(self.round_number),
            "request_type": self.request_type,
            "options": [o.as_dict() for o in self.options],
            "expert_index": int(self.expert_index),
            "expert_policy": self.expert_policy,
            "expert_kind": EvidenceKind.EXPERT_ACTION.value,
            "outcome": self.outcome,
            "text": self.text,
            "knowledge": list(self.knowledge),
            "evidence": None if self.evidence is None else self.evidence.as_dict(),
            "provenance": self.provenance.as_dict(),
        }
        if self.human is not None:
            payload["human"] = self.human.as_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DecisionSupervision":
        schema = str(payload.get("schema", ""))
        if schema != SCHEMA:
            raise ValueError(f"unsupported supervision schema {schema!r} (expected {SCHEMA!r})")
        evidence = payload.get("evidence")
        return cls(
            deck=str(payload["deck"]), opponent=str(payload["opponent"]), seed=int(payload["seed"]),
            side=int(payload.get("side", 0)), step_index=int(payload["step_index"]),
            ordinal=int(payload.get("ordinal", 0)), round_number=int(payload.get("round_number", 0)),
            request_type=str(payload["request_type"]),
            options=tuple(
                OptionRef(int(o["index"]), str(o["kind"]), o.get("semantic_key"), str(o.get("text", "")))
                for o in payload["options"]
            ),
            expert_index=int(payload["expert_index"]),
            expert_policy=str(payload.get("expert_policy", "")),
            outcome=None if payload.get("outcome") is None else float(payload["outcome"]),
            text=str(payload.get("text", "")),
            knowledge=tuple(str(v) for v in payload.get("knowledge", ())),
            evidence=None if evidence is None else CounterfactualEvidence.from_dict(evidence),
            provenance=Provenance.from_dict(payload.get("provenance")),
            schema=schema,
            human=None if payload.get("human") is None else HumanSignal.from_dict(payload["human"]),
        )


def write_supervision(path: str | Path, records: Iterable[DecisionSupervision], *, append: bool = False) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a" if append else "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def read_supervision(path: str | Path) -> Iterator[DecisionSupervision]:
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield DecisionSupervision.from_dict(json.loads(line))
