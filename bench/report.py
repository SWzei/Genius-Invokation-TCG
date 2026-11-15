"""Aggregate benchmark rows into the report (JSON-safe dict + Markdown)."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from eval.scoreboard import MatchOutcome, paired_difference
from eval.stats import estimate_rate
from reps.strategy import sign_test_p

AXES = (("group", "by_group"), ("opponent_level", "by_level"), ("deck_kind", "by_deck_kind"),
        ("version", "by_version"), ("side", "by_side"))


def _valid(row: Mapping[str, Any]) -> bool:
    return row.get("score") is not None and not row.get("truncated") and not row.get("degraded")


def _rate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    est = estimate_rate(sum(float(r["score"]) for r in rows), len(rows))
    return {"n": est.games, "rate": round(est.rate, 4), "ci95": [round(est.low, 4), round(est.high, 4)]}


def _outcomes(rows: Iterable[Mapping[str, Any]]) -> list[MatchOutcome]:
    # cluster = the matchup (group, deck, opponent); the pair key adds seed and side
    return [MatchOutcome(opponent=f"{r['group']}|{r['deck']}|{r['opponent']}", seed=int(r["seed"]),
                         side=int(r["side"]), score=float(r["score"])) for r in rows]


def _subject_block(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    valid = [r for r in rows if _valid(r)]
    block: dict[str, Any] = {
        "games": len(rows), "valid_games": len(valid),
        "invalid_games": sum(1 for r in rows if r.get("score") is None or r.get("truncated")),
        "degraded_games": sum(1 for r in rows if r.get("degraded")),
        "win_rate": _rate(valid),
        "engine_fallbacks": sum(int(r.get("engine_fallbacks") or 0) for r in rows),
        "io_errors": sum(int(r.get("io_errors") or 0) for r in rows),
        "mean_rounds": round(sum(int(r.get("rounds") or 0) for r in valid) / len(valid), 2) if valid else None,
        "game_seconds_mean": round(sum(float(r.get("wall_seconds") or 0) for r in rows) / len(rows), 2) if rows else None,
    }
    for field, name in AXES:
        table: dict[str, Any] = {}
        for value in sorted({str(r.get(field) if r.get(field) not in ("", None) else "default") for r in valid}):
            table[value] = _rate([r for r in valid
                                  if str(r.get(field) if r.get(field) not in ("", None) else "default") == value])
        block[name] = table
    llm_rows = [r for r in rows if r.get("llm")]
    if llm_rows:
        summaries = [r["llm"] for r in llm_rows]
        usage = [s.get("usage") or {} for s in summaries]
        asked = sum(int(s.get("asked", 0)) for s in summaries)
        used = sum(int((s.get("by_source") or {}).get("llm", 0)) for s in summaries)
        fallback = sum(int((s.get("by_source") or {}).get("fallback", 0)) for s in summaries)
        first_legal = sum(int(s.get("first_reply_legal", 0)) for s in summaries)
        calls = sum(int(u.get("calls", 0)) + int(u.get("errors", 0)) for u in usage)
        seconds = sum(float(u.get("total_seconds", 0)) for u in usage)
        prompt = sum(int(u.get("prompt_tokens", 0)) for u in usage)
        completion = sum(int(u.get("completion_tokens", 0)) for u in usage)
        cost_known = all(u.get("cost") is not None for u in usage)
        cost = sum(float(u.get("cost") or 0.0) for u in usage)
        errors: dict[str, int] = {}
        first_errors: dict[str, int] = {}
        by_request: dict[str, dict[str, int]] = {}
        for s in summaries:
            for key, value in (s.get("errors") or {}).items():
                errors[key] = errors.get(key, 0) + int(value)
            for key, value in (s.get("first_errors") or {}).items():
                first_errors[key] = first_errors.get(key, 0) + int(value)
            for request, counts in (s.get("by_request") or {}).items():
                slot = by_request.setdefault(request, {"asked": 0, "first_legal": 0, "used": 0})
                for key in slot:
                    slot[key] += int(counts.get(key, 0))
        p50 = sorted(float((s.get("decision_seconds") or {}).get("p50") or 0) for s in summaries)
        p90 = sorted(float((s.get("decision_seconds") or {}).get("p90") or 0) for s in summaries)
        n = len(llm_rows)
        block["model"] = {
            "games": n, "decisions_asked": asked,
            # legality of the model's own answers; executed actions are always legal
            "first_reply_legal_rate": round(first_legal / asked, 4) if asked else None,
            "answer_used_rate": round(used / asked, 4) if asked else None,
            "fallback_decisions": fallback,
            "first_errors": first_errors, "errors": errors, "by_request": by_request,
            "calls": calls, "retries": sum(int(u.get("retries", 0)) for u in usage),
            "seconds_per_call": round(seconds / calls, 3) if calls else None,
            "decision_seconds_p50_median_game": p50[len(p50) // 2] if p50 else None,
            "decision_seconds_p90_median_game": p90[len(p90) // 2] if p90 else None,
            "decision_seconds_max": max((float((s.get("decision_seconds") or {}).get("max") or 0)
                                         for s in summaries), default=None),
            "prompt_tokens": prompt, "completion_tokens": completion,
            "reasoning_tokens": sum(int(u.get("reasoning_tokens", 0)) for u in usage),
            "cached_tokens": sum(int(u.get("cached_tokens", 0)) for u in usage),
            "tokens_per_decision": round((prompt + completion) / asked, 1) if asked else None,
            "tokens_per_game": round((prompt + completion) / n, 0),
            "calls_per_game": round(calls / n, 1),
            "cost": round(cost, 6) if cost_known else None,
            "cost_per_game": round(cost / n, 6) if cost_known else None,
        }
    return block


def build_report(suite: Any, rows: Sequence[Mapping[str, Any]], subjects: Sequence[str],
                 *, reference: str | None = None) -> dict[str, Any]:
    latest: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in rows:                       # a retried cell: the last row wins
        latest[(row["subject"], row["cell"])] = row
    known = {c.key for c in suite.cells}
    by_subject = {s: [r for (subj, key), r in latest.items() if subj == s and key in known] for s in subjects}
    table = {s: _subject_block(by_subject[s]) for s in subjects if by_subject[s]}
    reference = reference if reference in table else (next(iter(table)) if table else None)
    paired: dict[str, Any] = {}
    if reference is not None:
        ref_valid = [r for r in by_subject[reference] if _valid(r)]
        ref_scores = {r["cell"]: float(r["score"]) for r in ref_valid}
        for spec in table:
            if spec == reference:
                continue
            mine = [r for r in by_subject[spec] if _valid(r) and r["cell"] in ref_scores]
            stats = paired_difference(_outcomes(mine), _outcomes([r for r in ref_valid
                                                                  if r["cell"] in {m["cell"] for m in mine}]))
            if stats is None:
                paired[spec] = {"vs": reference, "n_pairs": 0}
                continue
            wins = sum(1 for r in mine if float(r["score"]) > ref_scores[r["cell"]])
            losses = sum(1 for r in mine if float(r["score"]) < ref_scores[r["cell"]])
            paired[spec] = {
                "vs": reference, "n_pairs": stats["n_pairs"], "delta": round(stats["delta"], 4),
                "ci95": [round(stats["ci_low"], 4), round(stats["ci_high"], 4)],
                "matchup_cluster_boot_ci95": [round(stats["cluster_boot_ci_low"], 4),
                                              round(stats["cluster_boot_ci_high"], 4)],
                "better": wins, "worse": losses, "same": stats["n_pairs"] - wins - losses,
                "sign_test_p": round(sign_test_p(wins, losses), 4),
            }
    return {"suite": suite.as_dict(), "subjects": table, "reference": reference, "paired_vs_reference": paired,
            "note": ("win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid "
                     "games (errors, truncations and degraded games excluded and counted)")}


# --------------------------------------------------------------------------- #
def _fmt_rate(rate: Mapping[str, Any] | None) -> str:
    if not rate:
        return "—"
    return f"{rate['rate']:.3f} [{rate['ci95'][0]:.2f}, {rate['ci95'][1]:.2f}] (n={rate['n']})"


def display_path(path: Any) -> str:
    """``path`` relative to the repository when it lies inside it (reports are committed
    and read on other machines; an absolute path from the machine that ran them is noise)."""
    from pathlib import Path

    from common.paths import REPO_ROOT

    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def render_markdown(report: Mapping[str, Any]) -> str:
    suite = report["suite"]
    lines = [f"# Benchmark `{report.get('tag', suite['name'])}` — suite `{suite['name']}` ({suite['fingerprint']})", "",
             f"- cells: {suite['cells']} ({', '.join(f'{k} {v}' for k, v in suite['cells_by_group'].items())}); "
             f"seed base {suite['seed_base']}",
             f"- generated: {report.get('generated', '')}; stopped: {report.get('stopped')}; "
             f"model calls {report.get('total_calls', 0)}, cost {report.get('total_cost', 0)}", "",
             "## Win rate (Wilson 95%)", "",
             "| subject | valid / games | overall | " + " | ".join(
                 sorted({k for b in report["subjects"].values() for k in b["by_level"]})) + " |",
             ]
    levels = sorted({k for b in report["subjects"].values() for k in b["by_level"]})
    lines.append("|---|---|---|" + "---|" * len(levels))
    for spec, block in report["subjects"].items():
        lines.append(f"| `{spec}` | {block['valid_games']} / {block['games']} | {_fmt_rate(block['win_rate'])} | "
                     + " | ".join(_fmt_rate(block["by_level"].get(level)) for level in levels) + " |")
    for title, key in (("By group", "by_group"), ("By deck kind", "by_deck_kind"), ("By rules version", "by_version")):
        values = sorted({k for b in report["subjects"].values() for k in b[key]})
        if len(values) < 2:
            continue
        lines += ["", f"## {title}", "", "| subject | " + " | ".join(values) + " |", "|---|" + "---|" * len(values)]
        for spec, block in report["subjects"].items():
            lines.append(f"| `{spec}` | " + " | ".join(_fmt_rate(block[key].get(v)) for v in values) + " |")
    if report.get("paired_vs_reference"):
        lines += ["", f"## Paired difference vs `{report['reference']}` (same cells)", "",
                  "| subject | pairs | delta | 95% CI | better / worse / same | sign test p |", "|---|---|---|---|---|---|"]
        for spec, row in report["paired_vs_reference"].items():
            if not row.get("n_pairs"):
                lines.append(f"| `{spec}` | 0 | — | — | — | — |")
                continue
            lines.append(f"| `{spec}` | {row['n_pairs']} | {row['delta']:+.3f} | [{row['ci95'][0]:+.2f}, "
                         f"{row['ci95'][1]:+.2f}] | {row['better']} / {row['worse']} / {row['same']} | "
                         f"{row['sign_test_p']:.3f} |")
    models = {s: b["model"] for s, b in report["subjects"].items() if b.get("model")}
    if models:
        lines += ["", "## Model subjects: legality, latency, tokens", "",
                  "| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | "
                  "p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for spec, m in models.items():
            lines.append(
                f"| `{spec}` | {m['decisions_asked']} | {m['first_reply_legal_rate']} | {m['answer_used_rate']} | "
                f"{m['fallback_decisions']} | {m['seconds_per_call']} | {m['decision_seconds_p50_median_game']} / "
                f"{m['decision_seconds_p90_median_game']} / {m['decision_seconds_max']} | {m['tokens_per_decision']} | "
                f"{m['calls_per_game']} | {m['tokens_per_game']:.0f} | {m['cost_per_game']} |")
        lines += ["", "Errors (why a model answer was not used): "
                  + "; ".join(f"`{s}` {m['errors'] or '{}'}" for s, m in models.items())]
    quality = [f"`{s}` engine fallbacks {b['engine_fallbacks']}, invalid {b['invalid_games']}, "
               f"degraded {b['degraded_games']}" for s, b in report["subjects"].items()]
    lines += ["", "## Run health", "", "- " + "\n- ".join(quality), "", f"_{report['note']}_", ""]
    return "\n".join(lines)
