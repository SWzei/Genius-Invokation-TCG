"""Adaptive-computation gates: decide *whether* a decision gets search budget.

A gate is a callable ``gate(built, prior_probs, base_idx) -> bool`` plugged into
``ForkSearchPolicy(gate=...)`` (``envs.fork_search``). It sees the decision
context, the prior distribution over the legal options (``None`` when the policy
has no prior) and the index of the base policy's choice. Returning ``False``
skips the search for that decision; the base choice is played as usual.

A gate never changes which actions are legal, which candidates are evaluated
(that is ``top_k`` / the prior), or what the rollouts see. It only allocates
budget, so it cannot leak information the prior did not already have.

Implemented: the two gates below. Not implemented (interface only, see
``docs/howto/masd-adm.md``): learned gates, budget schedules across a game, and
any claim that gating improves strength -- that needs a paired evaluation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Sequence

Gate = Callable[[Any, Sequence[float] | None, int], bool]


@dataclass
class DisagreementGate:
    """Search only where the prior's top action differs from the base action.

    For evidence generation with ``base`` = expert and ``prior`` = a student
    network this selects the student-teacher disagreements -- the decisions where a
    counterfactual comparison can tell the two apart. Without a prior it passes
    nothing unless ``pass_without_prior``.
    """

    pass_without_prior: bool = False
    seen: int = 0
    passed: int = 0

    def __call__(self, built: Any, prior_probs: Sequence[float] | None, base_idx: int) -> bool:
        self.seen += 1
        if prior_probs is None:
            ok = bool(self.pass_without_prior)
        else:
            top = max(range(len(prior_probs)), key=lambda i: (prior_probs[i], -i))
            ok = int(top) != int(base_idx)
        self.passed += int(ok)
        return ok


@dataclass
class PriorUncertaintyGate:
    """Search only where the prior is unsure: small top-2 margin or high entropy.

    ``max_margin``: pass when ``p(top1) - p(top2) <= max_margin``.
    ``min_entropy``: pass when the normalised entropy (0..1) is at least this.
    Either condition passes; set one to ``None`` to disable it. Without a prior
    the gate passes (there is nothing to be confident about).
    """

    max_margin: float | None = 0.2
    min_entropy: float | None = None
    seen: int = 0
    passed: int = 0

    def __call__(self, built: Any, prior_probs: Sequence[float] | None, base_idx: int) -> bool:
        self.seen += 1
        ok = True
        if prior_probs is not None and len(prior_probs) > 1:
            ordered = sorted((float(p) for p in prior_probs), reverse=True)
            margin_ok = self.max_margin is not None and ordered[0] - ordered[1] <= float(self.max_margin)
            total = sum(ordered) or 1.0
            entropy = -sum((p / total) * math.log(p / total) for p in ordered if p > 0)
            entropy_ok = self.min_entropy is not None and entropy / math.log(len(ordered)) >= float(self.min_entropy)
            ok = bool(margin_ok or entropy_ok)
        self.passed += int(ok)
        return ok


def build_gate(spec: str | None) -> Gate | None:
    """``none`` | ``disagreement`` | ``margin:<x>`` | ``entropy:<x>`` -> gate."""
    if spec is None or spec in ("", "none"):
        return None
    name, _, arg = spec.partition(":")
    if name == "disagreement":
        return DisagreementGate()
    if name == "margin":
        return PriorUncertaintyGate(max_margin=float(arg or 0.2), min_entropy=None)
    if name == "entropy":
        return PriorUncertaintyGate(max_margin=None, min_entropy=float(arg or 0.5))
    raise ValueError(f"unknown gate spec {spec!r}")
