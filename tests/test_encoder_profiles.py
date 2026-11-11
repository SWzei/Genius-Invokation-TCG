"""Encoder profiles (2026-11 review): seat-relative turn flags + opponent public dice.

v1 is the historical encoding and must stay byte-identical (existing corpora,
checkpoints, collect fingerprints). v2/v1s fix two defects found in review:

* the global token encoded ``current_turn``/``acting_player`` as absolute seats,
  while every collector trains the contestant on seat 0 -- so on seat 1 the
  network saw an input column that was constant zero during training;
* the opponent's dice *count* (public) was always 0, because the snapshot drops
  hidden (face 0) dice.
"""

from __future__ import annotations

import pytest

from envs.decks import deck_spec
from envs.match import run_match
from envs.observation import default_encoder, encoder_for_profile, encoder_from_config
from envs.policy import expert_policy
from reps.observation_encoder import (
    ENCODER_PROFILES,
    TokenObservationEncoder,
    TokenObservationEncoderConfig,
    _OWNER_TYPES,
    _PHASES,
    _REQUEST_TYPES,
    _OPTION_KINDS,
    _TOKEN_TYPES,
    _OPPONENT_TAGS,
)
from reps.schema import public_dice_count

# Collect fingerprints computed with the pre-review code (commit 98b4dfa). A
# change here means existing replay dirs would refuse to resume.
_HISTORICAL_FINGERPRINTS = {
    "default": "8801d0a4840d67cea30fed9d200fb4c0cac67550f034603604e4891465e64092",
    "compact_neural": "da70d864037cd0d151a9682a36d442a9c183260a85353c6b0eae62bb27c3531d",
}


class _Capture:
    def __init__(self, inner):
        self.inner = inner
        self.name = "capture"
        self.built = []

    def choose(self, built):
        self.built.append(built)
        return self.inner.choose(built)


@pytest.fixture(scope="module")
def game_contexts():
    """One expert-vs-expert game; decision contexts for both seats."""
    cap0 = _Capture(expert_policy("superconduct_aggro", seed=1))
    cap1 = _Capture(expert_policy("dvalin_bonk", seed=2))
    record = run_match(
        deck_spec("superconduct_aggro"), deck_spec("dvalin_bonk"), cap0, cap1, seed=11
    )
    assert record.error is None
    return [b.context for b in cap0.built], [b.context for b in cap1.built]


def _scalar_offset(encoder: TokenObservationEncoder) -> int:
    return (
        len(_TOKEN_TYPES) + len(_OWNER_TYPES) + len(_PHASES) + len(_REQUEST_TYPES)
        + len(_OPTION_KINDS)
        + (len(_OPPONENT_TAGS) if encoder.config.include_opponent_tag else 0)
    )


def _turn_flags(encoder, observation):
    """(current_turn one-hot, acting_player one-hot) of the global token."""
    g = observation.token_features[0]
    base = _scalar_offset(encoder) + 2  # after round_number, definition_id
    return tuple(g[base : base + 2]), tuple(g[base + 2 : base + 4])


def _opponent_summary_dice(encoder, observation):
    owner0 = len(_TOKEN_TYPES)
    summary = _TOKEN_TYPES.index("player_summary")
    for token in observation.token_features:
        if token[summary] == 1.0 and token[owner0 + _OWNER_TYPES.index("opponent")] == 1.0:
            # scalars: round, def, 4 turn flags, then (chars, hand, dice, ...)
            return token[_scalar_offset(encoder) + 6 + 2]
    raise AssertionError("no opponent player_summary token")


# --------------------------------------------------------------------------- #
# serialisation / compatibility
# --------------------------------------------------------------------------- #
def test_v1_profile_is_the_historical_default_encoder():
    assert encoder_for_profile("v1") is default_encoder()
    payload = default_encoder().to_dict()
    assert "seat_relative_turn" not in payload and "public_opponent_dice" not in payload
    assert default_encoder().profile == "v1"


def test_profiles_round_trip_and_keep_dimensions():
    v1 = encoder_for_profile("v1")
    for name in ENCODER_PROFILES:
        enc = encoder_for_profile(name)
        assert enc.profile == name
        assert TokenObservationEncoder.from_dict(enc.to_dict()).profile == name
        assert (enc.token_dim, enc.option_dim) == (v1.token_dim, v1.option_dim)
    # a checkpoint/store config without the new keys is v1
    assert encoder_from_config(None).profile == "v1"
    assert encoder_from_config(v1.to_dict()).profile == "v1"


