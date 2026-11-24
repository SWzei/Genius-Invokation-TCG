"""Policy abstraction used by the environment layer.

A ``Policy`` maps a ``BuiltDecisionContext`` to a concrete low-level action code.
Keeping the interface at the action-code level means the same env can drive
scripted experts, legal-random/heuristic baselines, CVPN search agents, and
LLM-assisted agents without knowing their internals (PLAN.md WS0/WS4).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Protocol

from reps.action_adapter import BuiltDecisionContext
from reps.agents import HeuristicAgent, LegalRandomAgent
from reps.schema import ActionChoice


class Policy(Protocol):
    """Callable policy: pick one legal action code for the given context."""

    name: str

    def choose(self, built: BuiltDecisionContext) -> int:  # pragma: no cover - protocol
        ...


@dataclass
class ScriptedPolicy:
    """Adapter around the ported ``ExpertRuleAgent`` (one of the 22 scripted decks)."""

    agent: Any
    name: str = "scripted"

    def choose(self, built: BuiltDecisionContext) -> int:
        return int(self.agent.choose(built).action_code)


@dataclass
class BaselinePolicy:
    """Adapter around ``reps.agents`` baselines (legal-random / heuristic)."""

    agent: Any
    name: str = "baseline"

    def choose(self, built: BuiltDecisionContext) -> int:
        choice: ActionChoice = self.agent.choose_action(built.context)
        return int(choice.action_code)


@dataclass
class RandomPolicy:
    """Uniform random over the legal action codes of the current context."""

    seed: int | None = None
    name: str = "random"
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def choose(self, built: BuiltDecisionContext) -> int:
        codes = list(built.context.legal_low_level_codes)
        if not codes:
            raise RuntimeError("no legal actions available")
        return int(self._rng.choice(codes))


@dataclass
class NoisyPolicy:
    """D37: with probability ``epsilon`` a uniform legal choice, else ``base`` decides.

    A known handicap for calibrating evaluation metrics: ``noisy:0.3:heuristic`` is
    weaker than ``heuristic`` by construction, and two ``noisy`` players with the
    same spec and independent random streams are equally strong (A/A).
    """

    base: Policy
    epsilon: float
    seed: int | None = None
    name: str = "noisy"
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def choose(self, built: BuiltDecisionContext) -> int:
        codes = list(built.context.legal_low_level_codes)
        if len(codes) > 1 and self._rng.random() < self.epsilon:
            return int(self._rng.choice(codes))
        return int(self.base.choose(built))


@dataclass
class CallablePolicy:
    """Wrap a plain ``fn(built) -> int`` (used for LLM-assisted agents, tests)."""

    fn: Callable[[BuiltDecisionContext], int]
    name: str = "callable"

    def choose(self, built: BuiltDecisionContext) -> int:
        return int(self.fn(built))


def heuristic_policy() -> BaselinePolicy:
    return BaselinePolicy(HeuristicAgent(), name="heuristic")


def legal_random_policy(seed: int | None = None) -> BaselinePolicy:
    return BaselinePolicy(LegalRandomAgent(seed=seed), name="legal_random")


@lru_cache(maxsize=1)
def _asset_catalog() -> Any:
    from agents.scripted.assets import load_assets

    return load_assets()


@lru_cache(maxsize=1)
def _profiles_by_slug() -> dict[str, Any]:
    from agents.scripted.profiles import load_deck_profiles_by_slug

    return load_deck_profiles_by_slug()


def expert_profile(slug: str) -> Any:
    profiles = _profiles_by_slug()
    if slug not in profiles:
        raise KeyError(f"unknown expert deck slug: {slug!r}")
    return profiles[slug]


def expert_policy(slug: str, *, seed: int | None = None) -> ScriptedPolicy:
    """Build a scripted expert policy for one of the ported deck rules."""
    from agents.scripted.agent import ExpertRuleAgent

    profile = expert_profile(slug)
    agent = ExpertRuleAgent(assets=_asset_catalog(), profile=profile, seed=seed)
    return ScriptedPolicy(agent, name=f"expert:{slug}")


def _parse_neural_spec(spec: str) -> tuple[str, dict[str, str]]:
    """Split ``<path>[#k=v...]`` into the checkpoint path and its options."""
    path, _, suffix = spec.partition("#")
    options: dict[str, str] = {}
    for option in suffix.split("#"):
        if not option:
            continue
        key, _, value = option.partition("=")
        if key not in ("t", "d", "seatrel"):
            raise KeyError(f"unknown neural spec option: {option!r}")
        options[key] = value
    return path, options


def neural_spec_encoder(spec: str) -> Any:
    """The observation encoder a ``neural:`` spec body runs with.

    The checkpoint's saved encoder config (legacy default when absent), plus the
    ``#seatrel=1`` override: encode the turn/acting-player flags relative to the
    acting player. For a checkpoint trained only on seat 0 (every pre-2026-11
    corpus) this is byte-identical on seat 0 and maps seat-1 positions into the
    layout the network was trained on, instead of an all-zero-in-training column.
    """
    path, options = _parse_neural_spec(spec)
    from envs.observation import encoder_from_config
    from train.model import checkpoint_encoder_config

    encoder = encoder_from_config(checkpoint_encoder_config(path))
    seatrel = options.get("seatrel")
    if seatrel not in (None, "", "0"):
        if seatrel != "1":
            raise KeyError(f"neural spec option seatrel must be 0/1, got {seatrel!r}")
        encoder = encoder.with_flags(seat_relative_turn=True)
    return encoder


def _neural_policy(spec: str, *, seed: int) -> Policy:
    """Load a CVPN checkpoint as a greedy/sampled policy.

    Spec: ``<path>[#t=<temp>][#d=<device>][#seatrel=1]`` (options may be
    ``#``-joined in any order). ``d=cuda`` routes inference to the GPU (MX550);
    the default is CPU. ``seatrel=1`` see :func:`neural_spec_encoder`.
    """
    path, options = _parse_neural_spec(spec)
    temperature = float(options.get("t", 0.0) or 0.0)
    device = options.get("d") or "cpu"
    from agents.neural import load_neural_policy

    encoder = neural_spec_encoder(spec)
    return load_neural_policy(
        path, encoder, temperature=temperature, device=device, seed=seed
    )


def build_policy(spec: str, *, seed: int, role: str) -> Policy:
    """Build a policy from a serializable spec string (used by multiprocess rollout).

    ``seed``/``role`` are folded into the policy RNG seed so the same task always
    reproduces the same agents (M0 replay consistency).

    Specs: ``expert:<slug>`` | ``neural:<checkpoint>[#t=<temp>]`` | ``heuristic``
    | ``legal_random`` | ``random`` | ``noisy:<epsilon>:<spec>`` (D37)
    | ``llm:<model profile>[#kb=...,fallback=...]``
    | ``llm-assist:<model profile>#base=<spec>`` (``agents.llm_policy``; never part
    of strength acceptance). The ``neural`` spec loads the CVPN from a
    checkpoint (with the encoder config saved beside it) so a trained checkpoint
    can run through rollout / arena / collectors like any scripted opponent.
    """
    from common.seeding import derive_seed

    spec = spec.strip()
    if spec.startswith("expert:"):
        slug = spec.split(":", 1)[1]
        return expert_policy(slug, seed=derive_seed(seed, role, "expert", slug))
    if spec.startswith("neural:"):
        return _neural_policy(spec.split(":", 1)[1], seed=derive_seed(seed, role, "neural"))
    if spec == "heuristic":
        return heuristic_policy()
    if spec == "legal_random":
        return BaselinePolicy(
            LegalRandomAgent(seed=derive_seed(seed, role, "legal_random")),
            name="legal_random",
        )
    if spec == "random":
        return RandomPolicy(seed=derive_seed(seed, role, "random"))
    if spec.startswith("noisy:"):                  # D37: noisy:<epsilon>[@salt]:<base spec>
        _, eps, base = spec.split(":", 2)
        # The seed folds in the seat, so in a mirror pair the two players would share one random
        # stream per seat and both games would be identical. A salt gives a player its own stream
        # (A/A: ``noisy:0.1@a:heuristic`` against ``noisy:0.1@b:heuristic``).
        epsilon = float(eps.split("@", 1)[0])
        if not 0.0 <= epsilon <= 1.0:
            raise ValueError(f"noisy epsilon must be in [0, 1]: {spec!r}")
        return NoisyPolicy(build_policy(base, seed=seed, role=role), epsilon,
                           seed=derive_seed(seed, role, "noisy", eps), name=f"noisy{eps}")
    # 2026-11 (D29): model-API players. Imported lazily so the pure-policy paths
    # (rollout / arena / collectors) keep their import footprint.
    if spec.startswith("llm:"):
        from agents.llm_policy import build_llm_policy

        return build_llm_policy(spec.split(":", 1)[1], seed=seed, role=role)
    if spec.startswith("llm-assist:"):
        from agents.llm_policy import build_llm_assist_from_spec

        return build_llm_assist_from_spec(spec.split(":", 1)[1], seed=seed, role=role)
    raise KeyError(f"unknown policy spec: {spec!r}")

