"""D38 post-hoc summary: every same-model "knowledge base vs none" comparison, every criterion.

Exploratory by construction (written after all results were seen, at the user's request):
it does not pick a criterion, it computes all of them on every comparison and reports all.
Reads existing data only; no model calls.

    python -m scripts.d38_posthoc_summary --out d38_posthoc
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from bench import metrics as M
from common.paths import REPO_ROOT

DATA = REPO_ROOT / "data" / "bench"
KB = "kbt3-trig"


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def sign_p(better: int, worse: int) -> float:
    return M.sign_p_one_sided(better, worse)


def z_of_p(p: float) -> float:
    """One-sided p -> z (inverse normal survival), by bisection on erfc."""
    p = min(max(p, 1e-12), 1 - 1e-12)
    lo, hi = -10.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if 0.5 * math.erfc(mid / math.sqrt(2)) > p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def stouffer(ps: Sequence[float], weights: Sequence[float]) -> float:
    z = sum(w * z_of_p(p) for p, w in zip(ps, weights)) / math.sqrt(sum(w * w for w in weights))
    return 0.5 * math.erfc(z / math.sqrt(2))


def rate_ci(better: int, even: int, worse: int) -> tuple[float, float, float]:
    """Pair win rate (better + even/2) / n with a normal-approximation 95% CI on per-pair scores."""
    n = better + even + worse
    scores = [1.0] * better + [0.5] * even + [0.0] * worse
    mean = sum(scores) / n
    var = sum((s - mean) ** 2 for s in scores) / max(1, n - 1)
    half = 1.96 * math.sqrt(var / n)
    return round(mean, 3), round(max(0.0, mean - half), 3), round(min(1.0, mean + half), 3)


# --------------------------------------------------------------------------- #
# items
# --------------------------------------------------------------------------- #
def situ_rows(tag: str, model: str, mode: str = "reason") -> dict[str, dict[str, bool]]:
    """{kb: {item id: correct}} keeping the last answered row per (kb, id)."""
    out: dict[str, dict[str, bool]] = defaultdict(dict)
    for line in (DATA / tag / "situ.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["model"] != model or r.get("mode") not in (mode, None) or not r.get("ok"):
            continue
        out[r["kb"]][r["id"]] = bool(r["correct"])
    return out


def paired_items(runs: Sequence[Mapping[str, Mapping[str, bool]]], ids: Iterable[str] | None = None,
                 kb: str = KB) -> dict[str, Any]:
    """Per item, mean correctness over runs for each arm; sign test on the per-item difference."""
    common = None
    for run in runs:
        keys = set(run.get("none", {})) & set(run.get(kb, {}))
        common = keys if common is None else common & keys
    common = sorted(common & set(ids)) if ids is not None else sorted(common or ())
    better = worse = 0
    none_acc = kb_acc = 0.0
    for i in common:
        a = sum(run["none"][i] for run in runs) / len(runs)
        b = sum(run[kb][i] for run in runs) / len(runs)
        none_acc += a
        kb_acc += b
        better += b > a
        worse += b < a
    n = len(common)
    if not n:
        return {"n": 0}
    return {"n": n, "none": round(none_acc / n, 3), "kb": round(kb_acc / n, 3),
            "delta": round((kb_acc - none_acc) / n, 3), "kb_only": better, "none_only": worse,
            "p": round(sign_p(better, worse), 4)}


def interaction(weak: Mapping[str, Mapping[str, bool]], strong: Sequence[Mapping[str, Mapping[str, bool]]],
                ids: Iterable[str], kb: str = KB, draws: int = 4000, seed: int = 38) -> dict[str, Any]:
    """Is the KB gain larger for the weaker model on the same items? Per item: (gain weak) - (gain strong)."""
    import random

    ids = sorted(i for i in ids if all(i in r["none"] and i in r[kb] for r in [weak, *strong]))
    diffs = []
    for i in ids:
        gw = weak[kb][i] - weak["none"][i]
        gs = sum(r[kb][i] - r["none"][i] for r in strong) / len(strong)
        diffs.append(gw - gs)
    n = len(diffs)
    mean = sum(diffs) / n
    rng = random.Random(seed)
    boots = sorted(sum(rng.choice(diffs) for _ in range(n)) / n for _ in range(draws))
    better, worse = sum(d > 1e-9 for d in diffs), sum(d < -1e-9 for d in diffs)
    return {"n": n, "mean_gain_difference": round(mean, 3),
            "ci95_bootstrap": [round(boots[int(0.025 * draws)], 3), round(boots[int(0.975 * draws)], 3)],
            "weak_gain_larger": better, "strong_gain_larger": worse, "p_sign_one_sided": round(sign_p(better, worse), 4)}


def lethal_rows(tag: str) -> dict[str, dict[str, bool]]:
    out: dict[str, dict[str, bool]] = defaultdict(dict)
    for line in (DATA / tag / "scenarios.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("kind") != "lethal":
            continue
        value = r.get("correct", r.get("converted"))       # v3 was run with --convert (wins before the opponent acts)
        if value is not None:
            out[r["subject"]][r["id"]] = bool(value)
    return out


def items_section() -> dict[str, Any]:
    res: dict[str, Any] = {}
    ds = [situ_rows("kbt3_v3_situ_reason_r1", "deepseek-flash"), situ_rows("kbt3_v3_situ_reason_r2", "deepseek-flash")]
    glm = situ_rows("kbt3_v3_situ_glm_reason_r1", "glm-flash")
    glm_ids = set(glm["none"]) & set(glm[KB])
    test_ids = {i for i in glm_ids}
    res["situ_v3_test_glm47"] = paired_items([glm], test_ids)
    res["situ_v3_test_deepseek_r1"] = paired_items(ds[:1], test_ids)
    res["situ_v3_test_deepseek_r1r2"] = paired_items(ds, test_ids)
    res["situ_v3_all_deepseek_r1r2"] = paired_items(ds)
    res["interaction_glm47_vs_deepseek_v3_test"] = interaction(glm, ds, test_ids)
    for name in ("situ_v3_test_glm47", "situ_v3_test_deepseek_r1r2"):
        r = res[name]
        r["headroom_closed"] = round(r["delta"] / (1 - r["none"]), 3) if r["none"] < 1 else None
    ds_ans = [situ_rows("kbt3_v3_situ_answer_r1", "deepseek-flash", "answer"),
              situ_rows("kbt3_v3_situ_answer_r2", "deepseek-flash", "answer")]
    res["situ_v3_all_deepseek_answer_r1r2"] = paired_items(ds_ans)
    res["situ_v3_test_deepseek_answer_r1r2"] = paired_items(ds_ans, test_ids)
    son = situ_rows("d38_sonnet_situ", "subagent-sonnet")
    son_ids = set(son["none"]) & set(son[KB])
    res["situ_dev_sample_sonnet"] = paired_items([son], son_ids)
    r = res["situ_dev_sample_sonnet"]
    r["headroom_closed"] = round(r["delta"] / (1 - r["none"]), 3)
    ds_dev = [situ_rows("kbt_situ_dev_reason_r1", "deepseek-flash"), situ_rows("kbt_situ_dev_reason_r2", "deepseek-flash")]
    res["situ_dev_sonnet_overlap_deepseek_r1r2"] = paired_items(ds_dev, son_ids)
    res["situ_dev_sonnet_overlap_sonnet"] = paired_items([son], son_ids & set(ds_dev[0].get("none", {})))
    res["situ_dev245_deepseek_r1r2"] = paired_items(ds_dev)
    # lethal
    v3 = [lethal_rows("kbt3_v3_lethal_r1"), lethal_rows("kbt3_v3_lethal_r2")]
    runs = [{"none": r["llm:deepseek-flash"], KB: r[f"llm:deepseek-flash#kb={KB},reply=reason_first"]} for r in v3]
    res["lethal_v3_convert_deepseek_r1r2"] = paired_items(runs)   # no-KB arm also lacks reason_first
    s = lethal_rows("d38_sonnet_lethal")
    res["lethal_v2dev_sonnet"] = paired_items([{"none": s["llm:subagent-sonnet#reply=reason_first,elements=1"],
                                                KB: s[f"llm:subagent-sonnet#kb={KB},reply=reason_first,elements=1"]}])
    return res


# --------------------------------------------------------------------------- #
# games
# --------------------------------------------------------------------------- #
def game_rows(tag: str, subject: str) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in (DATA / tag / "games.jsonl").read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if r["subject"] == subject]


def w_only(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Games without a recorded end state: W per pair and per game."""
    latest = {r["cell"] if isinstance(r["cell"], str) else json.dumps(r["cell"], sort_keys=True): r for r in rows}
    grouped: dict[Any, list[Mapping[str, Any]]] = defaultdict(list)
    for r in latest.values():
        grouped[(r["group"], int(r.get("rep", 0)))].append(r)
    better = worse = even = 0
    gw = gl = gd = 0
    for games in grouped.values():
        if len(games) != 2 or any(g.get("error") or g.get("truncated") or g.get("degraded") or g.get("rival_degraded")
                                  or g.get("score") is None for g in games):
            continue
        total = sum(float(g["score"]) for g in games) - 1.0
        better += total > 1e-9
        worse += total < -1e-9
        even += abs(total) <= 1e-9
        for g in games:
            s = float(g["score"])
            gw += s == 1.0
            gl += s == 0.0
            gd += s == 0.5
    rate, lo, hi = rate_ci(better, even, worse)
    return {"pairs": better + even + worse, "W": {"better": better, "even": even, "worse": worse, "rate": rate,
                                                 "ci": [lo, hi], "p": round(sign_p(better, worse), 4)},
            "games": {"won": gw, "lost": gl, "drawn": gd,
                      "rate": round((gw + gd / 2) / max(1, gw + gl + gd), 3),
                      "p_binomial": round(sign_p(gw, gl), 4)}}


