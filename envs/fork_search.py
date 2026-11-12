"""Fork-based search policy + driver (PLAN.md WS3, M3 "实用版 continual resolving").

This is the practical resolver: at a decision point it evaluates candidate actions
by forking the last ``is_resumable()`` boundary snapshot (``envs.fork_bridge``),
injecting each candidate, rolling out with a fixed policy, and averaging the
outcome. It is the online counterpart of ``train.replay_branch``'s offline
replay-branch MC teacher -- same idea, O(1) fork instead of O(depth) replay.

Anchoring the search to a boundary
----------------------------------
A decision is delivered from *inside* ``game.step()``, so no boundary snapshot
exists at that moment. The driver therefore snapshots after every step while the
game reports ``is_resumable()`` and remembers how many decisions each player had
made at that point. A candidate task then forks that snapshot and replays the
decisions since it (the *prefix*) before injecting -- the record-replay contract
verified in ``reports/engine/probe_boundary_fork_*`` (I10). The initial state is
used as the first boundary: it is a complete state, so a fork from it reproduces
the live game (verified; unlike mid-phase ``canResume:false`` pauses).

Safety of the search
--------------------
The base policy is consulted once per decision regardless of whether the search
runs, so the expert's own RNG advances exactly as it would without search. Its
choice is always one of the evaluated candidates, so a search with enough
rollouts cannot be surprised into ignoring the expert action.

CVPN integration (prior + rollout)
----------------------------------
``ForkSearchPolicy.prior`` is an optional scorer exposing
``distribution(built) -> Sequence[float]`` over the legal options (e.g.
``train.resolver.PriorResolver`` around a CVPN checkpoint). When set, ``top_k``
selects the highest-prior options (instead of an even spread) -- the network prior
*ranks* candidates, it does not delete options from the reachable set (the base
choice is always kept; the charter's "prior is an ordering signal, not a deletion
rule", §5.4). ``base`` and the rollout policies can themselves be the network
(``neural:<ckpt>`` specs), so both the leaf rollout and the prior can be CVPN.

Cost is ``candidates x rollouts`` full games per searched decision; ``top_k`` and
``search_every`` bound it. Every decision is logged (``SearchDecision``) for the
coach/teacher and for distillation features.

Public-belief rooting (M3-CPU S-A, gaps G1+G3)
---------------------------------------------
By default the search root is the live boundary snapshot, i.e. the *single true*
determinization of the opponent's hidden hand/pile/dice -- a GT-CFR charter
§5.2 violation. With ``belief_root=True`` the root for each fork is instead a
**determinized** snapshot reconstructed by ``reps.belief.sample_belief_roots``:
the boundary is masked to the acting player's public view, a particle is sampled
from the public belief (known decklist, public hand/dice counts), and the hidden
zones are overwritten with that particle (hidden entity ids are synthetic, so no
identity/ordering of the true cards survives). ``belief_samples`` roots are
sampled and distributed across rollouts, so the search averages over hidden
states consistent with what the acting player can actually observe. This is the
CPU-tier precondition for the sampled GT-CFR solver (``train/cfr_solver.py``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from gitcg import Game, GameStatus

from common.seeding import derive_seed
from envs.decks import deck_spec
from envs.fork_bridge import ForkBridge, ForkTask
from envs.match import MatchRecord, PolicyPlayer, _build_create_param
from envs.policy import Policy, build_policy
from envs.snapshot import capture_snapshot


@dataclass
class SearchDecision:
    """One searched decision's outcome (also feeds the coach / distillation)."""

    player: int
    ordinal: int
    request_type: str
    option_count: int
    base_option: int
    candidates: tuple[int, ...]
    means: dict[int, float]
    counts: dict[int, int]
    chosen_option: int
    searched: bool
    prior: dict[int, float] | None = None
    belief_roots: int = 1
    # 2026-11 (MASD-ADM evidence). ``scores[option][r]`` is the outcome of
    # rollout ``r`` for that option (``None`` = that fork errored). Rollout ``r``
    # uses the same root particle and the same rollout seed for every option,
    # so ``scores[a][r] - scores[b][r]`` is a paired (common-random-number)
    # difference. ``errors`` counts discarded forks by reason.
    scores: dict[int, tuple[float | None, ...]] | None = None
    errors: dict[str, int] | None = None
    root_kind: str = "live"
    acted_on: bool = True

    def as_dict(self) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        if self.scores is not None:
            extra = {
                "scores": {str(k): list(v) for k, v in self.scores.items()},
                "errors": dict(self.errors or {}),
                "root_kind": self.root_kind,
                "acted_on": bool(self.acted_on),
            }
        return {
            **extra,
            "player": self.player,
            "ordinal": self.ordinal,
            "request_type": self.request_type,
            "option_count": self.option_count,
            "base_option": self.base_option,
            "candidates": list(self.candidates),
            "means": {str(k): v for k, v in self.means.items()},
            "counts": {str(k): v for k, v in self.counts.items()},
            "chosen_option": self.chosen_option,
            "searched": self.searched,
            "prior": None if self.prior is None else {str(k): v for k, v in self.prior.items()},
            "belief_roots": int(self.belief_roots),
        }


