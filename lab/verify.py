"""Check a person's corrections against counterfactual rollouts (VCSD on human feedback).

A correction ("X would have been better than what was played") or an override
("play X instead of the AI's proposal") is an opinion. This module tests it the
same way ``train.evidence`` tests a student's disagreement with an expert: the
stored game is replayed label-only, and at each corrected decision the played
action and the other action are compared by paired rollouts from public-belief
roots (``envs.fork_search``), under stated continuation policies.

The output is ``DecisionSupervision`` records carrying both the ``human`` signal
and the ``evidence``; ``reps.strategy.verdict`` then says whether the rollouts
support the played action, the alternative, or neither. Restrictions are those of
``train.evidence``: ``action`` decisions whose boundary snapshot coincides with the
decision, decks from the scripted pool (the rollouts need their experts), opponent
decklist assumed known. Decisions outside them are reported as skipped, not
estimated. Cost: ``2 * rollouts`` rollout games per checked decision.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from .replay import ReplayPolicy, human_signals
from .session import SessionStore


class _OtherOptionPrior:
    """Puts all prior mass on the option to compare with at the listed steps."""

    def __init__(self, other_by_step: dict[int, int]) -> None:
        self.other_by_step = other_by_step

    def distribution(self, built: Any) -> list[float]:
        count = len(built.context.legal_low_level_codes)
        other = self.other_by_step.get(int(built.context.step_index))
        if other is None or not 0 <= other < count:
            return [1.0 / count] * count
        return [1.0 if i == other else 0.0 for i in range(count)]


def verify_session(store: SessionStore, out_path: str | Path, *, rollouts: int = 12, workers: int = 2,
                   bridge: Any = None, alpha: float = 0.05, min_pairs: int = 8) -> dict[str, Any]:
    from envs.fork_bridge import ForkBridge
    from envs.fork_search import run_search_match
    from eval.stats import outcome_score
    from reps.knowledge import matching_units
    from reps.strategy import (CandidateEstimate, CounterfactualEvidence, DecisionSupervision,
                               Provenance, verdict, write_supervision)
    from train.evidence import INFORMATION_ASSUMPTIONS, default_describer, option_refs

    spec = store.spec()
    decisions = store.decisions()
    played = {(int(d["seat"]), int(d["step"])): int(d["index"]) for d in decisions}
    signals = {key: s for key, s in human_signals(store).items() if s.kind in ("override", "correction")}
    report: dict[str, Any] = {"kind": "verify", "session": store.id, "signals": len(signals),
                              "checked": 0, "skipped": [], "verdicts": {}, "rollouts": int(rollouts)}
    records: list[DecisionSupervision] = []
    own_bridge = bridge is None
    bridge = bridge or ForkBridge(workers=max(1, int(workers)))
    created = _dt.datetime.now().isoformat(timespec="seconds")
    try:
        for seat in (0, 1):
            other_by_step: dict[int, int] = {}
            for (s_seat, step), signal in signals.items():
                if s_seat != seat:
                    continue
                # compare the played action with the *other* one of the pair
                other = signal.rejected_index if signal.kind == "override" else signal.preferred_index
                if other is None or other == played[(seat, step)]:
                    report["skipped"].append({"seat": seat, "step": step, "reason": "no alternative recorded"})
                    continue
                other_by_step[step] = int(other)
            if not other_by_step:
                continue
            captured: list[Any] = []
            policies = [ReplayPolicy(i, [d for d in decisions if int(d["seat"]) == i]) for i in (0, 1)]
            result = run_search_match(
                spec.deck0, spec.deck1, bridge=bridge, seed=int(spec.seed), search_players=(seat,),
                rollouts=int(rollouts), top_k=1,
                rollout_specs=(f"expert:{spec.deck0}", f"expert:{spec.deck1}"),
                base_policies=(policies[0], policies[1]),
                prior_policies=(_OtherOptionPrior(other_by_step), None) if seat == 0
                else (None, _OtherOptionPrior(other_by_step)),
                belief_root=True, belief_samples=int(rollouts),
                search_policy_kwargs={
                    "act_on_search": False, "request_types": ("action",), "require_empty_prefix": True,
                    "verify_inject_key": True,
                    "gate": lambda built, prior, base: int(built.context.step_index) in other_by_step,
                },
                on_decision=lambda player, built, code: captured.append(built) if int(player) == seat else None,
            )
            record = result.record
            fallbacks = record.fallbacks0 if seat == 0 else record.fallbacks1
            if fallbacks or (record.error and "quit" not in str(record.error)):
                report["skipped"].append({"seat": seat, "reason": f"replay failed: {record.error or fallbacks}"})
                continue
            searched = {int(d.ordinal): d for d in result.searches if int(d.player) == seat and d.scores is not None}
            done_steps = set()
            for ordinal, built in enumerate(captured):
                decision = searched.get(ordinal)
                context = built.context
                step = int(context.step_index)
                if decision is None or step not in other_by_step:
                    continue
                base_index = played[(seat, step)]
                if int(decision.base_option) != base_index or other_by_step[step] not in decision.candidates:
                    report["skipped"].append({"seat": seat, "step": step, "reason": "search did not evaluate the pair"})
                    continue
                evidence = CounterfactualEvidence(
                    candidates=tuple(CandidateEstimate(int(o), tuple(decision.scores[o])) for o in decision.candidates),
                    baseline_index=base_index,
                    continuation={"self": f"expert:{spec.deck(seat)}", "opponent": f"expert:{spec.deck(1 - seat)}"},
                    information={"root": "public_belief" if decision.root_kind == "belief" else "true_state",
                                 "belief_roots": int(decision.belief_roots), "empty_prefix": True,
                                 "inject_key_verified": True, "assumptions": list(INFORMATION_ASSUMPTIONS),
                                 "prior_selected": True},
                    rollouts=int(rollouts), base_seed=int(spec.seed), errors=dict(decision.errors or {}),
                )
                describer = default_describer(spec.deck(1 - seat))
                view = context.player_view
                signal = signals[(seat, step)]
                records.append(DecisionSupervision(
                    deck=spec.deck(seat), opponent=spec.deck(1 - seat), seed=int(spec.seed), side=seat,
                    step_index=step, ordinal=ordinal,
                    round_number=int(view.round_number) if view is not None else 0,
                    request_type=context.request_type.value, options=option_refs(context, describer),
                    expert_index=base_index, expert_policy="played",
                    outcome=float(outcome_score(record.winner, seat)) if record.winner is not None else 0.5,
                    text=describer.describe_state(context) if view is not None else "",
                    knowledge=tuple(matching_units(context)), evidence=evidence,
                    provenance=Provenance(source="genshin-gitcg/lab", version="lab.verify/1",
                                          generator="lab.verify/1", created=created,
                                          extra={"session": store.id}),
                    human=signal,
                ))
                status = verdict(evidence, alpha=alpha, min_pairs=min_pairs).status
                # In the person's terms: did the rollouts back their preference?
                prefers_played = signal.kind == "override"
                backed = {"expert_supported": prefers_played, "alternative_supported": not prefers_played}.get(status)
                label = "inconclusive" if backed is None else ("human_supported" if backed else "human_contradicted")
                report["verdicts"][label] = report["verdicts"].get(label, 0) + 1
                done_steps.add(step)
            for step in sorted(set(other_by_step) - done_steps):
                if not any(s.get("step") == step and s.get("seat") == seat for s in report["skipped"]):
                    report["skipped"].append({"seat": seat, "step": step,
                                              "reason": "not an action decision at a clean boundary"})
    finally:
        if own_bridge:
            close = getattr(bridge, "close", None)
            if callable(close):
                close()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report["checked"] = write_supervision(out_path, records)
    report["path"] = str(out_path)
    return report