def full(pairs: Sequence[Mapping[str, float]]) -> dict[str, Any]:
    out: dict[str, Any] = {"pairs": len(pairs)}
    for m in M.METRICS:
        s = M.stats([p[m] for p in pairs])
        out[m] = {k: s[k] for k in ("better", "even", "worse", "pair_rate", "p_one", "mean", "ci95") if k in s}
    tb = M.tiebreak(pairs)
    out["tiebreak"] = {rule: {k: tb["rules"][rule][k] for k in ("rate", "ci95", "won", "even", "lost", "p_one")}
                       for rule, _ in M.TIEBREAK_RULES}
    return out


def games_section() -> dict[str, Any]:
    res: dict[str, Any] = {}
    ds_old = "llm:deepseek-flash#kb=kbt3-trig,reply=reason_first"
    ds_new = "llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1"
    res["deepseek_d34_dev80_oldobs"] = w_only(game_rows("d34_ab_v10_dev", ds_old))
    res["deepseek_d36_test150"] = w_only(game_rows("d36_test_main", ds_new))
    res["deepseek_train_replay50"] = full(M.replay_pairs(str(DATA / "d37_facts_train" / "replays.jsonl"))["全部"])
    res["deepseek_train_replay50"]["note"] = "teacher material (train), not an independent evaluation"
    for name, tag, subject in [
        ("glm4flash_d38_dev50", "d38_glm4", "llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1"),
        ("glm4flash_facts_d38_dev50", "d38_glm4", "llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1,facts=1"),
        ("decision1_d38_dev50", "d38_decision", "llm:gemini-decision-1#kb=kbt3-trig,elements=1"),
    ]:
        rows = game_rows(tag, subject)
        pairs, dropped = M.pairs_from_rows(rows)
        res[name] = full(pairs)
        res[name]["dropped"] = dropped
        res[name]["games"] = w_only(rows)["games"]
    # DeepSeek pooled over the two independent, pre-registered held-out runs (W only)
    a, b = res["deepseek_d34_dev80_oldobs"]["W"], res["deepseek_d36_test150"]["W"]
    better, worse, even = a["better"] + b["better"], a["worse"] + b["worse"], a["even"] + b["even"]
    rate, lo, hi = rate_ci(better, even, worse)
    res["deepseek_pooled_dev80_test150"] = {
        "W": {"better": better, "even": even, "worse": worse, "rate": rate, "ci": [lo, hi],
              "p_pooled_sign": round(sign_p(better, worse), 4),
              "p_stouffer_sqrt_n": round(stouffer([a["p"], b["p"]], [math.sqrt(80), math.sqrt(150)]), 4),
              "p_stouffer_equal": round(stouffer([a["p"], b["p"]], [1, 1]), 4)},
        "note": "post-hoc pooling; D34 used the old observation layer, D36 elements=1"}
    return res


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    report = {"items": items_section(), "games": games_section()}
    path = REPO_ROOT / "reports" / "bench" / f"{args.out}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