@dataclass
class SearchContext:
    """Mutable state shared between the driver loop and the search policies."""

    bridge: ForkBridge
    game_attrs: Mapping[int, int]
    rollout_specs: tuple[str | None, str | None]
    base_seed: int
    records: list[list[int]] = field(default_factory=lambda: [[], []])
    boundary: tuple[str, int, int] | None = None
    searches: list[SearchDecision] = field(default_factory=list)
    # M3-CPU S-A: public-belief rooting. When ``belief_root`` is on the search
    # root is a *determinized* boundary snapshot (public belief + sampled
    # particle) instead of the live snapshot's single true hidden state. Roots
    # are cached per (boundary snapshot, acting player) since they only depend
    # on the public view.
    belief_root: bool = False
    belief_samples: int = 1
    deck_cards: tuple[tuple[int, ...], tuple[int, ...]] = ((), ())
    # Per-player public-action trackers (populated by ``run_search_match`` when
    # ``belief_root`` is on). They let the opponent range subtract cards the
    # opponent has *publicly revealed* from the known decklist; without them the
    # sampled hand/pile would always total the whole 30-card deck.
    trackers: tuple[Any, Any] = (None, None)

    def belief_roots_for(self, *, snapshot: str, acting_player: int) -> list[str]:
        cache = self._belief_roots_cache.setdefault((snapshot, int(acting_player)), None)
        if cache is None:
            opponent_player = 1 - int(acting_player)
            deck_cards = self.deck_cards[opponent_player]
            if not deck_cards:
                # No opponent decklist -> determinization is undefined; degrade to
                # the live snapshot instead of sampling an empty hand/pile.
                cache = [snapshot]
            else:
                from reps.belief import sample_belief_roots

                cache = sample_belief_roots(
                    snapshot,
                    root_player=int(acting_player),
                    opponent_deck_cards=deck_cards,
                    samples=max(1, int(self.belief_samples)),
                    tracker=self.trackers[int(acting_player)],
                )
            self._belief_roots_cache[(snapshot, int(acting_player))] = cache
        return cache

    _belief_roots_cache: dict[tuple[str, int], list[str]] = field(
        default_factory=dict, init=False, repr=False
    )

    def prefix(self, player: int) -> tuple[int, ...]:
        if self.boundary is None:
            return ()
        base = self.boundary[1] if player == 0 else self.boundary[2]
        return tuple(self.records[player][base:])

    def update_boundary(self, snapshot: str) -> None:
        self.boundary = (snapshot, len(self.records[0]), len(self.records[1]))