def test_collect_fingerprints_unchanged_for_default_specs():
    from train.collect import CollectSpec

    default = CollectSpec(
        deck="superconduct_aggro", opponents=("natlan_battleship", "dvalin_bonk"), seeds=(0, 1, 2)
    )
    compact = CollectSpec(
        deck="double_geo_navia", opponents=("dvalin_bonk",), seeds=tuple(range(5)),
        teacher_spec="neural:x.pt#t=1.0", format="compact", include_privileged_state=False,
    )
    assert default.fingerprint() == _HISTORICAL_FINGERPRINTS["default"]
    assert compact.fingerprint() == _HISTORICAL_FINGERPRINTS["compact_neural"]
    # task indices are unchanged for the default single-seat spec
    assert [(t.index, t.opponent, t.seed, t.side) for t in default.tasks()][:2] == [
        (0, "natlan_battleship", 0, 0), (1, "natlan_battleship", 1, 0)
    ]


def test_collect_spec_sides_and_profile_enter_the_fingerprint():
    from train.collect import CollectSpec

    base = dict(deck="superconduct_aggro", opponents=("dvalin_bonk",), seeds=(0, 1))
    fps = {
        CollectSpec(**base).fingerprint(),
        CollectSpec(**base, sides=(0, 1)).fingerprint(),
        CollectSpec(**base, encoder_profile="v2").fingerprint(),
    }
    assert len(fps) == 3
    both = CollectSpec(**base, sides=(0, 1)).tasks()
    assert [(t.seed, t.side) for t in both] == [(0, 0), (0, 1), (1, 0), (1, 1)]
    assert len({t.index for t in both}) == 4


# --------------------------------------------------------------------------- #
# engine-backed behaviour
# --------------------------------------------------------------------------- #
def test_v1_turn_flags_are_absolute_seats(game_contexts):
    """Documents the defect: seat-1 decisions carry the acting_player==1 flag."""
    enc = encoder_for_profile("v1")
    seat0, seat1 = game_contexts
    acting0 = {_turn_flags(enc, enc.encode_context(c, include_training_targets=False))[1] for c in seat0}
    acting1 = {_turn_flags(enc, enc.encode_context(c, include_training_targets=False))[1] for c in seat1}
    assert acting0 == {(1.0, 0.0)}
    assert acting1 == {(0.0, 1.0)}   # never present in a seat-0-only training corpus


def test_seat_relative_flags_match_v1_on_seat0_and_map_seat1_into_it(game_contexts):
    v1, v1s = encoder_for_profile("v1"), encoder_for_profile("v1s")
    seat0, seat1 = game_contexts
    for context in seat0:
        a = v1.encode_context(context, include_training_targets=False)
        b = v1s.encode_context(context, include_training_targets=False)
        # byte-identical on seat 0: existing seat-0-trained checkpoints are unaffected
        assert a.token_features == b.token_features
        assert a.option_features == b.option_features
    for context in seat1:
        obs = v1s.encode_context(context, include_training_targets=False)
        turn, acting = _turn_flags(v1s, obs)
        assert acting == (1.0, 0.0)
        view = context.player_view
        expected = (1.0, 0.0) if view.current_turn == context.acting_player else (0.0, 1.0)
        assert turn == expected


def test_v2_exposes_opponent_public_dice_count_only(game_contexts):
    v1, v2 = encoder_for_profile("v1"), encoder_for_profile("v2")
    seat0, _ = game_contexts
    actions = [c for c in seat0 if c.request_type.value == "action"]
    assert actions
    seen_nonzero = False
    for context in actions:
        opponent = context.player_view.players[1 - context.acting_player]
        # the masked view hides faces but keeps the count
        assert opponent.dice == ()
        count = public_dice_count(opponent)
        assert v1_dice(v1, context) == 0.0
        got = _opponent_summary_dice(v2, v2.encode_context(context, include_training_targets=False))
        assert abs(got - min(count, 8) / 8.0) < 1e-9
        seen_nonzero |= count > 0
        # never exposes faces: no opponent dice tokens are emitted
        obs = v2.encode_context(context, include_training_targets=False)
        dice_type = _TOKEN_TYPES.index("dice")
        opp_owner = len(_TOKEN_TYPES) + _OWNER_TYPES.index("opponent")
        assert not any(t[dice_type] == 1.0 and t[opp_owner] == 1.0 for t in obs.token_features)
    assert seen_nonzero


