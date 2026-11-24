"""Mine traced *train* games for decision patterns, knowledge side vs plain side (D35).

D34's teacher read ~300k characters of digests through two subagents. This replays the
traced games (exact, ``bench.forks``) and counts a fixed list of objectively checkable
patterns on the seat's own view plus the chosen option -- no model calls, a few seconds
per game. The output is a short table (rate per 100 action decisions, each side) plus
a handful of examples per pattern with the model's stated reason, so the teacher reads
numbers first and only the decisions behind a gap.

Patterns (each is a candidate, not a verdict -- whether it was wrong needs the position):

* ``end_with_dice``   -- declare end with >= 3 dice and a usable skill while the opponent still acts
* ``end_after_opp``   -- the opponent already ended; declare end with >= 2 dice and a usable skill
* ``burst_skipped``   -- the active character's burst is playable now but a card is played instead
* ``draw_at_full_hand`` -- >= 9 cards in hand and a drawing card is played
* ``low_hp_end``      -- active character at <= 3 HP, a switch is possible, declare end
* ``tune_after_opp``  -- the opponent already ended and the seat tunes a card (dice vanish at round end)

    python -m bench.mirror_mine --tag d34_ab_v10_train --out d35_mine_v10_train

D36 adds two trace-only views (no replay, no model call):

* ``--natural``  -- the first decision where the two games of each pair differ (same seed and seat decks)
* ``--mulligan`` -- how often each side swaps its signature (character-only) and arcane cards; with
  ``--probe <tag>`` the same for every policy asked at those mulligans by ``bench.divergence probe``

    python -m bench.mirror_mine --tag d36_train_v10 --natural --out d36_natural_train
    python -m bench.mirror_mine --tag d36_train_v10 --mulligan --probe d36_r3_mech --out d36_r3_mech_mull
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping

from common.paths import ensure_dir, reports_dir

PATTERNS = ("end_with_dice", "end_after_opp", "burst_skipped", "draw_at_full_hand", "low_hp_end", "tune_after_opp")


def _kind(spec: Any) -> str:
    return getattr(spec.kind, "value", str(spec.kind))


def flags(context: Any, chosen: int, assets: Any) -> list[str]:
    """Patterns the chosen option matches at this decision (seat view only)."""
    rt = getattr(context.request_type, "value", str(context.request_type))
    if rt != "action":
        return []
    specs = list(context.legal_low_level_specs)
    kinds = {_kind(s) for s in specs}
    pick = specs[chosen]
    kind = _kind(pick)
    view = context.player_view
    me, opp = view.players[context.acting_player], view.players[1 - context.acting_player]
    dice = len(me.dice)
    active = next((c for c in me.characters if c.is_active and not c.defeated), None)
    alive = sum(1 for c in me.characters if not c.defeated)
    skill = "action_use_skill" in kinds
    out = []
    if kind == "action_declare_end":
        if not opp.declared_end and dice >= 3 and skill:
            out.append("end_with_dice")
        if opp.declared_end and dice >= 2 and skill:
            out.append("end_after_opp")
        if active is not None and active.health <= 3 and alive >= 2 and "action_switch_active" in kinds:
            out.append("low_hp_end")
    if kind == "action_play_card":
        burst = any(_kind(s) == "action_use_skill" and assets.get(int(s.subject_definition_id)).kind == "元素爆发"
                    for s in specs)
        if burst:
            out.append("burst_skipped")
        text = assets.get(int(pick.subject_definition_id)).description
        if len(me.hand_cards) >= 9 and "抓" in text:
            out.append("draw_at_full_hand")
    if kind == "action_elemental_tuning" and opp.declared_end:
        out.append("tune_after_opp")
    return out


def mine(tag: str, *, examples: int = 4) -> dict[str, Any]:
    from bench.divergence import _games, _source
    from bench.forks import replay
    from reps.describe import AssetText

    assets = AssetText.load()
    counts: dict[str, dict[str, int]] = {}
    actions: dict[str, int] = {}
    per_game: list[dict[str, Any]] = []
    samples: dict[str, list[dict[str, Any]]] = {p: [] for p in PATTERNS}
    broken = 0
    for path in _games(tag):
        source = _source(path)
        game_counts: dict[str, dict[str, int]] = {}

        def visit(seat: int, ordinal: int, built: Any) -> None:
            rec = source["seats"][seat][ordinal]
            role = "knowledge" if rec["role"] == "subject" else "plain"
            ctx = built.context
            if getattr(ctx.request_type, "value", str(ctx.request_type)) == "action" and rec["source"] != "forced":
                actions[role] = actions.get(role, 0) + 1
            for name in flags(ctx, rec["index"], assets):
                counts.setdefault(role, {}).setdefault(name, 0)
                counts[role][name] += 1
                game_counts.setdefault(role, {}).setdefault(name, 0)
                game_counts[role][name] += 1
                if len(samples[name]) < examples * 2:
                    samples[name].append({"side": role, "game": f"{source['seed']}|{source['subject_seat']}",
                                          "seat": seat, "ordinal": ordinal, "choice": rec["final_text"],
                                          "reason": (rec["reason"] or "")[:160], "knowledge": rec["knowledge"]})

        result = replay(source, on_decision=visit)
        if not result["ok"]:
            broken += 1
            continue
        subject_score = 1.0 if result["winner"] == source["subject_seat"] else 0.0 if result["winner"] is not None else 0.5
        per_game.append({"game": f"{source['seed']}|{source['subject_seat']}", "knowledge_score": subject_score,
                         "counts": game_counts})
    rates = {role: {p: round(100 * counts.get(role, {}).get(p, 0) / max(1, actions.get(role, 0)), 2) for p in PATTERNS}
             for role in ("knowledge", "plain")}
    # Does a pattern go with losing? Mean knowledge-side score of games where it occurred vs not.
    association = {}
    for p in PATTERNS:
        with_p = [g["knowledge_score"] for g in per_game if g["counts"].get("knowledge", {}).get(p)]
        without = [g["knowledge_score"] for g in per_game if not g["counts"].get("knowledge", {}).get(p)]
        association[p] = {"games_with": len(with_p), "score_with": round(sum(with_p) / len(with_p), 3) if with_p else None,
                          "score_without": round(sum(without) / len(without), 3) if without else None}
    return {"generated": _dt.datetime.now().isoformat(timespec="seconds"), "tag": tag, "games": len(per_game),
            "broken_replays": broken, "action_decisions": actions, "counts": counts, "rate_per_100_actions": rates,
            "knowledge_side_association": association,
            "examples": {p: v for p, v in samples.items() if v}}


def behaviour(probe_tag: str) -> dict[str, Any]:
    """Same positions, different policies (``bench.divergence probe`` answers): how often each
    policy's choice matches each pattern. A cheap mechanism check for a candidate KB version --
    did the new advice change behaviour where it was meant to? -- before any game is played."""
    from bench.divergence import _jsonl, _source
    from bench.forks import replay
    from common.paths import data_dir
    from reps.describe import AssetText

    assets = AssetText.load()
    rows = _jsonl(data_dir("bench", probe_tag, "positions.jsonl"))
    by_game: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_game.setdefault(row["path"], []).append(row)
    actions: dict[str, int] = {}
    hits: dict[str, dict[str, int]] = {}
    kinds: dict[str, dict[str, int]] = {}
    for path, game_rows in sorted(by_game.items()):
        source = _source(Path(path))
        wanted = {(r["seat"], r["ordinal"]) for r in game_rows}
        contexts: dict[tuple[int, int], Any] = {}

        def keep(seat: int, ordinal: int, built: Any) -> None:
            if (seat, ordinal) in wanted:
                contexts[(seat, ordinal)] = built.context

        if not replay(source, on_decision=keep)["ok"]:
            continue
        for r in game_rows:
            ctx = contexts.get((r["seat"], r["ordinal"]))
            if ctx is None or r.get("source") != "llm":
                continue
            if getattr(ctx.request_type, "value", str(ctx.request_type)) == "action":
                actions[r["policy"]] = actions.get(r["policy"], 0) + 1
                spec = ctx.legal_low_level_specs[int(r["index"])]
                kind = _kind(spec)
                if kind == "action_use_skill":
                    kind = "skill:" + assets.get(int(spec.subject_definition_id)).kind
                kinds.setdefault(r["policy"], {}).setdefault(kind, 0)
                kinds[r["policy"]][kind] += 1
            for name in flags(ctx, int(r["index"]), assets):
                hits.setdefault(r["policy"], {}).setdefault(name, 0)
                hits[r["policy"]][name] += 1
    return {"generated": _dt.datetime.now().isoformat(timespec="seconds"), "tag": probe_tag,
            "action_answers": actions, "hits": hits, "choice_kinds": kinds,
            "rate_per_100_actions": {p: {n: round(100 * hits.get(p, {}).get(n, 0) / max(1, a), 2) for n in PATTERNS}
                                     for p, a in sorted(actions.items())}}


# --- D36: natural divergence points and the opening mulligan -------------------------------------------
#
# Both games of a mirror pair share the seed and the seat decks, so they are identical until the two
# policies first choose differently: that decision is a free, exact divergence point (no replay, no
# model call). In D36 train it was the opening mulligan in 28 of 30 pairs.


def _trace_games(tag: str) -> list[dict[str, Any]]:
    from common.paths import data_dir

    games = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(data_dir("bench", tag, "traces").glob("*/*.json"))]
    for g in games:
        if not str(g["cell"].get("group", "")).endswith("train"):
            raise SystemExit("bench.mirror_mine reads train games only")
    return games


def seat_sequence(game: Mapping[str, Any]) -> list[tuple[int, int, str, Mapping[str, Any]]]:
    """(step, seat, role, trace) for every decision of a traced mirror game, in play order."""
    side = int(game["cell"]["side"])
    out = []
    for role, key in (("knowledge", "subject_traces"), ("plain", "rival_traces")):
        seat = side if role == "knowledge" else 1 - side
        out += [(int(t["step_index"]), seat, role, t) for t in game.get(key) or []]
    return sorted(out, key=lambda x: (x[0], x[1]))


def first_divergence(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any] | None:
    """The first decision where the two games of a pair differ (``None``: identical throughout)."""
    for i, (x, y) in enumerate(zip(seat_sequence(a), seat_sequence(b))):
        if x[1] != y[1] or x[3]["final_text"] != y[3]["final_text"]:
            return {"ordinal": i, "step": x[0], "seat": x[1], "request": x[3]["request_type"],
                    "a": {"role": x[2], "choice": x[3]["final_text"], "reason": (x[3].get("reason") or "")[:160]},
                    "b": {"role": y[2], "choice": y[3]["final_text"], "reason": (y[3].get("reason") or "")[:160]}}
    return None


def natural_divergence(tag: str) -> dict[str, Any]:
    pairs: dict[Any, dict[int, Mapping[str, Any]]] = {}
    for g in _trace_games(tag):
        pairs.setdefault(g["cell"]["seed"], {})[int(g["cell"]["side"])] = g
    rows, by_request = [], {}
    for seed, two in sorted(pairs.items()):
        if set(two) != {0, 1}:
            continue
        score = int(two[0]["winner"] == 0) + int(two[1]["winner"] == 1)
        dp = first_divergence(two[0], two[1])
        req = dp["request"] if dp else "none"
        by_request[req] = by_request.get(req, 0) + 1
        rows.append({"seed": seed, "pair_score": score, "first": dp})
    return {"tag": tag, "pairs": len(rows), "first_divergence_by_request": by_request, "rows": rows}


def hand_cards(prompt: str) -> list[dict[str, Any]]:
    """Cards of the seat's own hand in a decision prompt: name, signature card (character-only), arcane."""
    import re

    if "手牌（" not in prompt:
        return []
    block = prompt.split("手牌（", 1)[1].split("牌库", 1)[0]
    cards = []
    for line in block.splitlines()[1:]:
        m = re.match(r"\s*\d+\.\s*(.+?)（([^）]*)）", line)
        if m:
            cards.append({"name": m.group(1), "signature": "才能加入牌组" in line, "arcane": "秘传" in m.group(2)})
    return cards