def _select_candidates(
    option_count: int,
    top_k: int | None,
    *,
    prior: Sequence[float] | None = None,
    required: int | None = None,
) -> list[int]:
    """Pick candidate option indices.

    With ``prior`` (a score/policy over the options) the ``top_k`` highest-prior
    options are chosen; otherwise an even spread of ``top_k`` indices. ``required``
    (e.g. the base policy's choice) is always included. The result is sorted.
    """
    if option_count <= 0:
        return []
    if top_k is None or top_k >= option_count:
        keep = list(range(option_count))
    elif prior is not None:
        keep = sorted(range(option_count), key=lambda i: (-float(prior[i]), i))[
            : max(0, int(top_k))
        ]
    elif top_k <= 1:
        keep = [0]
    else:
        keep = sorted({round(i * (option_count - 1) / (top_k - 1)) for i in range(top_k)})
    if required is not None:
        keep.append(int(required))
    return sorted(set(keep))


@dataclass
class ForkSearchPolicy:
    """A ``Policy`` that refines the base choice with fork-based MC evaluation."""

    player: int
    context: SearchContext
    deck0: str = ""
    deck1: str = ""
    base: Policy | None = None
    prior: Any = None
    rollouts: int = 1
    top_k: int | None = 4
    search_every: int = 1
    max_searches: int | None = None
    max_steps: int = 5000
    belief_root: bool = False
    belief_samples: int = 1
    name: str = field(default="fork_search")
    # --- 2026-11 additive knobs (defaults reproduce the historical policy) -----
    # ``act_on_search=False``: label-only -- evaluate the candidates and log the
    # ``SearchDecision`` but always play the base choice (evidence generation).
    act_on_search: bool = True
    # Restrict searching to these request types (``None`` = all, as before).
    request_types: tuple[str, ...] | None = None
    # Skip decisions whose fork would have to replay decisions made since the
    # boundary snapshot. Under a belief root those prefix indices were recorded
    # in the *true* world and need not denote the same actions in a determinized
    # one; an empty prefix makes the fork start exactly at this decision.
    require_empty_prefix: bool = False
    # Verify, inside each fork, that the injected option carries the same
    # semantic key as in the live decision (``ForkTask.inject_key``).
    verify_inject_key: bool = False
    # Optional adaptive-budget hook: ``gate(built, prior_probs, base_idx) -> bool``;
    # ``False`` skips the search for this decision (``envs.adaptive``).
    gate: Any = None
    _calls: int = field(default=0, init=False, repr=False)
    _n_searched: int = field(default=0, init=False, repr=False)
    _n_gated: int = field(default=0, init=False, repr=False)

    @property
    def _default_rollout(self) -> str:
        return "legal_random"

    def _rollout_spec(self) -> str:
        spec = self.context.rollout_specs[self.player]
        return spec or self._default_rollout

    def _opp_rollout_spec(self) -> str:
        opp = 1 - self.player
        spec = self.context.rollout_specs[opp]
        return spec or self._default_rollout

    def _prior_distribution(self, built, option_count: int) -> list[float] | None:
        if self.prior is None or not hasattr(self.prior, "distribution"):
            return None
        dist = list(self.prior.distribution(built))
        if len(dist) != option_count:
            return None
        return [float(value) for value in dist]

    def choose(self, built) -> int:
        codes = [int(c) for c in built.context.legal_low_level_codes]
        if not codes:
            return -1
        self._calls += 1

        prior_probs: list[float] | None = None
        if self.prior is not None and self.prior is self.base:
            # Prior *is* the base network: one forward, base choice = prior argmax.
            prior_probs = self._prior_distribution(built, len(codes))
        if prior_probs is not None:
            base_idx = max(range(len(codes)), key=lambda i: prior_probs[i])
            base_code = int(codes[base_idx])
        else:
            base_code = int(self.base.choose(built)) if self.base is not None else codes[0]
            base_idx = codes.index(base_code) if base_code in codes else 0
            if self.prior is not None:
                prior_probs = self._prior_distribution(built, len(codes))

        if (
            self.context.boundary is None
            or len(codes) == 1
            or self.rollouts < 1
            or (self.search_every > 1 and self._calls % self.search_every != 0)
            or (self.max_searches is not None and self._n_searched >= self.max_searches)
        ):
            return base_code
        if self.request_types is not None:
            request_type = str(getattr(built.context.request_type, "value", built.context.request_type))
            if request_type not in self.request_types:
                return base_code
        if self.require_empty_prefix and (
            self.context.prefix(self.player) or self.context.prefix(1 - self.player)
        ):
            return base_code
        if self.gate is not None and not self.gate(built, prior_probs, base_idx):
            self._n_gated += 1
            return base_code

        self._n_searched += 1
        chosen_code = self._search(built, codes, base_idx, prior_probs)
        return chosen_code if self.act_on_search else base_code

    def _search(
        self,
        built,
        codes: list[int],
        base_idx: int,
        prior_probs: list[float] | None,
    ) -> int:
        context = self.context
        snapshot = context.boundary[0]  # type: ignore[index]
        acting = self.player
        if self.belief_root:
            root_snapshots = context.belief_roots_for(snapshot=snapshot, acting_player=acting)
            if not root_snapshots:
                root_snapshots = [snapshot]
        else:
            root_snapshots = [snapshot]
        ordinal = len(context.records[acting])  # decisions before this one
        prefix_self = context.prefix(acting)
        prefix_opp = context.prefix(1 - acting)

        candidates = _select_candidates(
            len(codes), self.top_k, prior=prior_probs, required=base_idx
        )

        roll_spec = self._rollout_spec()
        opp_spec = self._opp_rollout_spec()
        rollout0, rollout1 = (roll_spec, opp_spec) if acting == 0 else (opp_spec, roll_spec)

        ordinal_inject = len(prefix_self) + 1
        inject_keys: dict[int, Any] = {}
        if self.verify_inject_key:
            from reps.action_hierarchy import semantic_action_key_for_spec

            from envs.fork_bridge import legal_keys_digest

            specs = tuple(built.context.legal_low_level_specs)
            legal = legal_keys_digest(specs)
            inject_keys = {
                option: {"option": semantic_action_key_for_spec(specs[option]), "legal": legal}
                for option in candidates
                if option < len(specs)
            }
        tasks: list[ForkTask] = []
        index_map: dict[int, int] = {}
        rollout_of: dict[int, int] = {}
        order: list[int] = []
        for option in candidates:
            for r in range(self.rollouts):
                task_index = len(order)
                order.append(option)
                index_map[task_index] = option
                rollout_of[task_index] = r
                rollout_seed = derive_seed(
                    context.base_seed, "fork-search", acting, ordinal, r
                )
                tasks.append(
                    ForkTask(
                        index=task_index,
                        snapshot=root_snapshots[r % len(root_snapshots)],
                        game_attrs=dict(context.game_attrs),
                        deck0=self.deck0,
                        deck1=self.deck1,
                        prefix0=prefix_self if acting == 0 else prefix_opp,
                        prefix1=prefix_self if acting == 1 else prefix_opp,
                        inject_player=acting,
                        inject_ordinal=ordinal_inject,
                        inject_option=option,
                        rollout0=rollout0,
                        rollout1=rollout1,
                        rollout_seed=rollout_seed,
                        max_steps=self.max_steps,
                        inject_key=inject_keys.get(option),
                    )
                )

        results = context.bridge.evaluate(tasks)
        scores: dict[int, list[float]] = {option: [] for option in candidates}
        # Per-rollout record (paired across options by rollout index ``r``).
        per_rollout: dict[int, list[float | None]] = {
            option: [None] * int(self.rollouts) for option in candidates
        }
        errors: dict[str, int] = {}
        for result in results:
            option = index_map.get(result.index)
            if option is None:
                continue
            if getattr(result, "error", None) and self.verify_inject_key:
                # Evidence mode: an errored/misaligned fork is discarded, never
                # scored (the historical path below scores it as-is).
                reason = str(result.error).split(":", 1)[0]
                errors[reason] = errors.get(reason, 0) + 1
                continue
            value = result.outcome(acting)
            scores[option].append(value)
            per_rollout[option][rollout_of[result.index]] = float(value)

        means = {o: (sum(v) / len(v) if v else 0.0) for o, v in scores.items()}
        counts = {o: len(v) for o, v in scores.items()}
        if means:
            best = min(means, key=lambda o: (-means[o], 0 if o == base_idx else 1, o))
        else:
            best = base_idx
        chosen_code = int(codes[best])

        context.searches.append(
            SearchDecision(
                player=acting,
                ordinal=ordinal,
                request_type=getattr(built.context.request_type, "value", str(built.context.request_type)),
                option_count=len(codes),
                base_option=base_idx,
                candidates=tuple(candidates),
                means=means,
                counts=counts,
                chosen_option=best,
                searched=True,
                belief_roots=len(root_snapshots),
                prior=None
                if prior_probs is None
                else {opt: prior_probs[opt] for opt in candidates},
                scores={option: tuple(values) for option, values in per_rollout.items()},
                errors=errors,
                root_kind="belief" if (self.belief_root and root_snapshots != [snapshot]) else "live",
                acted_on=bool(self.act_on_search),
            )
        )
        self._on_searched(built, context.searches[-1])
        return chosen_code

    def _on_searched(self, built, decision: "SearchDecision") -> None:
        """Hook for subclasses that need the decision context of a search."""


