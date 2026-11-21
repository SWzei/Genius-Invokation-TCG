"""What does the knowledge base actually inject at real decisions? (offline, no model calls)

Plays benchmark cells with a non-model policy and, at every decision of the subject
seat, asks each knowledge profile's selector what it would put in the prompt. Records
which rule sections and strategy units were selected, how long the pack is, and the
version warnings -- the reach of the KB through the decision path, as opposed to its
size on disk.

    python -m bench.kb_probe --suite lite --profiles rules rules-strategy rules-strategy-full \
        --tag kb_probe --workers 2
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.paths import data_dir, ensure_dir, reports_dir


class _ProbePolicy:
    """Delegates to ``inner`` and records each profile's knowledge pack per decision."""

    def __init__(self, inner, selectors: Mapping[str, Any]) -> None:
        self.inner, self.selectors, self.rows = inner, dict(selectors), []
        self.warning_samples: dict[str, list[str]] = {}
        self.name = f"probe({getattr(inner, 'name', 'policy')})"

    def choose(self, built) -> int:
        context = built.context
        row: dict[str, Any] = {
            "request": getattr(context.request_type, "value", str(context.request_type)),
            "round": int(context.player_view.round_number) if context.player_view is not None else 0,
            "n_options": len(context.legal_low_level_specs),
            "kinds": sorted({spec.kind.value for spec in context.legal_low_level_specs}),
            "packs": {},
        }
        for name, selector in self.selectors.items():
            pack = selector.select(context)
            row["packs"][name] = {
                "rules": [i.id for i in pack.items if i.kind == "rule"],
                "strategy": [i.id for i in pack.items if i.kind == "strategy"],
                "chars": len(pack.text), "warnings": len(pack.warnings),
            }
            if pack.warnings and name not in self.warning_samples:
                self.warning_samples[name] = list(pack.warnings[:4])
        self.rows.append(row)
        return self.inner.choose(built)


def probe_cell(cell: Mapping[str, Any], decks: Mapping[str, Any] | None, profiles: Sequence[str],
               subject: str = "heuristic") -> dict[str, Any]:
    from bench.suite import Cell, resolve_deck
    from common.seeding import derive_seed
    from envs.match import run_match
    from envs.policy import build_policy
    from reps.knowledge_pack import KnowledgeSelector, get_knowledge_profile

    c = Cell.from_dict(cell)
    side = int(c.side)
    deck, opp_deck = resolve_deck(c.deck, decks), resolve_deck(c.opponent_deck, decks)
    role, opp_role = ("p0", "p1") if side == 0 else ("p1", "p0")
    selectors = {name: KnowledgeSelector(get_knowledge_profile(name)) for name in profiles}
    probe = _ProbePolicy(build_policy(subject.replace("<deck>", c.deck),
                                      seed=derive_seed(c.seed, role, c.deck), role=role), selectors)
    rival = build_policy(c.opponent_policy, seed=derive_seed(c.seed, opp_role, c.opponent_deck), role=opp_role)
    if side == 0:
        run_match(deck, opp_deck, probe, rival, seed=c.seed, version=c.version or None)
    else:
        run_match(opp_deck, deck, rival, probe, seed=c.seed, version=c.version or None)
    return {"cell": c.key, "deck": c.deck, "version": c.version, "decisions": probe.rows,
            "load_warnings": {name: sel.load_warnings for name, sel in selectors.items()},
            "warning_samples": probe.warning_samples}


def _probe_task(args):
    cell, decks, profiles, subject = args
    try:
        return probe_cell(cell, decks, profiles, subject)
    except Exception as exc:                       # pragma: no cover - reported, not raised
        return {"cell": cell.get("deck"), "error": f"{type(exc).__name__}: {exc}"[:300], "decisions": []}


