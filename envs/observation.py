"""Observation encoder factory (PLAN.md WS1).

Builds the tokenized observation encoder with a vocabulary that covers every card
and character appearing in the scripted expert deck pool. Inputs (tokens / option
features) derive from ``context.player_view`` (masked); training targets derive
from ``context.full_state`` (god view). See ``tests/test_info_leak.py``.
"""

from __future__ import annotations

from functools import lru_cache

from reps.observation_encoder import TokenObservationEncoder, TokenObservationEncoderConfig


@lru_cache(maxsize=1)
def expert_vocabulary() -> tuple[tuple[int, ...], tuple[int, ...]]:
    """(character_vocabulary, card_vocabulary) over all scripted expert decks."""
    from envs.decks import expert_deck_specs

    specs = expert_deck_specs()
    characters = sorted({int(c) for spec in specs for c in spec.characters})
    cards = sorted({int(c) for spec in specs for c in spec.cards})
    return tuple(characters), tuple(cards)


@lru_cache(maxsize=1)
def default_encoder() -> TokenObservationEncoder:
    characters, cards = expert_vocabulary()
    return TokenObservationEncoder(
        TokenObservationEncoderConfig(
            card_vocabulary=cards,
            character_vocabulary=characters,
        )
    )


ENCODER_PROFILE_NAMES = ("v1", "v1s", "v2")


@lru_cache(maxsize=4)
def encoder_for_profile(profile: str = "v1") -> TokenObservationEncoder:
    """The default (expert-vocabulary) encoder under a named feature profile.

    ``v1`` is :func:`default_encoder` itself (historical features, every existing
    corpus/checkpoint). ``v2`` adds seat-relative turn flags and the opponent's
    public dice count (see ``TokenObservationEncoderConfig``). Profiles only change
    feature *values*, never dimensions, so a v2 store trains the same networks; the
    profile travels with the encoder config (collect manifest -> store meta ->
    checkpoint), and ``neural:`` loads whatever the checkpoint recorded.
    """
    from reps.observation_encoder import ENCODER_PROFILES

    if profile not in ENCODER_PROFILES:
        raise KeyError(f"unknown encoder profile {profile!r} (known: {sorted(ENCODER_PROFILES)})")
    base = default_encoder()
    if profile == "v1":
        return base
    return base.with_flags(**ENCODER_PROFILES[profile])


def encoder_from_config(config: dict | None) -> TokenObservationEncoder:
    """Rebuild an encoder from a saved config; ``None`` -> the legacy v1 default."""
    if not config:
        return default_encoder()
    return TokenObservationEncoder.from_dict(config)