def _observe_public_record(tracker: Any, player: int, built: Any, code: int) -> None:
    """Feed one live decision into a ``PublicStateTracker`` (belief rooting).

    Mirrors ``PublicStateTracker.observe_step`` from a ``BuiltDecisionContext``:
    the tracker only needs the public action record (acting player, request type,
    chosen semantic key, spent dice) to subtract cards the opponent has revealed
    from the sampled hand/pile.
    """
    from reps.action_hierarchy import (
        public_spent_dice_for_spec,
        semantic_action_key_for_spec,
        try_public_spent_dice_for_code,
        try_semantic_action_key_for_code,
    )
    from reps.public_state import PublicActionRecord
    from reps.schema import DecisionType

    context = built.context
    codes = [int(c) for c in context.legal_low_level_codes]
    specs = context.legal_low_level_specs
    selected_index = None
    for index, candidate in enumerate(codes):
        if candidate == int(code):
            selected_index = index
            break
    spec = specs[selected_index] if selected_index is not None and selected_index < len(specs) else None
    if spec is not None:
        semantic_key = semantic_action_key_for_spec(spec)
        used_dice_count = int(public_spent_dice_for_spec(spec))
        option_kind = spec.kind.value
    else:
        # No matching spec (e.g. an inner policy returned a code outside the
        # legal list): fall back to the canonical code lookup, exactly as
        # PublicStateTracker.observe_step does.
        semantic_key = try_semantic_action_key_for_code(int(code))
        used_dice_count = int(try_public_spent_dice_for_code(int(code)) or 0)
        option_kind = None
    view = context.player_view
    request_type = context.request_type
    # observe_step marks the payload known for the acting player's own decisions
    # as well as for public action / choose-active requests.
    known = int(player) == int(tracker.player_id) or request_type in {
        DecisionType.ACTION,
        DecisionType.CHOOSE_ACTIVE,
    }
    tracker.observe_public_record(
        PublicActionRecord(
            acting_player=int(player),
            request_type=request_type,
            round_number=int(view.round_number) if view is not None else 0,
            phase=str(view.phase) if view is not None else "",
            payload={"action_code": int(code)} if known else None,
            semantic_key=semantic_key,
            option_kind=option_kind,
            used_dice_count=used_dice_count,
            known_payload=known,
            selected_legal_index=selected_index,
            legal_option_count=len(codes),
        )
    )


