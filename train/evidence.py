"""Information-legal counterfactual evidence for expert decisions (MASD-ADM / VCSD).

One *evidence game* replays an ordinary collection game -- same decks, seed, seat
and policy seeds as ``train.data.collect_samples`` -- and, at some of the teacher's
decisions, compares the expert's action with alternative legal actions:

    Q^mu(h, a) ~= mean over R rollouts of  outcome( fork(root_r), inject a, then mu )

* ``root_r`` is a **public-belief determinization** of the last boundary snapshot
  (``reps.belief.sample_belief_roots``): the snapshot is masked to the acting
  player's view and the hidden zones are resampled, so the estimate does not use
  the opponent's true hand/pile/dice or the true order of the player's own pile;
* ``mu`` is the stated continuation policy pair (default: both decks' scripted
  experts) -- the estimate is *relative to mu*, not a game-theoretic value;
* rollout ``r`` uses the same root particle and the same rollout seed for every
  candidate, so differences are paired.

The game itself is **label-only**: the teacher always plays the expert's action
(``ForkSearchPolicy(act_on_search=False)``), so the trajectory is the same game a
plain ``train.collect`` run records and the evidence joins that corpus by
``DecisionSupervision.store_key``. This module reuses ``envs.fork_search`` /
``envs.fork_bridge``; it adds no engine code.

Restrictions (each is recorded in ``CounterfactualEvidence.information``):

* ``action`` decisions only, and only when the boundary snapshot coincides with
  the decision (empty replay prefix). A prefix recorded in the true world need
  not denote the same actions in a determinized one, so those decisions are
  skipped rather than estimated;
* every fork checks that the injected option carries the same semantic key as in
  the live decision; a mismatch discards that rollout (``errors``);
* assumption: the opponent's 30-card list is known to the acting player (open
  decklists, as in tournament play). Without it the estimate would be undefined.

``train.replay_branch`` is *not* used here: it replays the real game and therefore
conditions on the true hidden state.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from common.seeding import derive_seed
from reps.strategy import (
    CandidateEstimate,
    CounterfactualEvidence,
    DecisionSupervision,
    OptionRef,
    Provenance,
    sign_test_pass_probability,
    verdict,
)

GENERATOR = "train.evidence/1"
INFORMATION_ASSUMPTIONS = ("opponent_decklist_known",)


@dataclass(frozen=True)
class EvidenceSpec:
    """One evidence game. Field defaults mirror ``train.collect`` so games align."""

    deck: str
    opponent: str
    seed: int
    side: int = 0
    rollouts: int = 8
    # Alternatives per decision besides the expert's action: the ``top_k``
    # highest-prior options when a prior is given, otherwise an even spread.
    top_k: int | None = 1
    max_searches: int | None = None
    # Consider only every N-th teacher decision (spreads a budget over the game).
    search_every: int = 1
    teacher_spec: str | None = None
    opponent_spec: str | None = None
    # Continuation policies mu as (teacher side, opponent side); ``None`` = that
    # deck's scripted expert.
    continuation: tuple[str | None, str | None] = (None, None)
    max_steps: int = 5000
    # Also emit a record (expert action + options + knowledge, no evidence) for
    # teacher decisions that were not searched.
    include_unsearched: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "deck": self.deck, "opponent": self.opponent, "seed": int(self.seed),
            "side": int(self.side), "rollouts": int(self.rollouts), "top_k": self.top_k,
            "max_searches": self.max_searches, "search_every": int(self.search_every),
            "teacher_spec": self.teacher_spec,
            "opponent_spec": self.opponent_spec, "continuation": list(self.continuation),
            "max_steps": int(self.max_steps), "include_unsearched": bool(self.include_unsearched),
        }


@dataclass
class EvidenceGame:
    spec: EvidenceSpec
    supervision: list[DecisionSupervision]
    winner: int | None
    error: str | None
    teacher_decisions: int
    searched: int
    wall_seconds: float
    # (step_index, option_count, expert_index) of every teacher decision, for
    # checking that the game is the one a plain collection run records.
    trace: list[tuple[int, int, int]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.spec.as_dict(), "winner": self.winner, "error": self.error,
            "teacher_decisions": self.teacher_decisions, "searched": self.searched,
            "records": len(self.supervision), "wall_seconds": round(self.wall_seconds, 2),
        }


def _json_key(key: Any) -> Any:
    if isinstance(key, (list, tuple)):
        return [_json_key(v) for v in key]
    if isinstance(key, (str, int, float, bool)) or key is None:
        return key
    return str(getattr(key, "value", key))


def option_refs(context: Any, describer: Any = None) -> tuple[OptionRef, ...]:
    """Legal options of a decision as model-agnostic references (engine order)."""
    from reps.action_hierarchy import semantic_action_key_for_spec

    refs = []
    for index, spec in enumerate(context.legal_low_level_specs):
        text = ""
        if describer is not None:
            try:
                text = describer.describe_candidate(context, spec, index)
            except Exception:
                text = ""
        refs.append(OptionRef(index=index, kind=str(spec.kind.value),
                              semantic_key=_json_key(semantic_action_key_for_spec(spec)), text=text))
    return tuple(refs)


def default_describer(opponent_name: str = "unknown") -> Any:
    """Text renderer over the acting player's view (``agents.llm_assist``)."""
    from agents.llm_assist import ContextDescriber
    from envs.policy import _asset_catalog

    return ContextDescriber(_asset_catalog(), opponent_name=opponent_name)


