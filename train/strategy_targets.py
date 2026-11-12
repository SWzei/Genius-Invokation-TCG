"""Decision-level strategy targets for distillation (MASD-ADM / VCSD training hook).

Turns model-agnostic ``DecisionSupervision`` records into per-sample policy targets
aligned to a training ``Store`` and provides the extra loss term

    L = L_base + distill_coef * (1/B) * sum_i  w_i * KL( pi_k,i || pi_theta,i )

where ``B`` is the batch size and the sum runs over the batch samples that have a
target (``w_i = 0`` elsewhere). ``L_base`` is whatever the trainer already
computes (CE / AWR / PG ...). With one-hot ``pi_k`` the KL equals the cross
entropy on that action, so at a decision whose target differs from the expert's
action ``distill_coef * w`` is the odds the optimum puts on the target against the
expert label. With no targets, or ``distill_coef == 0``, the trainer's loss is
untouched.

Target modes (:class:`TargetSpec`) keep the evidence classes apart:

* ``expert``         -- one-hot on the expert's action (``expert_action``). Adds
  no information beyond BC; it exists to test the plumbing (KL == CE).
* ``evidence_gated`` -- only decisions whose evidence passes the statistical gate
  (``reps.strategy.verdict``): one-hot on the supported action. Inconclusive or
  information-illegal evidence yields **no** target. This is the VCSD default.
* ``evidence_soft``  -- softmax of the candidates' mean rollout outcomes, for every
  information-legal evidence record, gate or not. A raw ``search_estimate`` used
  as a soft label; provided for ablation, not a verified target.

Knowledge-unit annotations (``DecisionSupervision.knowledge``) are deliberately
*not* turned into targets here: a strategy unit's recommendation is unverified
text and has no defined mapping to an option distribution in this code base.

Alignment is by ``DecisionSupervision.store_key`` and is checked: the sample must
have the same number of options and the same expert index as the record, else the
record is dropped (or raises with ``strict=True``).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Sequence

import torch

from reps.strategy import DecisionSupervision, reliability, verdict

MODES = ("expert", "evidence_gated", "evidence_soft")
WEIGHTINGS = ("uniform", "reliability")


@dataclass(frozen=True)
class TargetSpec:
    mode: str = "evidence_gated"
    weighting: str = "reliability"
    alpha: float = 0.05                 # gate level (evidence_gated)
    min_pairs: int = 8                  # gate: paired rollouts required
    temperature: float = 0.25           # evidence_soft: softmax(mean / temperature)
    require_information_legal: bool = True

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"unknown target mode {self.mode!r} (expected one of {MODES})")
        if self.weighting not in WEIGHTINGS:
            raise ValueError(f"unknown weighting {self.weighting!r} (expected one of {WEIGHTINGS})")
        if self.temperature <= 0:
            raise ValueError("temperature must be positive")


@dataclass(frozen=True)
class DecisionTarget:
    probs: tuple[float, ...]      # over the record's options (engine order)
    weight: float
    source: str                   # "expert_action" | "verified:<status>" | "search_estimate"


def target_for(record: DecisionSupervision, spec: TargetSpec) -> DecisionTarget | None:
    """The policy target one record supports under ``spec`` (``None`` = no target)."""
    n = len(record.options)
    if n == 0 or not 0 <= record.expert_index < n:
        return None

    def one_hot(index: int) -> tuple[float, ...]:
        return tuple(1.0 if i == index else 0.0 for i in range(n))

    if spec.mode == "expert":
        return DecisionTarget(one_hot(record.expert_index), 1.0, "expert_action")

    evidence = record.evidence
    if evidence is None:
        return None
    if spec.require_information_legal and not evidence.is_information_legal:
        return None

    if spec.mode == "evidence_gated":
        result = verdict(evidence, alpha=spec.alpha, min_pairs=spec.min_pairs,
                         require_information_legal=spec.require_information_legal)
        if not result.verified or not 0 <= result.option_index < n:
            return None
        weight = result.reliability if spec.weighting == "reliability" else 1.0
        return DecisionTarget(one_hot(result.option_index), float(weight), f"verified:{result.status}")

    # evidence_soft
    means = {c.option_index: c.mean for c in evidence.candidates
             if c.mean is not None and 0 <= c.option_index < n}
    if len(means) < 2:
        return None
    top = max(means.values())
    raw = {i: math.exp((m - top) / spec.temperature) for i, m in means.items()}
    total = sum(raw.values())
    probs = tuple(raw.get(i, 0.0) / total for i in range(n))
    comparisons = evidence.comparisons()
    weight = 1.0
    if spec.weighting == "reliability":
        weight = max((reliability(c) for c in comparisons), default=0.0)
    return DecisionTarget(probs, float(weight), "search_estimate")


@dataclass
class DecisionTargets:
    """Targets aligned to one ``Store`` (positions index into that store)."""

    spec: TargetSpec
    probs: dict[int, torch.Tensor] = field(default_factory=dict)     # position -> (K,)
    weight: dict[int, float] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.probs)

    @classmethod
    def for_store(
        cls,
        store: Any,
        records: Iterable[DecisionSupervision],
        spec: TargetSpec | None = None,
        *,
        strict: bool = False,
    ) -> "DecisionTargets":
        spec = spec or TargetSpec()
        position = {tuple(key): i for i, key in enumerate(store.keys)}
        out = cls(spec=spec)
        n_records = unmatched = mismatched = no_target = duplicate = 0
        sources: dict[str, int] = {}
        changed = 0
        for record in records:
            n_records += 1
            pos = position.get(tuple(record.store_key))
            if pos is None:
                unmatched += 1
                continue
            n_options = int(store.options[pos].shape[0])
            if n_options != len(record.options) or int(store.teacher[pos]) != int(record.expert_index):
                if strict:
                    raise ValueError(
                        f"supervision record {record.store_key} does not describe the stored "
                        f"sample: options {len(record.options)} vs {n_options}, expert "
                        f"{record.expert_index} vs {int(store.teacher[pos])}"
                    )
                mismatched += 1
                continue
            target = target_for(record, spec)
            if target is None or target.weight <= 0.0:
                no_target += 1
                continue
            if pos in out.probs:
                duplicate += 1
                continue
            out.probs[pos] = torch.tensor(target.probs, dtype=torch.float32)
            out.weight[pos] = float(target.weight)
            sources[target.source] = sources.get(target.source, 0) + 1
            changed += int(max(range(n_options), key=lambda i: target.probs[i]) != int(record.expert_index))
        weights = list(out.weight.values())
        out.stats = {
            "spec": asdict(spec),
            "records": n_records,
            "store_samples": len(store.keys),
            "targets": len(out.probs),
            "by_source": dict(sorted(sources.items())),
            "target_differs_from_expert": changed,
            "unmatched_records": unmatched,       # key not in this store (e.g. val split / subsample)
            "mismatched_records": mismatched,     # same key, different decision -> dropped
            "records_without_target": no_target,  # e.g. inconclusive evidence
            "duplicate_records": duplicate,
            "mean_weight": round(sum(weights) / len(weights), 4) if weights else None,
        }
        return out

    def kl_term(self, logits: torch.Tensor, index: Sequence[int]) -> tuple[torch.Tensor, int]:
        """``(1/B) * sum_i w_i * KL(pi_k,i || softmax(logits_i))`` and the supervised count.

        ``index`` are the store positions of the batch rows. Padded options must
        carry ``-inf`` logits (the CVPN heads mask them); targets are zero there.
        """
        rows = [(row, pos) for row, pos in enumerate(index) if pos in self.probs]
        if not rows:
            return logits.new_zeros(()), 0
        width = logits.shape[1]
        target = logits.new_zeros((len(rows), width))
        weight = logits.new_zeros((len(rows),))
        for j, (_row, pos) in enumerate(rows):
            probs = self.probs[pos]
            target[j, : probs.shape[0]] = probs.to(logits.device)
            weight[j] = self.weight[pos]
        logp = torch.log_softmax(logits[[row for row, _pos in rows]], dim=-1)
        positive = target > 0
        safe_target = torch.where(positive, target, torch.ones_like(target))
        safe_logp = torch.where(positive, logp, torch.zeros_like(logp))
        kl = (torch.where(positive, target * (safe_target.log() - safe_logp), torch.zeros_like(target))).sum(dim=-1)
        return (weight * kl).sum() / max(1, len(index)), len(rows)