class _RecordingPolicy:
    """Outer policy wrapper recording each decision's positional option index."""

    def __init__(
        self,
        inner: Policy,
        player: int,
        records: list[list[int]],
        *,
        on_decision: Any = None,
    ) -> None:
        self.inner = inner
        self.player = int(player)
        self.records = records
        self.on_decision = on_decision
        self.name = f"record:{getattr(inner, 'name', '?')}"

    def choose(self, built) -> int:
        codes = [int(c) for c in built.context.legal_low_level_codes]
        code = int(self.inner.choose(built))
        idx = codes.index(code) if code in codes else (-1 if codes else 0)
        self.records[self.player].append(idx)
        if self.on_decision is not None:
            self.on_decision(self.player, built, code)
        return code


@dataclass
class SearchMatchResult:
    """A search match's record plus the per-decision search log."""

    record: MatchRecord
    searches: list[SearchDecision]

    @property
    def winner(self) -> int | None:
        return self.record.winner

    def as_dict(self, *, include_searches: bool = False) -> dict[str, Any]:
        payload = self.record.as_dict()
        payload["searched_decisions"] = len(self.searches)
        if include_searches:
            payload["searches"] = [s.as_dict() for s in self.searches]
        return payload


def run_search_match(
    deck0: str,
    deck1: str,
    *,
    bridge: ForkBridge,
    seed: int,
    search_players: Sequence[int] = (0,),
    rollouts: int = 1,
    top_k: int | None = 4,
    search_every: int = 1,
    max_searches: int | None = None,
    rollout_specs: tuple[str | None, str | None] | None = None,
    game_attrs: Mapping[int, int] | None = None,
    max_steps: int = 5000,
    version: str | None = None,
    base_policies: tuple[Policy | None, Policy | None] | None = None,
    prior_policies: tuple[Any | None, Any | None] | None = None,
    record_final_state: bool = False,
    belief_root: bool = False,
    belief_samples: int = 1,
    search_policy_cls: Any = None,
    search_policy_kwargs: Mapping[str, Any] | None = None,
    on_decision: Any = None,
) -> SearchMatchResult:
    """Play one game in which ``search_players`` refine their moves with fork search.

    ``search_policy_cls``/``search_policy_kwargs`` (2026-11) let a caller swap in a
    ``ForkSearchPolicy`` subclass or set its additive knobs (label-only evidence,
    request-type filter, gate); ``on_decision(player, built, code)`` observes every
    live decision. All three default to the historical behaviour.

    Non-search players use an expert policy for their own deck; search players use
    their base policy plus fork search. ``prior_policies`` (per player) are optional
    scorers with ``distribution(built)`` (e.g. ``train.resolver.PriorResolver`` over
    a CVPN) that rank the candidates; ``rollout_specs`` may be ``neural:<ckpt>``.
    Decisions are recorded as positional option indices so the fork tasks replay
    exactly.
    """
    from reps.action_hierarchy import reset_default_hierarchical_action_codebook

    if bridge.workers == 0:
        raise ValueError(
            "run_search_match needs a subprocess fork bridge (workers >= 1): "
            "forking inside a live game callback corrupts the engine's JS runtime. "
            "ForkBridge(workers=0) is only for offline fork tasks."
        )
    reset_default_hierarchical_action_codebook()
    spec0, spec1 = deck_spec(deck0), deck_spec(deck1)
    create_param = _build_create_param(spec0, spec1, seed=seed, version=version)
    game = Game(create_param=create_param)
    attrs = dict(game_attrs or {})
    for attr, value in attrs.items():
        game.set_attr(int(attr), int(value))

    overrides = base_policies or (None, None)
    priors = prior_policies or (None, None)
    search_set = set(int(p) for p in search_players)
    rollout_specs = rollout_specs or (None, None)
    # Public-belief rooting needs a public-action tracker per player so the
    # opponent range can subtract cards the opponent has already revealed.
    from reps.public_state import PublicStateTracker

    trackers: tuple[Any, Any] = (None, None)
    if belief_root:
        trackers = (PublicStateTracker(player_id=0), PublicStateTracker(player_id=1))

    def _on_decision(player: int, built: Any, code: int) -> None:
        for tracker in trackers:
            if tracker is not None:
                _observe_public_record(tracker, player, built, code)
        if on_decision is not None:
            on_decision(player, built, code)

    context = SearchContext(
        bridge=bridge,
        game_attrs=attrs,
        rollout_specs=_normalize_rollout_specs(rollout_specs, deck0, deck1),
        base_seed=int(seed),
        belief_root=bool(belief_root),
        belief_samples=max(1, int(belief_samples)),
        deck_cards=(
            tuple(int(card) for card in spec0.cards),
            tuple(int(card) for card in spec1.cards),
        ),
        trackers=trackers,
    )

    policies: list[Policy] = []
    for player, deck_slug in ((0, deck0), (1, deck1)):
        base = overrides[player]
        if base is None:
            base = build_policy(f"expert:{deck_slug}", seed=derive_seed(seed, f"p{player}", "search-base"), role=f"p{player}")
        if player in search_set:
            policy: Policy = (search_policy_cls or ForkSearchPolicy)(
                **dict(search_policy_kwargs or {}),
                player=player,
                context=context,
                deck0=deck0,
                deck1=deck1,
                base=base,
                prior=priors[player],
                rollouts=rollouts,
                top_k=top_k,
                search_every=search_every,
                max_searches=max_searches,
                max_steps=max_steps,
                belief_root=bool(belief_root),
                belief_samples=max(1, int(belief_samples)),
            )
        else:
            policy = base
        policies.append(
            _RecordingPolicy(policy, player, context.records, on_decision=_on_decision)
        )

    players = [PolicyPlayer(p, policies[p]) for p in (0, 1)]
    game.set_player(0, players[0])
    game.set_player(1, players[1])

    # The initial state is a valid fork boundary (see module docstring).
    context.update_boundary(capture_snapshot(game))

    error: str | None = None
    truncated = False
    start = time.perf_counter()
    try:
        game.start()
        steps = 0
        while game.is_running():
            if steps >= max_steps:
                truncated = True
                break
            if game.is_resumable():
                context.update_boundary(capture_snapshot(game))
            game.step()
            steps += 1
    except Exception as exc:  # engine/IO failures are otherwise swallowed by cffi
        error = f"{type(exc).__name__}: {exc}"
    wall = time.perf_counter() - start

    winner: int | None = None
    rounds = 0
    final_json = None
    try:
        winner = game.winner()
        rounds = int(game.round_number())
        if record_final_state:
            final_json = capture_snapshot(game)
    except Exception:
        pass
    if error is None and game.status() == GameStatus.ABORTED:
        try:
            error = f"aborted: {game.error()}"
        except Exception:
            error = "aborted"

    record = MatchRecord(
        deck0=spec0.name,
        deck1=spec1.name,
        seed=int(seed),
        winner=winner,
        rounds=rounds,
        decisions0=len(context.records[0]),
        decisions1=len(context.records[1]),
        fallbacks0=players[0].fallbacks,
        fallbacks1=players[1].fallbacks,
        io_errors0=tuple(players[0].io_errors),
        io_errors1=tuple(players[1].io_errors),
        error=error,
        truncated=truncated,
        wall_seconds=wall,
        final_state_json=final_json,
    )
    return SearchMatchResult(record=record, searches=list(context.searches))


def _normalize_rollout_specs(
    rollout_specs: tuple[str | None, str | None], deck0: str, deck1: str
) -> tuple[str | None, str | None]:
    return (
        rollout_specs[0] or f"expert:{deck0}",
        rollout_specs[1] or f"expert:{deck1}",
    )