def collect_evidence_game(
    spec: EvidenceSpec,
    *,
    bridge: Any,
    prior: Any = None,
    gate: Callable[..., bool] | None = None,
    describer: Any = None,
    annotate: Callable[[Any], Sequence[str]] | None = None,
    provenance_extra: Mapping[str, Any] | None = None,
) -> EvidenceGame:
    """Play one label-only evidence game and return its supervision records.

    ``prior`` (``distribution(built)``, e.g. ``train.resolver.PriorResolver``) only
    *selects* which alternatives are evaluated; ``gate(built, prior_probs,
    base_idx)`` (``envs.adaptive``) only decides *whether* a decision is evaluated.
    Neither can change what is played. ``annotate(context)`` returns knowledge-unit
    ids for a decision (``reps.knowledge.matching_units``).
    """
    from envs.fork_search import run_search_match
    from eval.stats import outcome_score
    from envs.policy import build_policy

    side = int(spec.side)
    if side not in (0, 1):
        raise ValueError(f"side must be 0 or 1, got {spec.side!r}")
    # Same roles / seed derivation as train.data.collect_samples.
    teacher_role, opponent_role = ("p0", "p1") if side == 0 else ("p1", "p0")
    teacher_spec = spec.teacher_spec or f"expert:{spec.deck}"
    opponent_spec = spec.opponent_spec or f"expert:{spec.opponent}"
    teacher = build_policy(teacher_spec, seed=derive_seed(spec.seed, teacher_role, spec.deck), role=teacher_role)
    opponent = build_policy(opponent_spec, seed=derive_seed(spec.seed, opponent_role, spec.opponent), role=opponent_role)
    continuation = {
        "self": spec.continuation[0] or f"expert:{spec.deck}",
        "opponent": spec.continuation[1] or f"expert:{spec.opponent}",
    }
    if side == 0:
        deck0, deck1, bases = spec.deck, spec.opponent, (teacher, opponent)
        rollout_specs = (continuation["self"], continuation["opponent"])
    else:
        deck0, deck1, bases = spec.opponent, spec.deck, (opponent, teacher)
        rollout_specs = (continuation["opponent"], continuation["self"])

    captured: list[tuple[Any, int]] = []

    def _sink(player: int, built: Any, code: int) -> None:
        if int(player) == side:
            captured.append((built, int(code)))

    result = run_search_match(
        deck0, deck1,
        bridge=bridge,
        seed=int(spec.seed),
        search_players=(side,),
        rollouts=int(spec.rollouts),
        top_k=spec.top_k,
        max_searches=spec.max_searches,
        search_every=max(1, int(spec.search_every)),
        rollout_specs=rollout_specs,
        max_steps=int(spec.max_steps),
        base_policies=bases,
        prior_policies=(prior, None) if side == 0 else (None, prior),
        belief_root=True,
        belief_samples=int(spec.rollouts),
        search_policy_kwargs={
            "act_on_search": False,
            "request_types": ("action",),
            "require_empty_prefix": True,
            "verify_inject_key": True,
            "gate": gate,
        },
        on_decision=_sink,
    )
    record = result.record
    game = EvidenceGame(
        spec=spec, supervision=[], winner=record.winner, error=record.error,
        teacher_decisions=len(captured), searched=0, wall_seconds=float(record.wall_seconds),
    )
    for built, code in captured:
        codes = [int(c) for c in built.context.legal_low_level_codes]
        game.trace.append((int(built.context.step_index), len(codes),
                           codes.index(code) if code in codes else -1))
    fallbacks = record.fallbacks0 if side == 0 else record.fallbacks1
    if record.error or record.truncated or fallbacks:
        # A game that errored, was cut off or needed a fallback action is not the
        # game a collection run records; emit nothing rather than misaligned rows.
        game.error = record.error or ("truncated" if record.truncated else f"fallbacks={fallbacks}")
        return game

    outcome = float(outcome_score(record.winner, side))
    created = _dt.datetime.now().isoformat(timespec="seconds")
    searched = {int(d.ordinal): d for d in result.searches if int(d.player) == side and d.scores is not None}
    game.searched = len(searched)
    for ordinal, (built, code) in enumerate(captured):
        decision = searched.get(ordinal)
        if decision is None and not spec.include_unsearched:
            continue
        context = built.context
        codes = [int(c) for c in context.legal_low_level_codes]
        if code not in codes:
            continue
        expert_index = codes.index(code)
        evidence = None
        if decision is not None:
            if int(decision.base_option) != expert_index or int(decision.option_count) != len(codes):
                raise RuntimeError(
                    f"search log out of step with the game at ordinal {ordinal}: "
                    f"base={decision.base_option}/{decision.option_count} vs "
                    f"expert={expert_index}/{len(codes)}"
                )
            evidence = CounterfactualEvidence(
                candidates=tuple(
                    CandidateEstimate(int(option), tuple(decision.scores[option]))
                    for option in decision.candidates
                ),
                baseline_index=expert_index,
                continuation=continuation,
                information={
                    "root": "public_belief" if decision.root_kind == "belief" else "true_state",
                    "belief_roots": int(decision.belief_roots),
                    "empty_prefix": True,           # enforced by require_empty_prefix
                    "inject_key_verified": True,
                    "assumptions": list(INFORMATION_ASSUMPTIONS),
                    "prior_selected": decision.prior is not None,
                },
                rollouts=int(spec.rollouts),
                base_seed=int(spec.seed),
                errors=dict(decision.errors or {}),
            )
        view = context.player_view
        text = ""
        if describer is not None and view is not None:
            try:
                text = describer.describe_state(context)
            except Exception:
                text = ""
        game.supervision.append(
            DecisionSupervision(
                deck=spec.deck, opponent=spec.opponent, seed=int(spec.seed), side=side,
                step_index=int(context.step_index), ordinal=ordinal,
                round_number=int(view.round_number) if view is not None else 0,
                request_type=str(context.request_type.value),
                options=option_refs(context, describer),
                expert_index=expert_index,
                expert_policy=teacher_spec,
                outcome=outcome,
                text=text,
                knowledge=tuple(annotate(context)) if annotate is not None else (),
                evidence=evidence,
                provenance=Provenance(
                    source="genshin-gitcg/evidence", version=GENERATOR, generator=GENERATOR,
                    created=created, extra=dict(provenance_extra or {}),
                ),
            )
        )
    return game


