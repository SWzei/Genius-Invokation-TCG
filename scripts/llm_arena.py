"""Compare model / knowledge configurations by playing them (small, budgeted, resumable).

Every *contestant* is a policy spec (``llm:<profile>#kb=<knowledge>``, but any spec
works, so a scripted or neural baseline can sit in the same table). Each plays the
same games: one deck against a list of scripted opponents, the same seeds, both
seats -- so two contestants are compared on identical matchups (paired).

    python -m scripts.llm_arena --deck natlan_battleship \\
        --contestants "llm:deepseek-chat" "llm:deepseek-chat#kb=rules-strategy" heuristic \\
        --opponents superconduct_aggro unyielding_geo --seeds 2 --max-calls 600 --tag kb_ab

Reported per contestant: win rate (Wilson 95%), how often the model's own answer
was used (vs fallback), error kinds, latency, tokens, cost; and for every other
contestant the paired difference against the first one. Results are appended game
by game to ``<data>/llm_arena/<tag>.jsonl``; re-running the same command resumes.

This is a screening tool. Model calls cost money: ``--max-calls`` / ``--max-cost``
stop the run when the total is reached. Seeds start at 1 (engine seed 0 is
degenerate). An LLM player never enters strength acceptance (``AGENTS.md``).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import time
from pathlib import Path
from typing import Any

from common.paths import data_dir, ensure_dir, reports_dir


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--deck", required=True, help="the deck every contestant plays")
    p.add_argument("--contestants", nargs="+", required=True, help="policy specs; '<deck>' expands to --deck")
    p.add_argument("--opponents", nargs="+", required=True, help="scripted opponent decks")
    p.add_argument("--seeds", type=int, default=1, help="seeds per opponent and seat")
    p.add_argument("--seed-start", type=int, default=1)
    p.add_argument("--sides", nargs="+", type=int, default=[0, 1], choices=[0, 1])
    p.add_argument("--max-calls", type=int, default=None, help="stop once this many model calls were made in total")
    p.add_argument("--max-cost", type=float, default=None, help="stop once the summed cost reaches this")
    p.add_argument("--tag", required=True)
    return p


def _play(deck: str, opponent: str, seed: int, side: int, spec: str) -> dict[str, Any]:
    from common.seeding import derive_seed
    from envs.decks import deck_spec
    from envs.match import run_match
    from envs.policy import build_policy
    from eval.stats import outcome_score

    role, opp_role = ("p0", "p1") if side == 0 else ("p1", "p0")
    contestant = build_policy(spec, seed=derive_seed(seed, role, deck), role=role)
    rival = build_policy(f"expert:{opponent}", seed=derive_seed(seed, opp_role, opponent), role=opp_role)
    started = time.perf_counter()
    if side == 0:
        record = run_match(deck_spec(deck), deck_spec(opponent), contestant, rival, seed=seed)
    else:
        record = run_match(deck_spec(opponent), deck_spec(deck), rival, contestant, seed=seed)
    summary = contestant.summary() if callable(getattr(contestant, "summary", None)) else {}
    return {
        "contestant": spec, "opponent": opponent, "seed": seed, "side": side,
        "winner": record.winner, "score": None if record.error else outcome_score(record.winner, side),
        "error": record.error, "rounds": record.rounds,
        "decisions": record.decisions0 if side == 0 else record.decisions1,
        "engine_fallbacks": record.fallbacks0 if side == 0 else record.fallbacks1,
        "wall_seconds": round(time.perf_counter() - started, 2), "llm": summary,
    }


def summarise(rows: list[dict[str, Any]], contestants: list[str]) -> dict[str, Any]:
    from eval.stats import estimate_rate

    table: dict[str, Any] = {}
    for spec in contestants:
        mine = [r for r in rows if r["contestant"] == spec and r["score"] is not None]
        usage = [r["llm"].get("usage", {}) for r in mine if r.get("llm")]
        by_source: dict[str, int] = {}
        errors: dict[str, int] = {}
        for r in mine:
            for key, value in (r.get("llm", {}).get("by_source") or {}).items():
                by_source[key] = by_source.get(key, 0) + int(value)
            for key, value in (r.get("llm", {}).get("errors") or {}).items():
                errors[key] = errors.get(key, 0) + int(value)
        decided = sum(v for k, v in by_source.items() if k != "forced")
        calls = sum(int(u.get("calls", 0)) + int(u.get("errors", 0)) for u in usage)
        cost_known = bool(usage) and all(u.get("cost") is not None for u in usage)
        table[spec] = {
            "games": len(mine),
            "win_rate": estimate_rate(sum(r["score"] for r in mine), len(mine)).as_dict() if mine else None,
            "invalid_games": sum(1 for r in rows if r["contestant"] == spec and r["score"] is None),
            "engine_fallbacks": sum(int(r["engine_fallbacks"]) for r in mine),
            "model_answer_rate": round(by_source.get("llm", 0) / decided, 4) if decided else None,
            "decision_sources": by_source, "errors": errors, "calls": calls,
            "prompt_tokens": sum(int(u.get("prompt_tokens", 0)) for u in usage),
            "completion_tokens": sum(int(u.get("completion_tokens", 0)) for u in usage),
            "seconds_per_call": round(sum(float(u.get("total_seconds", 0)) for u in usage) / calls, 3) if calls else None,
            "cost": round(sum(float(u["cost"]) for u in usage), 6) if cost_known else None,
        }
    base = contestants[0]
    key = lambda r: (r["opponent"], r["seed"], r["side"])
    base_scores = {key(r): r["score"] for r in rows if r["contestant"] == base and r["score"] is not None}
    paired = {}
    for spec in contestants[1:]:
        diffs = [r["score"] - base_scores[key(r)] for r in rows
                 if r["contestant"] == spec and r["score"] is not None and key(r) in base_scores]
        n = len(diffs)
        if n == 0:
            paired[spec] = {"n_pairs": 0}
            continue
        mean = sum(diffs) / n
        var = sum((d - mean) ** 2 for d in diffs) / (n - 1) if n > 1 else 0.0
        se = (var / n) ** 0.5
        paired[spec] = {"vs": base, "n_pairs": n, "delta": round(mean, 4),
                        "ci95": [round(mean - 1.96 * se, 4), round(mean + 1.96 * se, 4)] if n > 1 else None}
    return {"contestants": table, "paired_vs_first": paired}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.seed_start < 1:
        raise SystemExit("--seed-start must be >= 1 (engine seed 0 is degenerate)")
    from common.lock import load_engine_lock, runtime_metadata

    contestants = [c.replace("<deck>", args.deck) for c in args.contestants]
    out_path = ensure_dir(data_dir() / "llm_arena") / f"{args.tag}.jsonl"
    rows: list[dict[str, Any]] = []
    if out_path.exists():
        with out_path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    break
    done = {(r["contestant"], r["opponent"], r["seed"], r["side"]) for r in rows}
    seeds = range(args.seed_start, args.seed_start + args.seeds)
    todo = [(spec, opp, seed, side) for seed in seeds for opp in args.opponents
            for side in sorted(set(args.sides)) for spec in contestants]

    def totals() -> tuple[int, float]:
        calls = sum(int(r.get("llm", {}).get("usage", {}).get("calls", 0))
                    + int(r.get("llm", {}).get("usage", {}).get("errors", 0)) for r in rows)
        cost = sum(float(r.get("llm", {}).get("usage", {}).get("cost") or 0.0) for r in rows)
        return calls, cost

    stopped = None
    for spec, opponent, seed, side in todo:
        if (spec, opponent, seed, side) in done:
            continue
        calls, cost = totals()
        if args.max_calls is not None and calls >= args.max_calls:
            stopped = f"max_calls reached ({calls})"
            break
        if args.max_cost is not None and cost >= args.max_cost:
            stopped = f"max_cost reached ({cost:.4f})"
            break
        row = _play(args.deck, opponent, int(seed), int(side), spec)
        rows.append(row)
        with out_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[arena] {spec} vs {opponent} seed={seed} side={side} score={row['score']} "
              f"err={row['error']} {row['wall_seconds']}s", flush=True)
    calls, cost = totals()
    report = {
        "tag": args.tag, "generated": _dt.datetime.now().isoformat(timespec="seconds"),
        "deck": args.deck, "contestants": contestants, "opponents": list(args.opponents),
        "seeds": list(seeds), "sides": sorted(set(args.sides)),
        "games_planned": len(todo), "games_done": len(rows), "stopped": stopped,
        "total_calls": calls, "total_cost": round(cost, 6),
        **summarise(rows, contestants),
        "note": "screening run; paired differences on a handful of games are not strength results",
        "engine_lock": load_engine_lock(), "runtime": runtime_metadata(),
    }
    report_path = Path(ensure_dir(reports_dir() / "llm")) / f"llm_arena_{args.tag}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("games_done", "stopped", "total_calls", "total_cost",
                                             "contestants", "paired_vs_first")}, ensure_ascii=False, indent=1))
    print(f"[arena] raw {out_path}\n[arena] report {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
