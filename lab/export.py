"""Turn lab sessions into training data and comparisons (CLI; also used by the server).

    # human demonstrations -> a train.collect-format corpus (BC / AWR / PG as usual)
    python -m lab.export bc --tag human_v1 --sessions <id> <id> ...
    python -m scripts.datafirst_bc_store --replays data/replays/human_v1 --store-cache data/store/human_v1.pt --seed-start 1
    python -m scripts.datafirst_bc_train --store-cache data/store/human_v1.pt --out data/checkpoints/human_bc.pt

    # demonstrations / overrides / corrections / ratings -> DecisionSupervision records
    python -m lab.export supervision --name human_v1 --sessions <id> ...
    python -m scripts.datafirst_bc_train ... --supervision data/lab_exports/human_v1/supervision.jsonl \\
        --distill-coef 1.0 --distill-target human

    # what would other policies have played in a stored game?
    python -m lab.export compare <id> --policies heuristic "llm:deepseek-chat#kb=rules" --seat 1

    # check a person's corrections against counterfactual rollouts (costly; see docs/howto/lab.md)
    python -m lab.export verify <id> --rollouts 12

``--sessions all`` selects every stored session. The last line printed on stdout is
a JSON report; everything else goes to stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from common.paths import data_dir


def _stores(root: str | None, ids: list[str]) -> list[Any]:
    from .session import list_sessions, open_session

    if ids == ["all"]:
        ids = [meta["id"] for meta in reversed(list_sessions(root))]
    return [open_session(session_id, root) for session_id in ids]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=None, help="session directory (default: <data>/lab)")
    sub = parser.add_subparsers(dest="command", required=True)

    bc = sub.add_parser("bc", help="write a train.collect-format corpus")
    bc.add_argument("--tag", required=True)
    bc.add_argument("--sessions", nargs="+", required=True)
    bc.add_argument("--seats", choices=["human", "corrected", "all"], default="human")
    bc.add_argument("--encoder-profile", default="v2")
    bc.add_argument("--include-autopilot", action="store_true")
    bc.add_argument("--include-unclean", action="store_true",
                    help="also export games in which the player could see hidden information")
    bc.add_argument("--out-dir", default=None, help="default: <data>/replays/<tag>")

    sup = sub.add_parser("supervision", help="write DecisionSupervision records with human signals")
    sup.add_argument("--name", required=True)
    sup.add_argument("--sessions", nargs="+", required=True)
    sup.add_argument("--kinds", nargs="+", default=["demonstration", "override", "correction", "rating"])
    sup.add_argument("--out", default=None, help="default: <data>/lab_exports/<name>/supervision.jsonl")

    cmp_ = sub.add_parser("compare", help="what other policies would have played")
    cmp_.add_argument("session")
    cmp_.add_argument("--policies", nargs="+", required=True)
    cmp_.add_argument("--seat", type=int, default=None, choices=[0, 1])
    cmp_.add_argument("--limit", type=int, default=None)

    ver = sub.add_parser("verify", help="counterfactual check of a session's corrections / overrides")
    ver.add_argument("session")
    ver.add_argument("--rollouts", type=int, default=12)
    ver.add_argument("--workers", type=int, default=2)
    ver.add_argument("--out", default=None, help="default: <data>/lab_exports/<session>/verified.jsonl")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    real_stdout = sys.stdout
    sys.stdout = sys.stderr            # keep stdout for the final JSON line
    try:
        if args.command == "bc":
            from .replay import export_bc

            out_dir = Path(args.out_dir) if args.out_dir else data_dir() / "replays" / args.tag
            report = export_bc(_stores(args.root, args.sessions), out_dir, encoder_profile=args.encoder_profile,
                               seats=args.seats, include_autopilot=args.include_autopilot,
                               include_unclean=args.include_unclean, tag=args.tag)
            report = {"kind": "bc", "path": str(out_dir), "games": report["games"],
                      "samples": report["samples"], "skipped": report["skipped"],
                      "sessions": report["sessions"]}
        elif args.command == "supervision":
            from .replay import export_supervision

            out = Path(args.out) if args.out else data_dir() / "lab_exports" / args.name / "supervision.jsonl"
            if out.exists():
                raise FileExistsError(f"{out} exists; choose another name (exports are append-only)")
            out.parent.mkdir(parents=True, exist_ok=True)
            report = {"kind": "supervision",
                      **export_supervision(_stores(args.root, args.sessions), out, kinds=args.kinds)}
        elif args.command == "compare":
            from .replay import compare_policies
            from .session import open_session

            report = compare_policies(open_session(args.session, args.root), args.policies,
                                      seat=args.seat, limit=args.limit)
        else:
            from .session import open_session
            from .verify import verify_session

            store = open_session(args.session, args.root)
            out = Path(args.out) if args.out else data_dir() / "lab_exports" / store.id / "verified.jsonl"
            report = verify_session(store, out, rollouts=args.rollouts, workers=args.workers)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        sys.stdout = real_stdout
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
