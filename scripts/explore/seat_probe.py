"""Seat-coverage / encoder-profile probe (2026-11 review).

Question: how much does the historical setup -- contestant always on seat 0 in
training, absolute seat flags in the global token (encoder profile v1) -- cost on
seat 1, and do the v1s/v2 profiles and both-seat data remove it?

The scripted experts never condition on seat, so their move choice is the same
function of the position on both seats. A model's imitation loss on held-out
*seat-1* expert decisions, compared with held-out *seat-0* decisions, therefore
isolates what the seat does to the model (no win-rate noise). Win rate is not
measured here; certify any arm with ``scripts.eval_protocol`` before claiming
strength.

Input: replay dirs collected with ``train.collect --sides both --encoder-profile v2
--format compact --compact-dtype float32``. Because the profiles differ only in
a few feature *values*, the v1 and v1s features of every recorded decision are
derived exactly from its v2 features (see :func:`to_profile`; checked against
direct encoding in ``tests/test_encoder_profiles.py``), so all arms see the very
same decisions.

Usage::

    # train arms from scratch and compare
    python -m scripts.explore.seat_probe --train-replays data/replays/seat_train \\
        --eval-replays data/replays/seat_eval --arms A C D --seeds 0 1 2 \\
        --out reports/explore/seat_probe.json

    # zero-training diagnostic of an existing v1 checkpoint (raw vs #seatrel=1)
    python -m scripts.explore.seat_probe --eval-replays data/replays/seat_eval \\
        --checkpoint data/checkpoints/<ckpt>.pt --out reports/explore/seat_probe_ckpt.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

import torch

from common.paths import ensure_dir
from envs.observation import encoder_for_profile
from reps.observation_encoder import (
    _OPPONENT_TAGS,
    _OPTION_KINDS,
    _OWNER_TYPES,
    _PHASES,
    _REQUEST_TYPES,
    _TOKEN_TYPES,
)
from scripts.datafirst_bc_store import load_store_any
from scripts.train_bc_scale import Config, Store, evaluate, train
from train.model import CVPN, config_for_encoder, load_cvpn_model


# --------------------------------------------------------------------------- #
# exact feature conversion v2 -> v1s / v1
# --------------------------------------------------------------------------- #
def _layout(include_opponent_tag: bool = True) -> dict[str, int]:
    scalar = (
        len(_TOKEN_TYPES) + len(_OWNER_TYPES) + len(_PHASES) + len(_REQUEST_TYPES)
        + len(_OPTION_KINDS) + (len(_OPPONENT_TAGS) if include_opponent_tag else 0)
    )
    return {
        "round": scalar,
        "turn": scalar + 2,          # current_turn one-hot (2)
        "acting": scalar + 4,        # acting_player one-hot (2)
        "summary_dice": scalar + 6 + 2,
        "type_summary": _TOKEN_TYPES.index("player_summary"),
        "owner_opponent": len(_TOKEN_TYPES) + _OWNER_TYPES.index("opponent"),
    }


def to_profile(tokens: torch.Tensor, side: int, profile: str) -> torch.Tensor:
    """Convert one decision's v2 token matrix to ``profile`` (``v1``/``v1s``/``v2``).

    v1s = v2 without the opponent dice count (always 0 in v1/v1s). v1 = v1s with
    absolute seat flags: identical on seat 0; on seat 1 both one-hots of the
    global token (row 0) are swapped (slot 0 = "acting/turn is seat 0").
    """
    if profile == "v2":
        return tokens
    lay = _layout()
    out = tokens.clone()
    is_opp_summary = (out[:, lay["type_summary"]] == 1.0) & (out[:, lay["owner_opponent"]] == 1.0)
    out[is_opp_summary, lay["summary_dice"]] = 0.0
    if profile == "v1s" or side == 0:
        return out
    if profile != "v1":
        raise ValueError(f"unknown profile {profile!r}")
    for start in (lay["turn"], lay["acting"]):
        a, b = out[0, start].clone(), out[0, start + 1].clone()
        out[0, start], out[0, start + 1] = b, a
    return out


def _side_of(key: tuple) -> int:
    return int(key[3]) if len(key) == 5 else 0


def converted(store: Store, profile: str, sides: Sequence[int], seeds: set[int] | None = None) -> Store:
    keep = [
        i for i, k in enumerate(store.keys)
        if _side_of(k) in sides and (seeds is None or int(k[2]) in seeds)
    ]
    sub = store.subset(keep)
    sub.tokens = [to_profile(t, _side_of(k), profile) for t, k in zip(sub.tokens, sub.keys)]
    return sub


def round_one(store: Store) -> Store:
    lay = _layout()
    keep = [i for i, t in enumerate(store.tokens) if abs(float(t[0, lay["round"]]) - 1.0 / 15.0) < 1e-6]
    return store.subset(keep)


# --------------------------------------------------------------------------- #
# arms
# --------------------------------------------------------------------------- #
ARMS: dict[str, dict[str, Any]] = {
    # profile used for training, training seats, fraction of training seeds used
    "A": {"profile": "v1", "sides": (0,), "seed_fraction": 1.0,
          "note": "status quo: v1 features, seat-0 data only"},
    "C": {"profile": "v2", "sides": (0,), "seed_fraction": 1.0,
          "note": "v2 features, seat-0 data only"},
    "D": {"profile": "v2", "sides": (0, 1), "seed_fraction": 0.5,
          "note": "v2 features, both seats, same number of games as A"},
    "E": {"profile": "v2", "sides": (0, 1), "seed_fraction": 1.0,
          "note": "v2 features, both seats, twice the games of A"},
}


def _metrics(model, store: Store, config: Config) -> dict[str, float]:
    if len(store) == 0:
        return {"n": 0}
    row = evaluate(model, store, config, config.device, False)
    return {"n": int(row["n"]), "ce": float(row["ce"]), "acc": float(row["acc"]),
            "value_mse": float(row["value"])}


@torch.no_grad()
def _argmax(model, store: Store, config: Config) -> list[int]:
    from scripts.train_bc_scale import _collate

    picks: list[int] = []
    for start in range(0, len(store), config.batch_size):
        index = list(range(start, min(start + config.batch_size, len(store))))
        tokens, token_mask, options, option_mask, _t, _v = _collate(store, index, config.device)
        logits, _value = model(tokens, token_mask, options, option_mask)
        picks.extend(int(v) for v in logits.argmax(dim=-1).tolist())
    return picks


def evaluate_model(model, eval_store: Store, profiles: dict[str, str], config: Config) -> dict[str, Any]:
    """``profiles`` maps a label to the profile used to encode the eval data."""
    out: dict[str, Any] = {}
    for label, profile in profiles.items():
        for side in (0, 1):
            data = converted(eval_store, profile, (side,))
            out[f"{label}/seat{side}"] = _metrics(model, data, config)
            out[f"{label}/seat{side}/round1"] = _metrics(model, round_one(data), config)
    labels = list(profiles)
    if len(labels) == 2:
        # f07's ``seat_swap`` diagnostic: how often does the profile change the
        # greedy action on seat-1 positions (and which choice matches the expert)?
        a = converted(eval_store, profiles[labels[0]], (1,))
        b = converted(eval_store, profiles[labels[1]], (1,))
        pa, pb = _argmax(model, a, config), _argmax(model, b, config)
        flips = [i for i, (x, y) in enumerate(zip(pa, pb)) if x != y]
        out["seat1_argmax_flip"] = {
            "n": len(pa),
            "flip_rate": len(flips) / max(1, len(pa)),
            f"{labels[0]}_matches_expert_on_flips": sum(pa[i] == a.teacher[i] for i in flips),
            f"{labels[1]}_matches_expert_on_flips": sum(pb[i] == b.teacher[i] for i in flips),
        }
    return out


def _mean_sd(values: list[float]) -> tuple[float, float]:
    n = len(values)
    if n == 0:
        return float("nan"), float("nan")
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else 0.0
    return mean, sd


def run_arms(args) -> dict[str, Any]:
    train_all, _, train_meta = load_store_any(args.train_replays, seed_start=0, val_every=0)
    eval_all, _, eval_meta = load_store_any(args.eval_replays, seed_start=0, val_every=0)
    for meta in (train_meta, eval_meta):
        if meta.get("encoder_profile") != "v2":
            raise SystemExit("seat_probe needs replay dirs collected with --encoder-profile v2")
    seeds = sorted({int(k[2]) for k in train_all.keys})
    encoder = encoder_for_profile("v1")  # dims are profile-independent
    results: dict[str, Any] = {}
    for arm in args.arms:
        spec = ARMS[arm]
        use_seeds = set(seeds[: max(1, int(round(len(seeds) * spec["seed_fraction"])))])
        data = converted(train_all, spec["profile"], spec["sides"], use_seeds)
        runs = []
        for seed in args.seeds:
            torch.manual_seed(int(seed))
            model = CVPN(config_for_encoder(encoder, d_model=args.d_model))
            config = Config(epochs=args.epochs, lr=args.lr, batch_size=args.batch_size,
                            seed=int(seed), log_every=0)
            history, seconds = train(data, Store([], [], [], [], [], [], [], [], [], [], []),
                                     model, config, False)
            model.eval()
            profiles = {"own": spec["profile"]}
            if spec["profile"] == "v1":
                profiles["seatrel"] = "v1s"   # same model, #seatrel=1 at inference
            runs.append({
                "seed": int(seed),
                "train_samples": len(data),
                "train_games": len({k[:-1] for k in data.keys}),
                "train_seconds": seconds,
                "final_train_ce": history[-1]["ce"] if history else None,
                "eval": evaluate_model(model, eval_all, profiles, config),
            })
            print(f"[probe] arm {arm} seed {seed}: "
                  + " ".join(f"{k}={v['ce']:.4f}" for k, v in runs[-1]["eval"].items()
                             if "round1" not in k and "ce" in v), flush=True)
        summary: dict[str, Any] = {}
        for key in runs[0]["eval"]:
            if key == "seat1_argmax_flip":
                summary[key] = {
                    "flip_rate_mean": _mean_sd([r["eval"][key]["flip_rate"] for r in runs])[0],
                    "per_run": [r["eval"][key] for r in runs],
                }
                continue
            for metric in ("ce", "acc"):
                vals = [r["eval"][key][metric] for r in runs if r["eval"][key].get("n")]
                mean, sd = _mean_sd(vals)
                summary[f"{key}/{metric}"] = {"mean": mean, "sd": sd, "n_runs": len(vals),
                                              "n_decisions": runs[0]["eval"][key]["n"]}
        # paired (same training run) seat gaps
        gaps: dict[str, Any] = {}
        for label in runs[0]["eval"]:
            if not label.endswith("seat1") or label.startswith("seat1_"):
                continue
            base = label.rsplit("/", 1)[0]
            vals = [r["eval"][label]["ce"] - r["eval"][f"own/seat0"]["ce"] for r in runs]
            mean, sd = _mean_sd(vals)
            gaps[f"{base}: ce(seat1) - ce(seat0, own)"] = {"mean": mean, "sd": sd}
        results[arm] = {"spec": {**spec, "sides": list(spec["sides"])}, "runs": runs,
                        "summary": summary, "seat_gaps": gaps}
    return {"train_meta": train_meta, "eval_meta": eval_meta, "arms": results}


def run_checkpoint(args) -> dict[str, Any]:
    """Zero-training diagnostic of an existing (v1, seat-0-trained) checkpoint."""
    eval_all, _, eval_meta = load_store_any(args.eval_replays, seed_start=0, val_every=0)
    if eval_meta.get("encoder_profile") != "v2":
        raise SystemExit("seat_probe needs replay dirs collected with --encoder-profile v2")
    model = load_cvpn_model(args.checkpoint)
    model.eval()
    config = Config(batch_size=args.batch_size)
    return {"checkpoint": args.checkpoint, "eval_meta": eval_meta,
            "eval": evaluate_model(model, eval_all, {"raw": "v1", "seatrel": "v1s"}, config)}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--train-replays", nargs="*", default=[])
    p.add_argument("--eval-replays", nargs="+", required=True)
    p.add_argument("--arms", nargs="*", default=["A", "C", "D"], choices=sorted(ARMS))
    p.add_argument("--seeds", nargs="*", type=int, default=[0, 1, 2])
    p.add_argument("--d-model", type=int, default=128)
    p.add_argument("--epochs", type=int, default=15)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--checkpoint", default=None)
    p.add_argument("--threads", type=int, default=None)
    p.add_argument("--out", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.threads:
        torch.set_num_threads(int(args.threads))
    if args.checkpoint:
        report = run_checkpoint(args)
    else:
        if not args.train_replays:
            raise SystemExit("--train-replays is required unless --checkpoint is given")
        report = run_arms(args)
    report.update({"kind": "seat_probe", "generated": _dt.datetime.now().isoformat(timespec="seconds"),
                   "args": vars(args)})
    out = Path(args.out)
    ensure_dir(out.parent)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