def v1_dice(encoder, context):
    return _opponent_summary_dice(encoder, encoder.encode_context(context, include_training_targets=False))


def test_neural_spec_seatrel_option_parses():
    from envs.policy import _parse_neural_spec

    path, options = _parse_neural_spec("ckpt.pt#t=1.0#seatrel=1")
    assert path == "ckpt.pt" and options == {"t": "1.0", "seatrel": "1"}
    with pytest.raises(KeyError):
        _parse_neural_spec("ckpt.pt#bogus=1")


def test_collect_samples_teacher_on_seat1_scores_from_its_own_perspective():
    from train.data import collect_samples

    enc = encoder_for_profile("v2")
    samples = collect_samples(
        "superconduct_aggro", "dvalin_bonk", [11], encoder=enc, capture_targets=False,
        teacher_side=1,
    )
    assert samples
    # every sample is a seat-1 decision encoded seat-relatively
    for sample in samples:
        _turn, acting = _turn_flags(enc, sample.observation)
        assert acting == (1.0, 0.0)
    values = {s.value_target for s in samples}
    assert len(values) == 1 and next(iter(values)) in (0.0, 0.5, 1.0)


def test_v2_inputs_do_not_depend_on_opponent_dice_faces(game_contexts):
    """Info-leak guard for v2: only the public *count* enters, never the faces."""
    import dataclasses

    v2 = encoder_for_profile("v2")
    seat0, _ = game_contexts
    context = [c for c in seat0 if c.request_type.value == "action"][3]
    opponent = 1 - context.acting_player
    view = context.player_view
    count = public_dice_count(view.players[opponent])
    players = list(view.players)
    # same public count, different (normally hidden) faces
    players[opponent] = dataclasses.replace(
        players[opponent], dice=tuple([7] * count), dice_count=count
    )
    leaked = dataclasses.replace(context, player_view=dataclasses.replace(view, players=tuple(players)))
    a = v2.encode_context(context, include_training_targets=False)
    b = v2.encode_context(leaked, include_training_targets=False)
    assert a.token_features == b.token_features
    assert a.option_features == b.option_features


def test_collect_refuses_a_neural_teacher_with_a_different_encoder(tmp_path):
    from train.collect import CollectSpec, check_teacher_encoder
    from train.model import CVPN, config_for_encoder

    v1 = encoder_for_profile("v1")
    ckpt = tmp_path / "v1.pt"
    CVPN(config_for_encoder(v1, d_model=8)).save(str(ckpt), encoder_config=v1.to_dict())
    base = dict(deck="superconduct_aggro", opponents=("dvalin_bonk",), seeds=(0,))
    check_teacher_encoder(CollectSpec(**base, teacher_spec=f"neural:{ckpt}#t=1.0"))
    with pytest.raises(SystemExit):
        check_teacher_encoder(
            CollectSpec(**base, teacher_spec=f"neural:{ckpt}#t=1.0", encoder_profile="v2")
        )
    # the upgrade path for an existing v1 checkpoint: seat-relative inference + v1s data
    check_teacher_encoder(
        CollectSpec(**base, teacher_spec=f"neural:{ckpt}#t=1.0#seatrel=1", encoder_profile="v1s")
    )


def test_seat_probe_profile_conversion_is_exact(game_contexts):
    """``scripts.explore.seat_probe.to_profile`` derives v1/v1s exactly from v2."""
    import torch

    from scripts.explore.seat_probe import to_profile

    encoders = {name: encoder_for_profile(name) for name in ("v1", "v1s", "v2")}
    for side, contexts in enumerate(game_contexts):
        for context in contexts[::5]:
            v2 = torch.tensor(encoders["v2"].encode_context(context, include_training_targets=False).token_features)
            for name in ("v1", "v1s"):
                direct = torch.tensor(
                    encoders[name].encode_context(context, include_training_targets=False).token_features
                )
                assert torch.equal(to_profile(v2, side, name), direct), (side, name)
