"""Collect information-legal counterfactual evidence for expert decisions.

Plays label-only evidence games (``train.evidence``) and writes, append-only::

    <data>/evidence/<tag>/supervision.jsonl   one DecisionSupervision per line
    <data>/evidence/<tag>/games.jsonl         one line per finished game (resume marker)
    <data>/evidence/<tag>/manifest.json       spec fingerprint, engine lock, prior hash

The games are the ones ``train.collect`` records for the same deck / opponent /
seed / side, so ``supervision.jsonl`` joins that corpus by decision key
(``train.strategy_targets``). Re-running the same command resumes; a changed spec
(different rollouts, prior, gate ...) is refused -- use a new ``--tag``.

Cost: every evaluated decision runs ``(alternatives + 1) * rollouts`` rollout
games in the fork workers. Bound it with ``--gate``, ``--max-searches-per-game``
and ``--max-decisions``.

Usage::

    python -m scripts.collect_evidence --deck double_geo_navia --all-opponents \\
        --seed-start 1 --seed-count 4 --sides 0 1 --rollouts 16 --top-k 1 \\
        --prior data/checkpoints/bc.pt --gate disagreement \\
        --max-decisions 200 --workers 2 --tag vcsd_min
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from common.lock import load_engine_lock, runtime_metadata
from common.paths import data_dir, ensure_dir

SUPERVISION_NAME = "supervision.jsonl"
GAMES_NAME = "games.jsonl"
MANIFEST_NAME = "manifest.json"


def _sha256(path: str | None) -> str | None:
    if not path:
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _game_id(row: dict[str, Any]) -> tuple[str, str, int, int]:
    return (str(row["deck"]), str(row["opponent"]), int(row["seed"]), int(row.get("side", 0)))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--deck", required=True)
    p.add_argument("--opponents", nargs="*", default=None)
    p.add_argument("--all-opponents", action="store_true")
    p.add_argument("--seed-start", type=int, default=1)
    p.add_argument("--seed-count", type=int, default=1)
    p.add_argument("--sides", nargs="+", type=int, default=[0], choices=[0, 1])
    p.add_argument("--rollouts", type=int, default=16)
    p.add_argument("--top-k", type=int, default=1,
                   help="alternatives evaluated besides the expert's action")
    p.add_argument("--prior", default=None,
                   help="CVPN/TransformerCVPN checkpoint that picks the alternatives (and feeds the gate)")
    p.add_argument("--gate", default="none",
                   help="none | disagreement | margin:<x> | entropy:<x> (envs.adaptive)")
    p.add_argument("--max-searches-per-game", type=int, default=None)
    p.add_argument("--search-every", type=int, default=1,
                   help="consider only every N-th teacher decision (spreads the budget over the game)")
    p.add_argument("--max-decisions", type=int, default=None,
                   help="stop starting new games once this many evidence records exist")
    p.add_argument("--teacher-spec", default=None)
    p.add_argument("--opponent-spec", default=None)
    p.add_argument("--continuation", nargs=2, default=[None, None], metavar=("SELF", "OPPONENT"),
                   help="rollout policy specs (default: both decks' scripted experts)")
    p.add_argument("--include-unsearched", action="store_true",
                   help="also write expert-action records for decisions without evidence")
    p.add_argument("--no-text", action="store_true", help="skip the text rendering of states/options")
    p.add_argument("--workers", type=int, default=2, help="fork-bridge worker processes")
    p.add_argument("--tag", required=True)
    p.add_argument("--out-dir", default=None, help="default: <data>/evidence/<tag>")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from envs.adaptive import build_gate
    from envs.decks import expert_decks_by_name
    from envs.fork_bridge import ForkBridge
    from reps.knowledge import KB_ENV, KnowledgeBase, detector_ids, matching_units
    from reps.strategy import read_supervision, write_supervision
    from train.evidence import GENERATOR, EvidenceSpec, collect_evidence_game, default_describer, summarize

    if args.seed_start <= 0 <= args.seed_start + args.seed_count - 1:
        print("[warn] seed 0 gives a degenerate engine RNG (every die rolls the same face); "
              "prefer --seed-start >= 1", flush=True)
    opponents = list(args.opponents or [])
    if args.all_opponents:
        opponents = [name for name in sorted(expert_decks_by_name()) if name != args.deck]
    if not opponents:
        raise SystemExit("give --opponents or --all-opponents")
    continuation = tuple(None if v in (None, "", "none") else v for v in args.continuation)

    kb_version = None
    try:
        kb_version = KnowledgeBase.load().version
    except FileNotFoundError:
        pass  # detectors need no KB files; only the version stamp is missing

    spec_block = {
        "generator": GENERATOR,
        "deck": args.deck, "opponents": opponents,
        "seed_start": args.seed_start, "seed_count": args.seed_count, "sides": sorted(set(args.sides)),
        "rollouts": args.rollouts, "top_k": args.top_k, "gate": args.gate,
        "max_searches_per_game": args.max_searches_per_game, "search_every": args.search_every,
        "teacher_spec": args.teacher_spec, "opponent_spec": args.opponent_spec,
        "continuation": list(continuation), "include_unsearched": bool(args.include_unsearched),
        "text": not args.no_text,
        "prior_sha256": _sha256(args.prior),
        "knowledge": {"detectors": list(detector_ids()), "kb_version": kb_version, "kb_env": KB_ENV},
    }
    fingerprint = hashlib.sha256(json.dumps(spec_block, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    out_dir = Path(args.out_dir) if args.out_dir else data_dir() / "evidence" / args.tag
    ensure_dir(out_dir)
    manifest_path, games_path, sup_path = (out_dir / MANIFEST_NAME, out_dir / GAMES_NAME, out_dir / SUPERVISION_NAME)
    lock = load_engine_lock()
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("fingerprint") != fingerprint or previous.get("engine_lock") != lock:
            raise SystemExit(f"{manifest_path} was written for a different spec or engine lock; use a new --tag")
    done: set[tuple[str, str, int, int]] = set()
    if games_path.exists():
        with games_path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    done.add(_game_id(json.loads(line)))
                except (ValueError, KeyError):
                    continue  # torn trailing line: that game is simply not done
    if sup_path.exists():
        # Records are appended game by game before the game's done-marker, so
        # records of an unfinished game can only be a suffix: cut it off.
        keep = 0
        with sup_path.open("rb") as handle:
            for raw in handle:
                try:
                    row = json.loads(raw)
                    if _game_id(row) not in done:
                        break
                except (ValueError, KeyError):
                    break
                keep += len(raw)
        if keep != sup_path.stat().st_size:
            with sup_path.open("r+b") as handle:
                handle.truncate(keep)
            print(f"[resume] dropped records of an unfinished game ({sup_path.name} -> {keep} bytes)", flush=True)
    n_records = sum(1 for _ in read_supervision(sup_path)) if sup_path.exists() else 0

    manifest = {
        "tag": args.tag, "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "fingerprint": fingerprint, "spec": spec_block, "prior": args.prior,
        "engine_lock": lock, "runtime": runtime_metadata(),
    }
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    prior = None
    if args.prior:
        from train.student import NetworkStudent

        prior = NetworkStudent.from_checkpoint(args.prior)
    gate = build_gate(args.gate)
    seeds = range(args.seed_start, args.seed_start + args.seed_count)
    todo = [(seed, opponent, side) for seed in seeds for opponent in opponents for side in sorted(set(args.sides))]
    bridge = ForkBridge(workers=max(1, int(args.workers)))
    t0 = time.perf_counter()
    played = 0
    try:
        for seed, opponent, side in todo:
            if (args.deck, opponent, int(seed), int(side)) in done:
                continue
            if args.max_decisions is not None and n_records >= args.max_decisions:
                break
            spec = EvidenceSpec(
                deck=args.deck, opponent=opponent, seed=int(seed), side=int(side),
                rollouts=args.rollouts, top_k=args.top_k, max_searches=args.max_searches_per_game,
                search_every=args.search_every,
                teacher_spec=args.teacher_spec, opponent_spec=args.opponent_spec,
                continuation=continuation, include_unsearched=args.include_unsearched,
            )
            game = collect_evidence_game(
                spec, bridge=bridge, prior=prior, gate=gate,
                describer=None if args.no_text else default_describer(opponent),
                annotate=matching_units,
                provenance_extra={"tag": args.tag, "fingerprint": fingerprint, "kb_version": kb_version,
                                  "prior_sha256": spec_block["prior_sha256"], "gate": args.gate,
                                  "gitcg_version": manifest["runtime"].get("gitcg_version")},
            )
            write_supervision(sup_path, game.supervision, append=True)
            with games_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(game.as_dict(), ensure_ascii=False) + "\n")
            n_records += len(game.supervision)
            played += 1
            print(f"[evidence] {args.deck} vs {opponent} seed={seed} side={side} "
                  f"searched={game.searched}/{game.teacher_decisions} records={n_records} "
                  f"err={game.error} ({time.perf_counter() - t0:.0f}s)", flush=True)
    finally:
        close = getattr(bridge, "close", None)
        if callable(close):
            close()

    records = list(read_supervision(sup_path)) if sup_path.exists() else []
    summary = summarize(records)
    manifest.update({"updated": _dt.datetime.now().isoformat(timespec="seconds"),
                     "games_done": len(done) + played, "summary": summary,
                     "created": json.loads(manifest_path.read_text(encoding="utf-8")).get("created")})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] {json.dumps(summary, ensure_ascii=False)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
