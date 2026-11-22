"""Stage-wise optimisation of how the knowledge base reaches the model (D32).

The KB content stays fixed; what is "trained" is the adapter: which rule sections are
retrieved, which strategy units are shown, and targeted notes written from training
errors. Every stage is a knowledge profile in ``configs/knowledge.toml``
(``kbt-s0`` ... ``kbt-s3``) so any stage can be re-run later.

Data discipline: scenario sources carry a fixed ``split`` (train / dev / test, by source
game). Error analysis and every statistic fitted here (the unit frequency table) use
**train** only; stages are compared on **dev**; **test** is used once at the end.

    python -m bench.kb_train unit-frequency --sets v1 --out configs/knowledge/unit_frequency_train.json
    python -m bench.kb_train stages --set v2 --split dev --tag kbt_dev \\
        --runs kbt_dev_r1 kbt_dev_r2 --subjects "llm:deepseek-flash" "llm:deepseek-flash#kb=kbt-s0" ...
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.paths import REPO_ROOT, data_dir, ensure_dir, reports_dir
from common.pool import recycled_map


# --------------------------------------------------------------------------- #
# unit frequency (fitted on training sources)
# --------------------------------------------------------------------------- #
def _frequency_task(task: Mapping[str, Any]) -> dict[str, Any]:
    """Replay one recorded source game; count detector firings at every action decision."""
    from bench.scenarios import _Scripted, _run
    from reps.knowledge import matching_units

    class _Probe(_Scripted):
        def __init__(self, indices, counts, sink):
            super().__init__(indices, counts)
            self.sink = sink

        def choose(self, built):
            context = built.context
            if getattr(context.request_type, "value", "") == "action":
                self.sink["decisions"] += 1
                for unit in matching_units(context, version=task.get("kb_version", "")):
                    self.sink["fired"][unit] += 1
            return super().choose(built)

    source = task["source"]
    sink: dict[str, Any] = {"decisions": 0, "fired": Counter()}
    seats = [_Probe([d["index"] for d in source["trace"] if d["seat"] == s],
                    [d["n"] for d in source["trace"] if d["seat"] == s], sink) for s in (0, 1)]
    try:
        _run(source, seats)
    except Exception as exc:                        # pragma: no cover - reported, not raised
        return {"decisions": 0, "fired": {}, "error": f"{type(exc).__name__}: {exc}"[:200]}
    return {"decisions": sink["decisions"], "fired": dict(sink["fired"])}


def unit_frequency(set_specs: Sequence[str], workers: int = 2, kb_version: str = "") -> dict[str, Any]:
    """``set_specs``: ``name`` (all sources) or ``name:split``."""
    from bench.scenarios import load_set

    tasks, used = [], []
    for spec in set_specs:
        name, _, split = spec.partition(":")
        scenario_set = load_set(name)
        for i, source in enumerate(scenario_set["sources"]):
            if split and source.get("split") != split:
                continue
            tasks.append({"source": source, "kb_version": kb_version})
            used.append(f"{name}#{i}")
    results = list(recycled_map(_frequency_task, tasks, workers=workers, tasks_per_child=4))
    decisions = sum(r["decisions"] for r in results)
    fired: Counter = Counter()
    for r in results:
        fired.update(r["fired"])
    return {
        "what": "share of action decisions (both seats) at which each strategy unit's detector fires",
        "fitted_on": list(set_specs), **({"kb_version": kb_version} if kb_version else {}), "sources": len(used), "source_errors": sum(1 for r in results if r.get("error")),
        "action_decisions": decisions,
        "frequency": {k: round(v / max(1, decisions), 4) for k, v in sorted(fired.items(), key=lambda kv: -kv[1])},
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
    }


# --------------------------------------------------------------------------- #
# stage report
# --------------------------------------------------------------------------- #
def _rows(tag: str) -> list[dict[str, Any]]:
    path = data_dir("bench", tag) / "scenarios.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sign_p(better: int, worse: int) -> float:
    n = better + worse
    if n == 0:
        return 1.0
    k = min(better, worse)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def _wilson(k: float, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(max(0.0, p * (1 - p) / n + z * z / (4 * n * n)))
    return [round((c - h) / d, 3), round((c + h) / d, 3)]


def stage_report(set_name: str, split: str, runs: Sequence[str], subjects: Sequence[str],
                 metric: str = "converted") -> dict[str, Any]:
    """Per subject: score per run, the mean over runs, and per-item paired comparisons
    (items scored by their mean over runs) against the first subject, the previous one,
    and every other subject in the list (sign test on items whose mean differs)."""
    from bench.scenarios import load_set

    scenario_set = load_set(set_name)
    # split "all": every lethal item (v1 predates splits and belongs to training as a whole)
    ids = [s["id"] for s in scenario_set["scenarios"]
           if s["kind"] == "lethal" and (split == "all" or s.get("split") == split)]
    score: dict[str, dict[str, list[float]]] = {s: defaultdict(list) for s in subjects}
    per_run: dict[str, dict[str, Any]] = {s: {} for s in subjects}
    extra: dict[str, dict[str, float]] = {s: Counter() for s in subjects}
    for tag in runs:
        latest = {}
        for row in _rows(tag):
            if row.get("kind") == "lethal" and metric in row and row["subject"] in score:
                latest[(row["subject"], row["id"])] = row
        for subject in subjects:
            got = [latest[(subject, i)] for i in ids if (subject, i) in latest]
            if not got:
                continue
            hits = sum(1 for r in got if r[metric])
            per_run[subject][tag] = {"n": len(got), "hits": hits, "rate": round(hits / len(got), 4)}
            for r in got:
                score[subject][r["id"]].append(1.0 if r[metric] else 0.0)
                extra[subject]["prompt_tokens"] += int(r.get("prompt_tokens") or 0)
                extra[subject]["completion_tokens"] += int(r.get("completion_tokens") or 0)
                extra[subject]["calls"] += int(r.get("calls") or 0)
                extra[subject]["cost"] += float(r.get("cost") or 0)
                extra[subject]["rows"] += 1
                extra[subject]["first_illegal"] += 0 if r.get("first_reply_legal", True) else 1
    table = []
    for subject in subjects:
        items = {i: sum(v) / len(v) for i, v in score[subject].items() if v}
        n_obs = sum(len(v) for v in score[subject].values())
        hits = sum(sum(v) for v in score[subject].values())
        e = extra[subject]
        table.append({
            "subject": subject, "items": len(items), "observations": n_obs,
            "mean": round(hits / n_obs, 6) if n_obs else None, "ci95_obs": _wilson(hits, n_obs),
            "per_run": per_run[subject],
            "tokens_in_per_call": round(e["prompt_tokens"] / e["calls"], 1) if e["calls"] else None,
            "calls_per_item": round(e["calls"] / e["rows"], 2) if e["rows"] else None,
            "cost": round(e["cost"], 5), "first_reply_illegal_items": int(e["first_illegal"]),
        })

    def compare(a: str, b: str) -> dict[str, Any] | None:
        sa = {i: sum(v) / len(v) for i, v in score[a].items() if v}
        sb = {i: sum(v) / len(v) for i, v in score[b].items() if v}
        common = sorted(set(sa) & set(sb))
        if not common:
            return None
        diffs = [sa[i] - sb[i] for i in common]
        better, worse = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
        m = sum(diffs) / len(diffs)
        sd = (sum((d - m) ** 2 for d in diffs) / (len(diffs) - 1)) ** 0.5 if len(diffs) > 1 else 0.0
        se = sd / len(diffs) ** 0.5
        return {"a": a, "b": b, "n": len(common), "delta": round(m, 4),
                "ci95": [round(m - 1.96 * se, 4), round(m + 1.96 * se, 4)],
                "better_items": better, "worse_items": worse, "sign_test_p": round(_sign_p(better, worse), 4)}

    comparisons = []
    for k, subject in enumerate(subjects):
        for other in subjects[:k]:
            row = compare(subject, other)
            if row:
                comparisons.append(row)
    # run-to-run agreement of each subject (same configuration, different runs)
    stability = {}
    for subject in subjects:
        pairs = [v for v in score[subject].values() if len(v) >= 2]
        if pairs:
            stability[subject] = {"items_with_2_runs": len(pairs),
                                  "disagree": sum(1 for v in pairs if v[0] != v[1])}
    return {"set": set_name, "split": split, "metric": metric, "runs": list(runs), "items_in_split": len(ids),
            "table": table, "comparisons": comparisons, "stability": stability,
            "generated": _dt.datetime.now().isoformat(timespec="seconds")}


def render_stage_markdown(report: Mapping[str, Any], title: str) -> str:
    lines = [f"# {title}", "",
             f"场景集 `{report['set']}`，划分 `{report['split']}`（{report['items_in_split']} 道斩杀题），指标 `{report['metric']}`，"
             f"轮次 {', '.join(report['runs'])}；生成于 {report['generated']}。", "",
             "| 受试者 | 题数 | 观测数 | 均值 [95% CI，按观测] | 各轮 | 每题调用 | 每次输入 token | 费用（美元，估算） |",
             "|---|---|---|---|---|---|---|---|"]
    for e in report["table"]:
        runs = "；".join(f"{t}: {v['hits']}/{v['n']}" for t, v in e["per_run"].items())
        mean = "—" if e["mean"] is None else f"{e['mean']:.3f} [{e['ci95_obs'][0]:.2f}, {e['ci95_obs'][1]:.2f}]"
        lines.append(f"| `{e['subject']}` | {e['items']} | {e['observations']} | {mean} | {runs} | "
                     f"{e['calls_per_item']} | {e['tokens_in_per_call']} | {e['cost']} |")
    lines += ["", "## 逐题配对（每题取各轮均值；符号检验只计均值不同的题）", "",
              "| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |", "|---|---|---|---|---|---|"]
    for c in report["comparisons"]:
        lines.append(f"| `{c['a']}` | `{c['b']}` | {c['n']} | {c['delta']:+.3f} [{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}] | "
                     f"{c['better_items']} / {c['worse_items']} | {c['sign_test_p']:.3f} |")
    if report["stability"]:
        lines += ["", "## 同一配置的轮间一致性", "", "| 受试者 | 有两轮的题 | 两轮结果不同 |", "|---|---|---|"]
        for s, v in report["stability"].items():
            lines.append(f"| `{s}` | {v['items_with_2_runs']} | {v['disagree']} |")
    return "\n".join(lines) + "\n"


def write_stage_report(set_name: str, split: str, runs: Sequence[str], subjects: Sequence[str], tag: str,
                       title: str, metric: str = "converted") -> dict[str, Any]:
    report = stage_report(set_name, split, runs, subjects, metric)
    report["tag"] = tag
    out = Path(ensure_dir(reports_dir() / "bench"))
    (out / f"{tag}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / f"{tag}.md").write_text(render_stage_markdown(report, title), encoding="utf-8")
    return report


# --------------------------------------------------------------------------- #
# whole games pooled over runs
# --------------------------------------------------------------------------- #
def _arm(spec: str) -> tuple[str, list[tuple[str, str]]]:
    """``ALIAS=TAG:SUBJECT[;TAG:SUBJECT...]`` (a subject may contain ``:``; the tag may not)."""
    alias, sep, rest = spec.partition("=")
    if not sep or not rest:
        raise ValueError(f"arm must be ALIAS=TAG:SUBJECT[;TAG:SUBJECT...], got {spec!r}")
    runs = []
    for part in rest.split(";"):
        tag, sep, subject = part.partition(":")
        if not sep:
            raise ValueError(f"run must be TAG:SUBJECT, got {part!r}")
        runs.append((tag.strip(), subject.strip()))
    return alias.strip(), runs


def games_report(arms: Sequence[str]) -> dict[str, Any]:
    """Pool ``bench.run`` games of one configuration over several runs and compare
    configurations cell by cell (each cell's score = its mean over that arm's runs)."""
    table, cells_by_arm = [], {}
    for spec in arms:
        alias, runs = _arm(spec)
        per_cell: dict[str, list[float]] = defaultdict(list)
        per_run, invalid, cost, calls, asked, legal = {}, 0, 0.0, 0, 0, 0
        for tag, subject in runs:
            path = data_dir("bench", tag) / "games.jsonl"
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            rows = [r for r in rows if r["subject"] == subject]
            valid = [r for r in rows if r.get("score") is not None and not r.get("error") and not r.get("degraded")]
            invalid += len(rows) - len(valid)
            per_run[f"{tag}"] = {"games": len(valid), "score": round(sum(r["score"] for r in valid) / max(1, len(valid)), 4)}
            for r in valid:
                per_cell[r["cell"]].append(float(r["score"]))
                llm = r.get("llm") or {}
                cost += float((llm.get("usage") or {}).get("cost") or 0.0)
                calls += int(llm.get("calls") or 0)
                asked += int(llm.get("asked") or 0)
                legal += int(llm.get("first_reply_legal") or 0)
        obs = [v for vals in per_cell.values() for v in vals]
        table.append({"arm": alias, "runs": [f"{t}:{s}" for t, s in runs], "per_run": per_run, "games": len(obs),
                      "invalid": invalid, "score": round(sum(obs) / max(1, len(obs)), 6) if obs else None,
                      "ci95": _wilson(sum(obs), len(obs)), "cost_per_game": round(cost / max(1, len(obs)), 5),
                      "calls_per_game": round(calls / max(1, len(obs)), 1),
                      "first_reply_legal": round(legal / max(1, asked), 4) if asked else None})
        cells_by_arm[alias] = {c: sum(v) / len(v) for c, v in per_cell.items()}
    comparisons = []
    names = [t["arm"] for t in table]
    for i, a in enumerate(names):
        for b in names[:i]:
            common = sorted(set(cells_by_arm[a]) & set(cells_by_arm[b]))
            diffs = [cells_by_arm[a][c] - cells_by_arm[b][c] for c in common]
            if not diffs:
                continue
            m = sum(diffs) / len(diffs)
            sd = (sum((d - m) ** 2 for d in diffs) / max(1, len(diffs) - 1)) ** 0.5
            se = sd / len(diffs) ** 0.5
            better, worse = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
            comparisons.append({"a": a, "b": b, "cells": len(common), "delta": round(m, 4),
                                "ci95": [round(m - 1.96 * se, 4), round(m + 1.96 * se, 4)],
                                "better_cells": better, "worse_cells": worse, "sign_test_p": round(_sign_p(better, worse), 4)})
    return {"arms": table, "comparisons": comparisons, "generated": _dt.datetime.now().isoformat(timespec="seconds")}


def render_games_markdown(report: Mapping[str, Any], title: str) -> str:
    lines = [f"# {title}", "", f"生成于 {report['generated']}。每格得分 = 该配置各轮在此格的平均分；配对按格。", "",
             "| 配置 | 轮次（tag: 局数 → 胜率） | 有效局 | 胜率 [95% CI，按局] | 无效局 | 每局调用 | 首答合法率 | 每局费用（美元，估算） |",
             "|---|---|---|---|---|---|---|---|"]
    for a in report["arms"]:
        runs = "；".join(f"{t}: {v['games']} → {v['score']:.3f}" for t, v in a["per_run"].items())
        score = "—" if a["score"] is None else f"{a['score']:.3f} [{a['ci95'][0]:.2f}, {a['ci95'][1]:.2f}]"
        legal = "—" if a["first_reply_legal"] is None else f"{a['first_reply_legal']:.3f}"
        lines.append(f"| `{a['arm']}` | {runs} | {a['games']} | {score} | {a['invalid']} | {a['calls_per_game']} | "
                     f"{legal} | {a['cost_per_game']:.4f} |")
    lines += ["", "## 逐格配对", "", "| A | B | 格数 | A − B [95% CI] | A 更好 / 更差 | p |", "|---|---|---|---|---|---|"]
    for c in report["comparisons"]:
        lines.append(f"| `{c['a']}` | `{c['b']}` | {c['cells']} | {c['delta']:+.3f} [{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}] | "
                     f"{c['better_cells']} / {c['worse_cells']} | {c['sign_test_p']:.3f} |")
    lines += ["", "子配置配对时，若两边轮数不同，格得分的噪声也不同；符号检验只计得分不同的格。"]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("unit-frequency")
    f.add_argument("--sets", nargs="+", required=True, help="scenario sets as name or name:split")
    f.add_argument("--out", required=True)
    f.add_argument("--workers", type=int, default=2)
    f.add_argument("--kb-version", default="", help="detector table of this KB version string (D34), e.g. 1.0-s1")
    s = sub.add_parser("stages")
    s.add_argument("--set", required=True)
    s.add_argument("--split", required=True, choices=["train", "dev", "test", "all"])
    s.add_argument("--runs", nargs="+", required=True, help="scenario-eval tags, one per run")
    s.add_argument("--subjects", nargs="+", required=True)
    s.add_argument("--tag", required=True)
    s.add_argument("--title", default="知识接入阶段比较")
    s.add_argument("--metric", default="converted", choices=["converted", "correct", "kept"])
    g = sub.add_parser("games")
    g.add_argument("--arm", action="append", required=True,
                   help="ALIAS=TAG:SUBJECT[;TAG:SUBJECT...] -- one configuration pooled over runs (repeatable)")
    g.add_argument("--tag", required=True)
    g.add_argument("--title", default="整局：按配置合并多轮")
    args = parser.parse_args(argv)
    if args.cmd == "games":
        report = games_report(args.arm)
        out = Path(ensure_dir(reports_dir() / "bench"))
        (out / f"{args.tag}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / f"{args.tag}.md").write_text(render_games_markdown(report, args.title), encoding="utf-8")
        print(f"[kb_train] report: reports/bench/{args.tag}.md")
        return 0
    if args.cmd == "unit-frequency":
        payload = unit_frequency(args.sets, args.workers, args.kb_version)
        out = Path(args.out)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({k: v for k, v in payload.items() if k != "frequency"}, ensure_ascii=False))
        print(json.dumps(payload["frequency"], ensure_ascii=False))
        return 0
    write_stage_report(args.set, args.split, args.runs, args.subjects, args.tag, args.title, args.metric)
    print(f"[kb_train] report: reports/bench/{args.tag}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
