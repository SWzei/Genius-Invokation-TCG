"""Score checkpoints against stored counterfactual evidence (offline, no engine).

For every supervision record whose decision is in the store, take each
checkpoint's argmax over the stored option features and report
``train.student.evidence_agreement`` -- how often the choice is the expert's
action, how often it is the action a *verified* verdict supports, and the mean
paired ``Q(choice) - Q(expert)`` where the choice was evaluated.

These are consistency measures against Monte-Carlo evidence under its stated
continuation policies. They are **not** playing strength; use
``scripts.eval_protocol`` for that.

Usage::

    python -m scripts.evidence_agreement --store-cache data/store/x.pt \\
        --supervision data/evidence/<tag>/supervision.jsonl \\
        --checkpoints data/checkpoints/bc.pt data/checkpoints/vcsd.pt --out reports/x.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from reps.strategy import read_supervision
from train.evidence import summarize
from train.student import NetworkStudent, evidence_agreement


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--store-cache", required=True)
    p.add_argument("--supervision", nargs="+", required=True)
    p.add_argument("--checkpoints", nargs="+", required=True)
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--min-pairs", type=int, default=8)
    p.add_argument("--out", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = torch.load(args.store_cache, map_location="cpu", weights_only=False)
    records = [record for path in args.supervision for record in read_supervision(path)]
    report: dict = {
        "store_cache": args.store_cache,
        "supervision": list(args.supervision),
        "evidence": summarize(records, alpha=args.alpha, min_pairs=args.min_pairs),
        "checkpoints": {},
    }
    for checkpoint in args.checkpoints:
        student = NetworkStudent.from_checkpoint(checkpoint)
        row: dict = {}
        for split in ("train", "val"):
            store = payload[split]
            position = {tuple(key): i for i, key in enumerate(store.keys)}
            matched = [(record, position[tuple(record.store_key)]) for record in records
                       if tuple(record.store_key) in position
                       and int(store.options[position[tuple(record.store_key)]].shape[0]) == len(record.options)
                       and int(store.teacher[position[tuple(record.store_key)]]) == record.expert_index]
            dists = student.store_distributions(store, [pos for _record, pos in matched])
            choices = {tuple(record.store_key): max(range(len(dist)), key=lambda i: (dist[i], -i))
                       for (record, _pos), dist in zip(matched, dists)}
            row[split] = evidence_agreement(choices, [record for record, _pos in matched],
                                            alpha=args.alpha, min_pairs=args.min_pairs)
        report["checkpoints"][checkpoint] = row
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