def summarise(games: Sequence[Mapping[str, Any]], profiles: Sequence[str], kb) -> dict[str, Any]:
    decisions = [d for g in games for d in g["decisions"]]
    by_request = Counter(d["request"] for d in decisions)
    out: dict[str, Any] = {"games": len(games), "decisions": len(decisions), "by_request": dict(by_request),
                           "errors": [g["error"] for g in games if g.get("error")], "profiles": {}}
    for name in profiles:
        packs = [d["packs"][name] for d in decisions]
        rule_refs = Counter(r for p in packs for r in p["rules"])
        units = Counter(u for p in packs for u in p["strategy"])
        chars = sorted(p["chars"] for p in packs)
        per_request = defaultdict(lambda: {"n": 0, "with_rules": 0, "with_strategy": 0, "chars": 0})
        for d, p in zip(decisions, packs):
            slot = per_request[d["request"]]
            slot["n"] += 1
            slot["with_rules"] += bool(p["rules"])
            slot["with_strategy"] += bool(p["strategy"])
            slot["chars"] += p["chars"]
        signatures = Counter(tuple(p["rules"]) for p in packs if p["rules"])
        out["profiles"][name] = {
            "decisions_with_rules": sum(1 for p in packs if p["rules"]),
            "decisions_with_strategy": sum(1 for p in packs if p["strategy"]),
            "decisions_with_version_warning": sum(1 for p in packs if p["warnings"]),
            "chars_mean": round(sum(chars) / max(1, len(chars)), 1),
            "chars_p50": chars[len(chars) // 2] if chars else 0,
            "chars_max": chars[-1] if chars else 0,
            "distinct_rule_sections": len(rule_refs), "rule_sections": dict(rule_refs.most_common()),
            "distinct_units": len(units), "units": dict(units.most_common()),
            "distinct_rule_sets": len(signatures),
            "top_rule_sets": [{"rules": list(k), "n": v} for k, v in signatures.most_common(5)],
            "per_request": {k: {**v, "chars_mean": round(v["chars"] / max(1, v["n"]), 1)}
                            for k, v in per_request.items()},
        }
    from reps.knowledge import detector_ids

    out["kb"] = {"version": kb.version, "rule_sections": len(kb.rules), "units": len(kb.units),
                 "units_with_detector": len([u for u in kb.units if u in set(detector_ids())]),
                 "units_by_doc": dict(Counter(u.split("-")[0] for u in kb.units))}
    samples: dict[str, set] = defaultdict(set)
    for g in games:
        for name, texts in (g.get("warning_samples") or {}).items():
            samples[name].update(texts)
    out["warning_samples"] = {k: sorted(v)[:6] for k, v in samples.items()}
    return out


def render_markdown(report: Mapping[str, Any]) -> str:
    kb = report["kb"]
    lines = [f"# KB 注入体检 `{report['tag']}`", "",
             f"生成于 {report['generated']}；原始数据 `{report['raw']}`。受试座位策略 `{report['subject']}`；"
             f"{report['games']} 局、{report['decisions']} 个决策（{', '.join(f'{k} {v}' for k, v in report['by_request'].items())}）。", "",
             f"知识库 v{kb['version']}：规则 {kb['rule_sections']} 节，策略单元 {kb['units']} 个"
             f"（有条件检测器的 {kb['units_with_detector']} 个）。", "",
             "| 配置 | 有规则的决策 | 有策略的决策 | 版本告警的决策 | 不同规则节 | 不同规则组合 | 不同策略单元 | 平均字数 | 中位 | 最大 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    n = report["decisions"]
    for name, p in report["profiles"].items():
        lines.append(f"| {name} | {p['decisions_with_rules']}/{n} | {p['decisions_with_strategy']}/{n} | "
                     f"{p['decisions_with_version_warning']}/{n} | {p['distinct_rule_sections']} | {p['distinct_rule_sets']} | "
                     f"{p['distinct_units']} | {p['chars_mean']} | {p['chars_p50']} | {p['chars_max']} |")
    for name, p in report["profiles"].items():
        lines += ["", f"## {name}", "", "规则节（被选中的决策数）：" + "、".join(f"{k} {v}" for k, v in p["rule_sections"].items()),
                  "", "策略单元（被选中的决策数）：" + ("、".join(f"{k} {v}" for k, v in p["units"].items()) or "—"),
                  "", "| 决策类型 | 数量 | 有规则 | 有策略 | 平均字数 |", "|---|---|---|---|---|"]
        for req, v in p["per_request"].items():
            lines.append(f"| {req} | {v['n']} | {v['with_rules']} | {v['with_strategy']} | {v['chars_mean']} |")
    if report.get("warning_samples"):
        lines += ["", "## 版本告警示例", ""]
        for name, texts in report["warning_samples"].items():
            lines += [f"- {name}：" + "；".join(texts)]
    lines += ["", "口径：只统计受试座位的决策；选取只读行动方视图与合法选项，与真实模型对局时的选取代码相同。"]
    return "\n".join(lines) + "\n"


def run(suite: str, profiles: Sequence[str], *, tag: str, subject: str, workers: int,
        replicates: int | None) -> dict[str, Any]:
    from bench.report import display_path
    from bench.suite import load_suite
    from reps.knowledge import KnowledgeBase

    loaded = load_suite(suite)
    cells = [c for c in loaded.cells if replicates is None or int(c.rep) < replicates]
    decks = getattr(loaded, "decks", None)
    out_dir = Path(ensure_dir(data_dir("bench", tag)))
    tasks = [(c.as_dict(), decks, list(profiles), subject) for c in cells]
    with ProcessPoolExecutor(max_workers=max(1, workers), max_tasks_per_child=1) as pool:
        games = list(pool.map(_probe_task, tasks))
    raw = out_dir / "kb_probe.jsonl"
    raw.write_text("".join(json.dumps(g, ensure_ascii=False) + "\n" for g in games), encoding="utf-8")
    report = summarise(games, profiles, KnowledgeBase.load())
    report.update({"tag": tag, "subject": subject, "suite": suite, "generated": _dt.datetime.now().isoformat(timespec="seconds"),
                   "raw": display_path(raw)})
    target = Path(ensure_dir(reports_dir() / "bench"))
    (target / f"{tag}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (target / f"{tag}.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", default="lite")
    parser.add_argument("--profiles", nargs="+", default=["rules", "rules-strategy", "rules-strategy-full"])
    parser.add_argument("--subject", default="heuristic")
    parser.add_argument("--tag", default="kb_probe")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--replicates", type=int, default=None)
    args = parser.parse_args(argv)
    report = run(args.suite, args.profiles, tag=args.tag, subject=args.subject, workers=args.workers,
                 replicates=args.replicates)
    print(json.dumps({k: report[k] for k in ("games", "decisions", "by_request")}, ensure_ascii=False))
    print(f"[kb_probe] report: reports/bench/{args.tag}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
