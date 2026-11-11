"""Seat coverage (2026-11 review): both-seat corpora, per-seat reporting, store provenance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.scoreboard import MatchOutcome, paired_difference, summarize
from envs.observation import encoder_for_profile


def _outcome(opp, seed, side, score):
    return MatchOutcome(opponent=opp, seed=seed, side=side, score=score, rounds=6,
                        decisions=40, fallbacks=0, error=None, truncated=False)


def test_summary_and_paired_delta_report_each_seat():
    a = [_outcome("x", s, side, 1.0 if side == 0 else 0.0) for s in range(4) for side in (0, 1)]
    b = [_outcome("x", s, side, 0.5) for s in range(4) for side in (0, 1)]
    summary = summarize(a)
    assert summary["per_side"]["0"]["rate"] == 1.0
    assert summary["per_side"]["1"]["rate"] == 0.0
    paired = paired_difference(a, b)
    assert paired["per_side"]["0"]["delta"] == pytest.approx(0.5)
    assert paired["per_side"]["1"]["delta"] == pytest.approx(-0.5)
    assert paired["delta"] == pytest.approx(0.0)  # the pooled number hides the seat gap


def _sample(step: int, value: float) -> dict:
    return {
        "teacher_index": 0,
        "value_target": value,
        "step_index": step,
        "observation": {
            "token_features": [[0.0, 1.0], [1.0, 0.0]],
            "option_features": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            "belief_target": {},
        },
    }


def _write_dir(root: Path, name: str, records: list[dict], encoder_config: dict | None) -> Path:
    d = root / name
    d.mkdir()
    (d / "samples.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )
    if encoder_config is not None:
        (d / "manifest.json").write_text(json.dumps({"encoder_config": encoder_config}))
    return d


def test_store_keeps_both_seats_of_a_seed_and_splits_them_together(tmp_path):
    from scripts.datafirst_bc_store import load_store_any

    records = []
    for seed in (0, 1, 2):
        for side in (0, 1):
            rec = {"index": len(records), "deck": "d", "opponent": "o", "seed": seed,
                   "error": None, "samples": [_sample(1, 1.0), _sample(2, 1.0)]}
            if side:
                rec["side"] = side
            records.append(rec)
    d = _write_dir(tmp_path, "both", records, encoder_for_profile("v2").to_dict())
    train, val, meta = load_store_any([str(d)], seed_start=0, val_every=3)
    assert meta["duplicate_games"] == 0
    assert meta["games"] == 6
    # seed 0 -> val with BOTH of its seats (no train/val leakage of the same deal)
    assert sorted(k[2] for k in val.keys) == [0, 0, 0, 0]
    assert {len(k) for k in val.keys} == {4, 5}           # seat-0 keys keep the old layout
    assert ("d", "o", 0, 1, 1) in val.keys and ("d", "o", 0, 1) in val.keys
    assert meta["encoder_profile"] == "v2"


def test_store_records_v1_for_legacy_dirs_and_refuses_mixed_profiles(tmp_path):
    from scripts.datafirst_bc_store import load_store_any
    from scripts.train_bc_scale import replay_encoder_config

    rec = {"index": 0, "deck": "d", "opponent": "o", "seed": 5, "error": None,
           "samples": [_sample(1, 0.0)]}
    legacy = _write_dir(tmp_path, "legacy", [rec], None)
    _train, _val, meta = load_store_any([str(legacy)], seed_start=0, val_every=0)
    assert meta["encoder_profile"] == "v1"
    v2 = _write_dir(tmp_path, "v2", [rec], encoder_for_profile("v2").to_dict())
    with pytest.raises(SystemExit):
        replay_encoder_config([str(legacy), str(v2)])