def swapped(text: str) -> list[str]:
    return [x.strip() for x in text.split("替换", 1)[1].split("、") if x.strip()] if "替换" in (text or "") else []


def _mull_add(stat: dict[str, int], cards: list[dict[str, Any]], names: list[str]) -> None:
    core = [c["name"] for c in cards if c["signature"] or c["arcane"]]
    stat["n"] = stat.get("n", 0) + 1
    stat["cards"] = stat.get("cards", 0) + len(names)
    stat["core_hands"] = stat.get("core_hands", 0) + bool(core)
    stat["core_swapped"] = stat.get("core_swapped", 0) + any(n in names for n in core)
    sig = Counter(c["name"] for c in cards if c["signature"])
    gone = Counter(names)
    stat["signature_cards"] = stat.get("signature_cards", 0) + sum(sig.values())
    stat["signature_swapped"] = stat.get("signature_swapped", 0) + sum(min(k, gone[n]) for n, k in sig.items())
    stat["arcane_swapped"] = stat.get("arcane_swapped", 0) + any(c["arcane"] and c["name"] in names for c in cards)


def mulligan(tag: str, probe: str | None = None) -> dict[str, Any]:
    """Opening-mulligan behaviour. From a traced train run: each side's recorded mulligans. With
    ``probe`` (a ``bench.divergence probe`` tag over that run): every probed policy's answer at the
    same mulligans -- the mechanism check for a mulligan advice."""
    hands: dict[tuple[str, int], list[dict[str, Any]]] = {}
    stats: dict[str, dict[str, int]] = {}
    from common.paths import data_dir

    for path in sorted(data_dir("bench", tag, "traces").glob("*/*.json")):
        g = json.loads(path.read_text(encoding="utf-8"))
        if not str(g["cell"].get("group", "")).endswith("train"):
            raise SystemExit("bench.mirror_mine reads train games only")
        seen: set[int] = set()
        for _step, seat, role, t in seat_sequence(g):
            if t["request_type"] != "switch_hands" or seat in seen:
                continue
            seen.add(seat)
            cards = hand_cards(t.get("prompt") or "")
            hands[(path.name, seat)] = cards
            if probe is None:
                _mull_add(stats.setdefault(role, {}), cards, swapped(t["final_text"]))
    if probe is not None:
        for line in data_dir("bench", probe, "positions.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            cards = hands.get((Path(r["path"]).name, int(r["seat"])))
            if r.get("request") == "switch_hands" and cards is not None:
                _mull_add(stats.setdefault(r["policy"], {}), cards, swapped(r.get("text") or ""))
    rates = {p: {"n": s["n"], "core_swap": round(s["core_swapped"] / max(1, s["core_hands"]), 3),
                 "signature_swap": round(s["signature_swapped"] / max(1, s["signature_cards"]), 3),
                 "arcane_swap": round(s["arcane_swapped"] / max(1, s["n"]), 3),
                 "cards_per_hand": round(s["cards"] / max(1, s["n"]), 2)} for p, s in sorted(stats.items())}
    return {"tag": tag, "probe": probe, "counts": stats, "rates": rates}


def render_markdown(report: Mapping[str, Any]) -> str:
    r, a = report["rate_per_100_actions"], report["knowledge_side_association"]
    lines = [f"# 训练对局决策模式：{report['tag']}", "",
             f"生成于 {report['generated']}；{report['games']} 局（重放失败 {report['broken_replays']}）；"
             f"行动决策：知识方 {report['action_decisions'].get('knowledge', 0)}，无知识方 {report['action_decisions'].get('plain', 0)}。", "",
             "| 模式 | 知识方（每 100 次行动） | 无知识方 | 知识方出现该模式的局 | 这些局知识方得分 | 其余局 |",
             "|---|---|---|---|---|---|"]
    for p in PATTERNS:
        lines.append(f"| `{p}` | {r['knowledge'][p]} | {r['plain'][p]} | {a[p]['games_with']} | {a[p]['score_with']} | {a[p]['score_without']} |")
    lines += ["", "模式只是候选：是否真是失误要看局面。得分对照只是相关，不是因果。", ""]
    for p, rows in report["examples"].items():
        lines += [f"## `{p}` 示例", ""]
        for row in rows:
            lines.append(f"- [{row['side']}] {row['game']} 座位 {row['seat']} #{row['ordinal']}：{row['choice']} —— {row['reason']}"
                         + (f"（知识：{', '.join(k for k in row['knowledge'] if k)}）" if row["knowledge"] else ""))
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", required=True, help="traced mirror_train run (or a probe tag with --behaviour)")
    parser.add_argument("--behaviour", action="store_true",
                        help="patterns of each probed policy's answers at the same positions (bench.divergence probe)")
    parser.add_argument("--natural", action="store_true",
                        help="first decision where the two games of each pair differ (D36)")
    parser.add_argument("--mulligan", action="store_true",
                        help="opening-mulligan behaviour per side, or per probed policy with --probe (D36)")
    parser.add_argument("--probe", help="with --mulligan: a bench.divergence probe tag over --tag")
    parser.add_argument("--out", required=True)
    parser.add_argument("--examples", type=int, default=4)
    args = parser.parse_args(argv)
    out = ensure_dir(reports_dir("bench"))
    if args.natural or args.mulligan:
        report = natural_divergence(args.tag) if args.natural else mulligan(args.tag, args.probe)
        report["generated"] = _dt.datetime.now().isoformat(timespec="seconds")
        if args.natural:
            lines = [f"# 镜像对的自然分歧点：{args.tag}", "", f"生成于 {report['generated']}；{report['pairs']} 对。", "",
                     "第一次分歧的决策类型：" + "，".join(f"{k} {v}" for k, v in sorted(report["first_divergence_by_request"].items())), "",
                     "| 种子 | 对分（知识方） | 决策 | 座位 | 一方选择 | 另一方选择 |", "|---|---|---|---|---|---|"]
            for r in report["rows"]:
                d = r["first"] or {}
                a, b = d.get("a", {}), d.get("b", {})
                lines.append(f"| {r['seed']} | {r['pair_score']} | {d.get('request', '—')} | {d.get('seat', '—')} | "
                             f"[{a.get('role', '')}] {a.get('choice', '')} | [{b.get('role', '')}] {b.get('choice', '')} |")
        else:
            lines = [f"# 起手换牌：{args.tag}" + (f"（探针 {args.probe}）" if args.probe else ""), "",
                     f"生成于 {report['generated']}。核心牌 = 专属牌（“牌组中包含某角色，才能加入牌组”）或秘传。", "",
                     "| 一方 / 策略 | 换牌决策 | 换掉 ≥1 张核心牌（手里有核心牌时） | 专属牌被换比例 | 换掉秘传 | 平均换牌张数 |",
                     "|---|---|---|---|---|---|"]
            for p, r in report["rates"].items():
                lines.append(f"| `{p}` | {r['n']} | {r['core_swap']} | {r['signature_swap']} | {r['arcane_swap']} | {r['cards_per_hand']} |")
        lines.append("")
        text = "\n".join(lines)
        (out / f"{args.out}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (out / f"{args.out}.md").write_text(text, encoding="utf-8")
        print(text)
        return 0
    if args.behaviour:
        report = behaviour(args.tag)
        lines = [f"# 同一局面、不同策略的决策模式：{args.tag}", "", f"生成于 {report['generated']}。", "",
                 "| 策略 | 行动类回答 | " + " | ".join(f"`{p}`" for p in PATTERNS) + " |",
                 "|---|---|" + "---|" * len(PATTERNS)]
        for pol, rates in report["rate_per_100_actions"].items():
            lines.append(f"| `{pol}` | {report['action_answers'][pol]} | " + " | ".join(str(rates[p]) for p in PATTERNS) + " |")
        lines += ["", "每 100 次行动类回答中命中该模式的次数；局面相同，只有策略不同。", "",
                  "选择的行动类别（占行动类回答的比例）：", ""]
        all_kinds = sorted({k for v in report["choice_kinds"].values() for k in v})
        lines += ["| 策略 | " + " | ".join(all_kinds) + " |", "|---|" + "---|" * len(all_kinds)]
        for pol, counts in sorted(report["choice_kinds"].items()):
            total = max(1, report["action_answers"][pol])
            lines.append(f"| `{pol}` | " + " | ".join(f"{counts.get(k, 0) / total:.3f}" for k in all_kinds) + " |")
        lines.append("")
        text = "\n".join(lines)
        (out / f"{args.out}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (out / f"{args.out}.md").write_text(text, encoding="utf-8")
        print(text)
        return 0
    report = mine(args.tag, examples=args.examples)
    (out / f"{args.out}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / f"{args.out}.md").write_text(render_markdown(report), encoding="utf-8")
    print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
