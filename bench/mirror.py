"""Model-vs-model games (D34): build seat-and-deck-swapped pair suites and report them.

A *pair* is two games on one seed with the same two decks in the same seats
(``p0`` = deck X, ``p1`` = deck Y). The subject plays ``p0`` in the first game and
``p1`` in the second; the rival (``--rival`` of ``bench.run``) takes the other seat.
Seat, deck and shuffle advantages are identical for both players, so a pair score
(0, 0.5, ..., 2 wins) has mean 1 when the two players are equally strong. When
both players behave identically (A/A at temperature 0) every pair scores exactly 1;
how often it does not measures how non-deterministic a game is.

Decks: distinct tournament line-ups of the engine versions in ``VERSIONS`` (the
``test`` split of the tournament deck data, never a training pool), minus the two
decks the ``lite`` suites use. Deck codes are split by hash into ``train`` / ``dev``
/ ``test`` deck sets, so the three splits share neither seeds nor decks. ``aa``
(calibration) draws from the ``dev`` decks on its own seed block.

    python -m bench.mirror build --split dev --pairs 150
    python -m bench.run --suite configs/bench/mirror_dev.lock.json --subjects SPEC --rival SPEC --tag T
    python -m bench.mirror report --tag T [--tag T2 ...] --out NAME
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import random
from typing import Any, Iterable, Mapping

from bench.suite import BENCH_SEED_BASE, SUITE_DIR, Cell, Suite, engine_accepts, suite_to_lock
from common.paths import data_dir, ensure_dir, reports_dir

VERSIONS = ("v6.2.0", "v6.3.0")
SPLITS = {"train": 0, "dev": 1, "test": 2, "aa": 3}          # seed block index
DECK_SHARE = (("train", 4), ("dev", 3), ("test", 3))           # deck-set weights (of 10)
SEED_OFFSET = 300_000                                          # beyond every suite used before D34
RIVAL = "<rival>"


def deck_split(code: str) -> str:
    bucket = int(hashlib.sha256(code.encode("utf-8")).hexdigest(), 16) % 10
    for name, weight in DECK_SHARE:
        if bucket < weight:
            return name
        bucket -= weight
    raise AssertionError


def candidate_decks(excluded: Iterable[str] = ()) -> dict[str, dict[str, Any]]:
    """deck id -> table entry (with ``split``), distinct line-ups the engine accepts."""
    from envs.tournament_decks import iter_tournament_decks, unique_decks

    skip = set(excluded)
    out: dict[str, dict[str, Any]] = {}
    lineups: set[tuple[str, tuple[int, ...]]] = set()
    pool = [d for d in unique_decks(iter_tournament_decks(splits=["test"])) if d.engine_version in VERSIONS]
    for deck in sorted(pool, key=lambda d: d.deck_code):
        deck_id = f"human:{deck.deck_code[:12]}"
        lineup = (deck.engine_version, tuple(sorted(deck.characters)))
        if deck_id in skip or lineup in lineups or not engine_accepts(deck.spec(), deck.engine_version):
            continue
        lineups.add(lineup)
        out[deck_id] = {"characters": list(deck.characters), "cards": list(deck.cards),
                        "deck_code": deck.deck_code, "native_version": deck.engine_version,
                        "mirror_split": deck_split(deck.deck_code),
                        "tournament": deck.provenance.extra.get("tournament"),
                        "game_id": deck.provenance.extra.get("gameId")}
    return out


def lite_decks() -> set[str]:
    ids: set[str] = set()
    for name in ("lite", "lite_fresh"):
        path = SUITE_DIR / f"{name}.lock.json"
        if path.exists():
            ids |= {k for k in json.loads(path.read_text(encoding="utf-8")).get("decks", {}) if k.startswith("human:")}
    return ids


def build_pairs(split: str, n_pairs: int, decks: Mapping[str, Mapping[str, Any]]) -> Suite:
    deck_set = "dev" if split == "aa" else split
    by_version: dict[str, list[str]] = {}
    for deck_id, entry in sorted(decks.items()):
        if entry["mirror_split"] == deck_set:
            by_version.setdefault(entry["native_version"], []).append(deck_id)
    versions = [v for v in sorted(by_version) if len(by_version[v]) >= 2]
    if not versions:
        raise ValueError(f"mirror: no version has two {deck_set} decks")
    rng = random.Random(f"mirror:{split}")
    used: dict[str, dict[str, Any]] = {}
    cells: list[Cell] = []
    group = f"mirror-{split}"
    for rep in range(n_pairs):
        version = versions[rep % len(versions)]
        x, y = rng.sample(by_version[version], 2)
        seed = BENCH_SEED_BASE + SEED_OFFSET + 10_000 * SPLITS[split] + rep
        for deck, opp, side in ((x, y, 0), (y, x, 1)):          # p0 = x, p1 = y in both games
            cells.append(Cell(group, deck, f"rival@{opp}", "model", RIVAL, opp, version, seed, side, "human", rep))
        used[x], used[y] = decks[x], decks[y]
    return Suite(f"mirror_{split}", f"model-vs-model pairs ({split}): {n_pairs} pairs, seat and deck swapped",
                 cells, dict(sorted(used.items())), source=f"bench.mirror build --split {split} --pairs {n_pairs}")


# ---------------------------------------------------------------------------- report

def _load(tag: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run = data_dir("bench", tag)
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    with (run / "games.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return meta, rows


def _usable(row: Mapping[str, Any]) -> bool:
    return row.get("score") is not None and not row.get("error") and not row.get("degraded") \
        and not row.get("rival_degraded")


def sign_test(better: int, worse: int) -> float:
    n = better + worse
    if n == 0:
        return 1.0
    k = min(better, worse)
    return min(1.0, 2 * sum(math.comb(n, j) for j in range(k + 1)) / 2 ** n)


def pair_stats(scores: list[float]) -> dict[str, Any]:
    """Pair scores (0..2) -> win rate, 95% CI (normal over pairs), sign test on pairs."""
    n = len(scores)
    if n == 0:
        return {"pairs": 0}
    mean = sum(scores) / n
    var = sum((s - mean) ** 2 for s in scores) / (n - 1) if n > 1 else 0.0
    se = math.sqrt(var / n) / 2
    better = sum(s > 1 for s in scores)
    worse = sum(s < 1 for s in scores)
    return {"pairs": n, "win_rate": round(mean / 2, 4), "se": round(se, 4),
            "ci95": [round(mean / 2 - 1.96 * se, 4), round(mean / 2 + 1.96 * se, 4)],
            "pair_sd": round(math.sqrt(var), 4), "better": better, "worse": worse, "even": n - better - worse,
            "p_sign": round(sign_test(better, worse), 4)}


def _cost(row: Mapping[str, Any], side: str) -> float:
    return float(((row.get(side) or {}).get("usage") or {}).get("cost") or 0.0)


def summarise(tags: list[str]) -> dict[str, Any]:
    arms: list[dict[str, Any]] = []
    for tag in tags:
        meta, rows = _load(tag)
        rival = meta.get("rival", "")
        for subject in meta.get("subjects", []):
            mine = [r for r in rows if r.get("subject") == subject]
            latest: dict[str, dict[str, Any]] = {}
            for row in mine:                        # a resumed game: the last row counts
                latest[row["cell"]] = row
            pairs: dict[tuple[str, int], list[dict[str, Any]]] = {}
            for row in latest.values():
                pairs.setdefault((row["group"], int(row.get("rep", 0))), []).append(row)
            scores, dropped, p0_wins, p0_games, identical = [], 0, 0.0, 0, 0
            for key, games in sorted(pairs.items()):
                if len(games) != 2 or not all(_usable(g) for g in games):
                    dropped += 1
                    continue
                scores.append(sum(float(g["score"]) for g in games))
                for g in games:
                    p0_games += 1
                    p0_wins += float(g["score"]) if int(g["side"]) == 0 else 1.0 - float(g["score"])
                identical += games[0].get("winner") is not None and games[0].get("winner") == games[1].get("winner")
            usable = [r for r in latest.values() if _usable(r)]
            arms.append({
                "tag": tag, "subject": subject, "rival": rival, **pair_stats(scores),
                "dropped_pairs": dropped, "games": len(latest),
                "errors": sum(1 for r in latest.values() if r.get("error")),
                "degraded": sum(1 for r in latest.values() if r.get("degraded") or r.get("rival_degraded")),
                "seat0_win_rate": round(p0_wins / p0_games, 4) if p0_games else None,
                "same_seat_won_both": identical,
                "mean_rounds": round(sum(float(r.get("rounds") or 0) for r in usable) / len(usable), 2) if usable else None,
                "cost_per_game_subject": round(sum(_cost(r, "llm") for r in usable) / len(usable), 5) if usable else None,
                "cost_per_game_rival": round(sum(_cost(r, "rival_llm") for r in usable) / len(usable), 5) if usable else None,
            })
    return {"generated": _dt.datetime.now().isoformat(timespec="seconds"), "tags": tags, "arms": arms}


def render_markdown(report: Mapping[str, Any], title: str) -> str:
    lines = [f"# {title}", "",
             f"轮次 {', '.join(report['tags'])}；生成于 {report['generated']}。", "",
             "| 受试者 | 对手 | 有效对 | 胜率 [95% CI] | 好 / 平 / 差（对） | p（符号检验） | 弃对 | 座位 0 胜率 | 同座位两局都赢 | 平均回合 | 每局费用（美元，受试者 + 对手） |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in report["arms"]:
        if not a.get("pairs"):
            lines.append(f"| `{a['subject']}` | `{a['rival']}` | 0 | — | — | — | {a['dropped_pairs']} | — | — | — | — |")
            continue
        lines.append(
            f"| `{a['subject']}` | `{a['rival']}` | {a['pairs']} | {a['win_rate']:.3f} [{a['ci95'][0]:.3f}, {a['ci95'][1]:.3f}] "
            f"| {a['better']} / {a['even']} / {a['worse']} | {a['p_sign']:.3f} | {a['dropped_pairs']} "
            f"| {a['seat0_win_rate']:.3f} | {a['same_seat_won_both']}/{a['pairs']} | {a['mean_rounds']} "
            f"| {a['cost_per_game_subject']:.4f} + {a['cost_per_game_rival']:.4f} |")
    lines += ["", "口径：一对 = 同一种子、同样两副牌、同样座位，受试者与对手各坐一次座位 0；"
              "对分 0–2，胜率 = 对分均值 / 2，CI 按对计算（正态近似）。"
              "任一局出错或任一方模型应答率 < 90% 的对整对剔除。模拟器内结果，不进强度验收。", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Model-vs-model pair suites (D34).")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--split", required=True, choices=sorted(SPLITS))
    b.add_argument("--pairs", type=int, required=True)
    sub.add_parser("decks")
    r = sub.add_parser("report")
    r.add_argument("--tag", nargs="+", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--title", default="模型对战")
    args = parser.parse_args(argv)
    if args.command == "decks":
        decks = candidate_decks(lite_decks())
        counts: dict[str, int] = {}
        for entry in decks.values():
            key = f"{entry['mirror_split']}/{entry['native_version']}"
            counts[key] = counts.get(key, 0) + 1
        print(json.dumps(dict(sorted(counts.items())), indent=1))
    elif args.command == "build":
        suite = build_pairs(args.split, args.pairs, candidate_decks(lite_decks()))
        path = SUITE_DIR / f"mirror_{args.split}.lock.json"
        if path.exists():
            raise SystemExit(f"{path} exists (suites are append-only): delete it by hand if it was never played")
        path.write_text(json.dumps(suite_to_lock(suite), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(suite.as_dict(), ensure_ascii=False, indent=1)[:2000])
    else:
        report = summarise(args.tag)
        out = ensure_dir(reports_dir("bench"))
        (out / f"{args.out}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (out / f"{args.out}.md").write_text(render_markdown(report, args.title), encoding="utf-8")
        print(render_markdown(report, args.title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
