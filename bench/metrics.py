"""Outcome metrics beyond the winner for mirror pairs (D37), and their validation.

Per game, from the subject's side, using the public end state recorded by ``bench.play``
(``row["outcome"]``, per seat):

* ``W`` win 1 / draw 0.5 / loss 0;
* ``H`` own surviving HP share minus the opponent's (alive characters' HP / all max HP);
* ``K`` (opponent characters defeated - own defeated) / 3;
* ``D`` damage dealt / (dealt + taken) - 0.5 (0 when no damage).

Pair value: ``W`` -> sum of the two games - 1; ``H`` / ``K`` / ``D`` -> sum of the two games.
Both games of a pair have the same seed, decks and seats with the players swapped, so a
pair value is antisymmetric: swapping subject and rival negates it.

    python -m bench.metrics report --tag T [T ...] --out NAME          # any mirror run
    python -m bench.metrics validate --known T1 T2 --null T3 --out NAME  # D37 calibration
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import random
from statistics import NormalDist
from typing import Any, Iterable, Mapping, Sequence

from common.paths import data_dir, ensure_dir, reports_dir

METRICS = ("W", "H", "K", "D")
NAMES = {"W": "胜负", "H": "生命差", "K": "击倒差", "D": "伤害占比"}
EPS = 1e-9


def game_metrics(row: Mapping[str, Any]) -> dict[str, float] | None:
    """Subject-side metrics of one game row, or None without a usable outcome."""
    outcome = row.get("outcome")
    if row.get("score") is None or not outcome:
        return None
    me, op = int(row["side"]), 1 - int(row["side"])
    hp, max_hp = outcome["hp"], outcome["max_hp"]
    share = [hp[i] / max_hp[i] if max_hp[i] else 0.0 for i in (0, 1)]
    taken = outcome["damage_taken"]
    total = taken[0] + taken[1]
    return {"W": float(row["score"]), "H": share[me] - share[op],
            "K": (outcome["defeated"][op] - outcome["defeated"][me]) / 3.0,
            "D": (taken[op] / total - 0.5) if total else 0.0}


def pair_value(metric: str, games: Sequence[Mapping[str, float]]) -> float:
    total = sum(g[metric] for g in games)
    return total - 1.0 if metric == "W" else total


def _usable(row: Mapping[str, Any]) -> bool:
    return row.get("score") is not None and not row.get("error") and not row.get("truncated") \
        and not row.get("degraded") and not row.get("rival_degraded")


def pairs_from_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, float]], int]:
    """Rows of one subject -> per-pair metric values (whole pairs only) and the dropped count."""
    latest: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        latest[row["cell"]] = row
    grouped: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    for row in latest.values():
        grouped.setdefault((row["group"], int(row.get("rep", 0))), []).append(row)
    out, dropped = [], 0
    for key, games in sorted(grouped.items()):
        metrics = [game_metrics(g) for g in games]
        if len(games) != 2 or not all(_usable(g) for g in games) or any(m is None for m in metrics):
            dropped += 1
            continue
        values = {m: pair_value(m, metrics) for m in METRICS}
        values["rep"] = key[1]
        values["seat0_subject_won"] = next(float(g["score"]) for g in games if int(g["side"]) == 0)
        out.append(values)
    return out, dropped


def sign_p_one_sided(better: int, worse: int) -> float:
    n = better + worse
    if n == 0:
        return 1.0
    return sum(math.comb(n, j) for j in range(better, n + 1)) / 2 ** n


def stats(values: Sequence[float]) -> dict[str, Any]:
    n = len(values)
    if n == 0:
        return {"pairs": 0}
    better = sum(v > EPS for v in values)
    worse = sum(v < -EPS for v in values)
    even = n - better - worse
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else 0.0
    half = 1.96 * sd / math.sqrt(n) if n > 1 else 0.0
    return {"pairs": n, "better": better, "worse": worse, "even": even,
            "pair_rate": round((better + even / 2) / n, 4), "tie_rate": round(even / n, 4),
            "mean": round(mean, 4), "sd": round(sd, 4), "ci95": [round(mean - half, 4), round(mean + half, 4)],
            "p_one": round(sign_p_one_sided(better, worse), 4)}


def n80(s: Mapping[str, Any]) -> float:
    """Pairs needed for a one-sided sign test (alpha 0.05, power 0.8) at the observed effect."""
    decisive = s.get("better", 0) + s.get("worse", 0)
    if not decisive:
        return math.inf
    p = s["better"] / decisive
    if p <= 0.5:
        return math.inf
    za, zb = NormalDist().inv_cdf(0.95), NormalDist().inv_cdf(0.8)
    m = ((za * 0.5 + zb * math.sqrt(p * (1 - p))) / (p - 0.5)) ** 2
    return round(m / max(1e-9, 1 - s["tie_rate"]), 1)


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return round(cov / (vx * vy), 4) if vx and vy else None


def null_rejection(values: Sequence[float], *, size: int = 40, draws: int = 2000, seed: int = 37) -> float:
    """Share of bootstrap subsamples (``size`` pairs) where the one-sided sign test rejects at 0.05."""
    rng = random.Random(seed)
    hits = 0
    for _ in range(draws):
        sample = [values[rng.randrange(len(values))] for _ in range(size)]
        s = stats(sample)
        hits += s["p_one"] < 0.05
    return round(hits / draws, 4)


def _load(tag: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    run = data_dir("bench", tag)
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (run / "games.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    return meta, rows


def arms(tags: Sequence[str], *, pool: bool = False) -> list[dict[str, Any]]:
    """One arm per (tag, subject); with ``pool`` the tags are stages of one comparison (disjoint pairs)."""
    loaded = [(tag, *_load(tag)) for tag in tags]
    if pool:
        meta = loaded[0][1]
        rows = [r for _, _, rs in loaded for r in rs]
        loaded = [("+".join(tags), meta, rows)]
    out = []
    for tag, meta, rows in loaded:
        for subject in meta.get("subjects", []):
            pairs, dropped = pairs_from_rows(r for r in rows if r.get("subject") == subject)
            entry = {"tag": tag, "subject": subject, "rival": meta.get("rival", ""), "dropped_pairs": dropped,
                     "pairs": len(pairs), "metrics": {m: stats([p[m] for p in pairs]) for m in METRICS}}
            for m in METRICS:
                entry["metrics"][m]["n80"] = n80(entry["metrics"][m])
            if pairs:
                entry["seat0_win_rate"] = round(sum(p["seat0_subject_won"] for p in pairs) / len(pairs), 4)
            entry["values"] = pairs
            out.append(entry)
    return out


def render_report(rows: Sequence[Mapping[str, Any]], title: str) -> str:
    lines = [f"# {title}", "", f"生成于 {_dt.datetime.now().isoformat(timespec='seconds')}。", "",
             "| 轮次 | 受试者 | 对手 | 有效对 | 指标 | 对胜率 | 好 / 平 / 差 | 单侧 p | 对分均值 [95% CI] |",
             "|---|---|---|---|---|---|---|---|---|"]
    for a in rows:
        for m in METRICS:
            s = a["metrics"][m]
            if not s.get("pairs"):
                continue
            lines.append(f"| {a['tag']} | `{a['subject']}` | `{a['rival']}` | {s['pairs']} | {m} {NAMES[m]} "
                         f"| {s['pair_rate']:.3f} | {s['better']} / {s['even']} / {s['worse']} | {s['p_one']:.4f} "
                         f"| {s['mean']:+.3f} [{s['ci95'][0]:+.3f}, {s['ci95'][1]:+.3f}] |")
    lines += ["", "口径：一对 = 同一种子、同样两副牌、同样座位，双方各坐一次座位 0。指标取自对局结束时的公开状态与公开伤害事件"
              "（`bench.metrics`）。W 的对分 = 两局胜负之和 − 1；H / K / D 的对分 = 两局之和。对胜率 =（好 + 平/2）/ 对数；"
              "单侧符号检验（H1：受试者更好），平局不计。任一局出错、截断或模型应答率 < 90% 的对整对剔除。模拟器内结果，不进强度验收。", ""]
    return "\n".join(lines)


def validate(known: Sequence[str], null: Sequence[str]) -> dict[str, Any]:
    """D37 §3.2: calibration (null), direction, sensitivity (n80), validity (Spearman with W)."""
    known_arms, null_arms = arms(known), arms(null)
    result: dict[str, Any] = {"known": [], "null": [], "verdict": {}}
    for a in known_arms:
        result["known"].append({"tag": a["tag"], "subject": a["subject"], "rival": a["rival"], "pairs": a["pairs"],
                                "metrics": a["metrics"]})
    for a in null_arms:
        values = a["values"]
        result["null"].append({"tag": a["tag"], "subject": a["subject"], "rival": a["rival"], "pairs": a["pairs"],
                               "metrics": a["metrics"],
                               "rejection_40": {m: null_rejection([p[m] for p in values]) for m in METRICS}})
    pooled = [p for a in known_arms for p in a["values"]]
    for m in METRICS:
        calibrated = all(n["rejection_40"][m] <= 0.08 and n["metrics"][m]["ci95"][0] <= 0 <= n["metrics"][m]["ci95"][1]
                         for n in result["null"])
        # the known direction (subject stronger by construction); W's own estimate is reported beside it
        direction = all(k["metrics"][m]["mean"] > 0 for k in result["known"])
        sens = sum(k["metrics"][m]["n80"] for k in result["known"])
        sens_w = sum(k["metrics"]["W"]["n80"] for k in result["known"])
        rho = spearman([p[m] for p in pooled], [p["W"] for p in pooled])
        result["verdict"][m] = {"calibrated": calibrated, "direction": direction, "n80_sum": sens,
                                "n80_sum_W": sens_w, "sensitive": sens <= sens_w, "spearman_W": rho,
                                "valid": (rho or 0) >= 0.5,
                                "passes": calibrated and direction and sens <= sens_w and (rho or 0) >= 0.5}
    passing = [m for m in METRICS if result["verdict"][m]["passes"]]
    result["primary"] = min(passing, key=lambda m: result["verdict"][m]["n80_sum"]) if passing else "W"
    return result


def render_validation(v: Mapping[str, Any], title: str) -> str:
    lines = [f"# {title}", "", "## 已知差距的比较", "",
             "| 轮次 | 受试者 | 对手 | 对 | 指标 | 对胜率 | 好 / 平 / 差 | 单侧 p | n80 |", "|---|---|---|---|---|---|---|---|---|"]
    for k in v["known"]:
        for m in METRICS:
            s = k["metrics"][m]
            lines.append(f"| {k['tag']} | `{k['subject']}` | `{k['rival']}` | {s['pairs']} | {m} | {s['pair_rate']:.3f} "
                         f"| {s['better']} / {s['even']} / {s['worse']} | {s['p_one']:.4f} | {s['n80']} |")
    lines += ["", "## 空白对照（A/A）", "",
              "| 轮次 | 对 | 指标 | 对胜率 | 对分均值 [95% CI] | 40 对子样本拒绝率 |", "|---|---|---|---|---|---|"]
    for n in v["null"]:
        for m in METRICS:
            s = n["metrics"][m]
            lines.append(f"| {n['tag']} | {s['pairs']} | {m} | {s['pair_rate']:.3f} | {s['mean']:+.3f} "
                         f"[{s['ci95'][0]:+.3f}, {s['ci95'][1]:+.3f}] | {n['rejection_40'][m]:.3f} |")
    lines += ["", "## 逐项判定", "",
              "| 指标 | 校准 | 方向 | n80 合计（W） | 灵敏度 | 与 W 的 Spearman | 效度 | 通过 |", "|---|---|---|---|---|---|---|---|"]
    for m in METRICS:
        r = v["verdict"][m]
        lines.append(f"| {m} {NAMES[m]} | {'是' if r['calibrated'] else '否'} | {'是' if r['direction'] else '否'} "
                     f"| {r['n80_sum']}（{r['n80_sum_W']}） | {'是' if r['sensitive'] else '否'} | {r['spearman_W']} "
                     f"| {'是' if r['valid'] else '否'} | **{'是' if r['passes'] else '否'}** |")
    lines += ["", f"按预先登记的规则，主指标为 **{v['primary']}**。", "",
              "口径：n80 = 单侧符号检验 α = 0.05、功效 0.8 所需对数（按观察到的好差比例与平局比例换算）；"
              "拒绝率 = 从 A/A 的对中有放回抽 40 对、2,000 次，单侧 p < 0.05 的比例。", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Outcome metrics for mirror pairs (D37).")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("report")
    r.add_argument("--tag", nargs="+", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--title", default="镜像对战：多维指标")
    r.add_argument("--pool", action="store_true", help="treat the tags as stages of one comparison")
    v = sub.add_parser("validate")
    v.add_argument("--known", nargs="+", required=True)
    v.add_argument("--null", nargs="+", required=True)
    v.add_argument("--out", required=True)
    v.add_argument("--title", default="评测指标校准（脚本策略）")
    args = parser.parse_args(argv)
    out = ensure_dir(reports_dir("bench"))
    if args.command == "report":
        rows = arms(args.tag, pool=args.pool)
        (out / f"{args.out}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        text = render_report(rows, args.title)
    else:
        result = validate(args.known, args.null)
        (out / f"{args.out}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        text = render_validation(result, args.title)
    (out / f"{args.out}.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