def summarize(records: Sequence[DecisionSupervision], *, alpha: float = 0.05, min_pairs: int = 8) -> dict[str, Any]:
    """Counts for a report: how much evidence, how much of it passes the gate.

    ``expected_by_chance`` is the number of comparisons that would pass the gate if
    every alternative were exactly as good as the expert's action: the sum, over
    gate-eligible comparisons, of the exact pass probability given that
    comparison's number of discordant pairs (``sign_test_pass_probability``). A
    verified count near it carries no information. ``can_pass`` counts the
    decisions that had enough discordant pairs to pass at all.
    """
    with_evidence = [r for r in records if r.evidence is not None]
    status: dict[str, int] = {"expert_supported": 0, "alternative_supported": 0, "inconclusive": 0}
    legal = eligible = rollouts = errors = can_pass = no_discordant = 0
    by_chance = 0.0
    diffs: list[float] = []
    for record in with_evidence:
        evidence = record.evidence
        assert evidence is not None
        legal += int(evidence.is_information_legal)
        rollouts += sum(c.n for c in evidence.candidates)
        errors += sum(int(v) for v in evidence.errors.values())
        comparisons = evidence.comparisons()
        if comparisons and evidence.is_information_legal and all(c.n_pairs >= min_pairs for c in comparisons):
            eligible += 1
            chances = [sign_test_pass_probability(c.wins + c.losses, alpha) for c in comparisons]
            by_chance += sum(chances)
            can_pass += int(any(chance > 0 for chance in chances))
            no_discordant += int(all(c.wins + c.losses == 0 for c in comparisons))
        diffs.extend(c.mean_diff for c in comparisons)
        status[verdict(evidence, alpha=alpha, min_pairs=min_pairs).status] += 1
    verified = status["expert_supported"] + status["alternative_supported"]
    return {
        "records": len(records),
        "with_evidence": len(with_evidence),
        "information_legal": legal,
        "gate": {"alpha": alpha, "min_pairs": min_pairs, "test": "exact two-sided sign test"},
        "gate_eligible": eligible,
        "verdicts": status,
        "verified": verified,
        "expected_by_chance": round(by_chance, 3),
        "can_pass": can_pass,
        "no_discordant_pair": no_discordant,
        "valid_rollouts": rollouts,
        "discarded_rollouts": errors,
        "mean_abs_dq": round(sum(abs(d) for d in diffs) / len(diffs), 4) if diffs else None,
        "knowledge_annotated": sum(1 for r in records if r.knowledge),
    }
