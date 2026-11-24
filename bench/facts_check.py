"""Replay traced train games to check derived facts and mine what they would change (D37).

For every traced game (``bench.run --trace``, train only) the game is replayed exactly
(``bench.forks``). On the way:

* **preview accuracy** -- whenever a seat chose a skill, the kept preview (``reps.facts``)
  is compared with the damage that actually happened before the next decision of either
  seat: same (target, value, reaction, defeated) multiset or not;
* **teacher counts** per side (knowledge / plain): action decisions where some skill
  option defeats the opponent's active character and whether the chosen option did;
  skills chosen below the highest previewed damage; skills used while the opponent's
  active character had full energy;
* **outcome** -- the public end state of the replayed game, so the D37 outcome metrics
  can be computed on real model games (``bench.metrics``).

    python -m bench.facts_check --tag d36_train_v10 d34_ab_v10_train --out d37_facts_train
    python -m bench.facts_check --probe <probe tag> --out NAME     # mechanism check of a candidate
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any, Mapping

from common.paths import data_dir, ensure_dir, reports_dir


def _games(tag: str) -> list[dict[str, Any]]:
    games = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(data_dir("bench", tag, "traces").glob("*/*.json"))]
    for g in games:
        if not str(g["cell"].get("group", "")).endswith("train"):
            raise SystemExit("bench.facts_check reads train games only")
    return games


class _DamageLog:
    """Public damage mutations seen by seat 0, in order (the engine sends them to both seats)."""

    def __init__(self) -> None:
        self.rows: list[tuple[int, int, int, int]] = []


def replay_game(game: Mapping[str, Any], decks: Mapping[str, Any]) -> dict[str, Any]:
    from bench import forks
    from envs import match
    from reps.facts import option_effects, summarize
    from reps.schema import OptionKind

    source = forks.game_source(game, decks)
    side = int(game["cell"]["side"])
    roles = {side: "knowledge", 1 - side: "plain"}
    log = _DamageLog()
    decisions: list[dict[str, Any]] = []
    original = match.PolicyPlayer.on_notify

    def on_notify(self: Any, notification: Any) -> None:
        original(self, notification)
        if self.who != 0:
            return
        for mutation in getattr(notification, "mutation", ()):
            if mutation.WhichOneof("mutation") == "damage":
                d = mutation.damage
                if int(d.damage_type) != 9:
                    log.rows.append((int(d.target_id), int(d.value), int(d.reaction_type), int(bool(d.cause_defeated))))

    def on_decision(seat: int, cursor: int, built: Any) -> None:
        context = built.context
        recorded = source["seats"][seat][cursor]
        entry: dict[str, Any] = {"seat": seat, "ordinal": cursor, "role": roles[seat], "at": len(log.rows),
                                 "request": context.request_type.value}
        if context.request_type.value == "action":
            specs = context.legal_low_level_specs
            chosen = int(recorded["index"])
            effects = [option_effects(context, s) for s in specs]
            dealt = [sum(e["value"] for e in eff if e["kind"] == "damage" and e["side"] == "对方") for eff in effects]
            ko = [i for i, eff in enumerate(effects)
                  if any(e["kind"] == "damage" and e["side"] == "对方" and e["active"] and e["defeated"] for e in eff)]
            view = context.player_view
            opp_full = any(c.is_active and not c.defeated and int(c.max_energy) > 0 and int(c.energy) >= int(c.max_energy)
                           for c in view.players[1 - seat].characters)
            entry.update({
                "chosen": chosen, "chosen_kind": specs[chosen].kind.value,
                "chosen_skill": specs[chosen].kind == OptionKind.ACTION_USE_SKILL,
                "predicted": summarize(effects[chosen]) if effects[chosen] else None,
                "ko_options": ko, "max_dealt": max(dealt) if dealt else 0, "chosen_dealt": dealt[chosen],
                "skill_options": sum(1 for s in specs if s.kind == OptionKind.ACTION_USE_SKILL),
                "opp_full_energy": opp_full, "llm": recorded.get("source") == "llm",
            })
        decisions.append(entry)

    match.PolicyPlayer.on_notify = on_notify
    try:
        shared = forks._Shared()
        seats = [forks._Seat(s, source["seats"][s], shared, on_decision=on_decision) for s in (0, 1)]
        record = forks._run(source, seats)
    finally:
        match.PolicyPlayer.on_notify = original
    mismatch = seats[0].mismatch or seats[1].mismatch
    # actual damage of each decision = damage logged until the next decision of either seat
    for i, d in enumerate(decisions):
        if d.get("predicted") is not None:
            end = decisions[i + 1]["at"] if i + 1 < len(decisions) else len(log.rows)
            d["actual"] = sorted(log.rows[d["at"]:end])
    return {"cell": game["cell"], "subject": game.get("subject"), "side": side, "winner": record.winner,
            "recorded_winner": game.get("winner"), "rounds": record.rounds, "outcome": record.outcome,
            "mismatch": mismatch, "decisions": decisions}


def summarise(replays: list[dict[str, Any]]) -> dict[str, Any]:
    acc = Counter()
    mism_examples: list[dict[str, Any]] = []
    by_role: dict[str, Counter] = {"knowledge": Counter(), "plain": Counter()}
    for r in replays:
        for d in r["decisions"]:
            if d.get("predicted") is not None:
                predicted = [tuple(x) for x in d["predicted"]]
                actual = Counter(tuple(x) for x in d["actual"])
                same = sorted(predicted) == sorted(actual.elements())
                contained = not (Counter(predicted) - actual)
                acc["checked"] += 1
                acc["same"] += same
                acc["contained"] += contained
                if not contained and len(mism_examples) < 12:
                    mism_examples.append({"predicted": d["predicted"], "actual": d["actual"]})
            if d["request"] != "action" or not d.get("llm"):
                continue
            c = by_role[d["role"]]
            c["actions"] += 1
            if d["ko_options"]:
                c["ko_available"] += 1
                c["ko_taken"] += d["chosen"] in d["ko_options"]
                c["ko_skill_used_other"] += d["chosen_skill"] and d["chosen"] not in d["ko_options"]
            if d["chosen_skill"]:
                c["skills"] += 1
                c["skill_below_max"] += d["chosen_dealt"] < d["max_dealt"]
            if d["opp_full_energy"]:
                c["opp_full_energy"] += 1
                c["opp_full_energy_skill"] += d["chosen_skill"]
    return {"replayed": len(replays), "faithful": sum(1 for r in replays if not r["mismatch"]
                                                      and r["winner"] == r["recorded_winner"]),
            "preview_checked": acc["checked"], "preview_same": acc["same"],
            "preview_accuracy": round(acc["same"] / acc["checked"], 4) if acc["checked"] else None,
            "preview_contained": acc["contained"],
            "preview_contained_rate": round(acc["contained"] / acc["checked"], 4) if acc["checked"] else None,
            "mismatch_examples": mism_examples,
            "teacher": {role: dict(c) for role, c in by_role.items()}}


def render(report: Mapping[str, Any], tags: list[str]) -> str:
    t = report["teacher"]
    lines = [f"# 派生事实核对与教师计数：{', '.join(tags)}", "",
             f"重放 {report['replayed']} 局，忠实（无不符、胜者相同）{report['faithful']} 局。只读 train 对局。", "",
             "## 技能预演的准确率", "",
             f"选了技能的决策 {report['preview_checked']} 个，预演与实际伤害（目标、数值、反应、击倒）完全一致 "
             f"{report['preview_same']} 个，一致率 **{report['preview_accuracy']}**。", "",
             f"预演中的每一项伤害都实际发生（实际中可以另有其他来源的后续伤害，例如对方行动前触发、召唤物、回合结束）"
             f"{report['preview_contained']} 个，比例 **{report['preview_contained_rate']}**。", "",
             "## 教师计数（模型作答的行动决策）", "",
             "| 一方 | 行动决策 | 有击倒选项 | 选了击倒选项 | 用了别的技能 | 用技能 | 技能伤害低于最高 | 对方可放爆发时 | 其中用技能 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for role in ("knowledge", "plain"):
        c = t.get(role, {})
        lines.append(f"| {role} | {c.get('actions', 0)} | {c.get('ko_available', 0)} | {c.get('ko_taken', 0)} "
                     f"| {c.get('ko_skill_used_other', 0)} | {c.get('skills', 0)} | {c.get('skill_below_max', 0)} "
                     f"| {c.get('opp_full_energy', 0)} | {c.get('opp_full_energy_skill', 0)} |")
    if report["mismatch_examples"]:
        lines += ["", "## 预演中有项目没有发生的例子（目标 id, 数值, 反应, 击倒）", ""]
        lines += [f"- 预演 {m['predicted']} / 实际 {m['actual']}" for m in report["mismatch_examples"]]
    lines += ["", "口径：预演取自引擎在行动请求中附带的预览，只保留技能对角色的伤害、治疗与附着（`reps.facts`）。"
              "实际 = 该决策之后、任一方下一个决策之前的公开伤害事件。", ""]
    return "\n".join(lines)


def probe_summary(tag: str) -> dict[str, Any]:
    """Per policy, on ``bench.divergence probe --select-facts`` positions: how often it takes a
    knock-out when one exists, and picks a highest-damage skill when it uses a skill."""
    rows = [json.loads(line) for line in data_dir("bench", tag, "positions.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    out: dict[str, Counter] = {}
    for r in rows:
        f = r.get("facts")
        if not f or r.get("source") not in ("llm", None):
            continue
        c = out.setdefault(r["policy"], Counter())
        c["positions"] += 1
        if f["ko"]:
            c["ko_positions"] += 1
            c["ko_taken"] += r["index"] in f["ko"]
        dealt = {int(k): v for k, v in f["dealt"].items()}
        if r["index"] in dealt and len(set(dealt.values())) >= 2:
            c["skill_choices"] += 1
            c["best_skill"] += r["index"] in f["best"]
        c["skill"] += r["index"] in dealt
    table = {}
    for name, c in out.items():
        table[name] = {**c, "ko_rate": round(c["ko_taken"] / c["ko_positions"], 4) if c["ko_positions"] else None,
                       "best_rate": round(c["best_skill"] / c["skill_choices"], 4) if c["skill_choices"] else None,
                       "skill_rate": round(c["skill"] / c["positions"], 4) if c["positions"] else None}
    return {"tag": tag, "policies": table}


def render_probe(report: Mapping[str, Any]) -> str:
    lines = [f"# 派生事实的机制核对：{report['tag']}", "",
             "| 策略 | 局面 | 有击倒选项的局面 | 选了击倒 | 击倒率 | 用技能且伤害有高低 | 选了最高伤害 | 最高伤害率 | 用技能比例 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, c in sorted(report["policies"].items()):
        lines.append(f"| {name} | {c.get('positions', 0)} | {c.get('ko_positions', 0)} | {c.get('ko_taken', 0)} "
                     f"| {c['ko_rate']} | {c.get('skill_choices', 0)} | {c.get('best_skill', 0)} | {c['best_rate']} "
                     f"| {c['skill_rate']} |")
    lines += ["", "口径：train 重放局面（`bench.divergence probe --select-facts`），每局面每策略问 1 次；"
              "击倒 / 伤害按引擎预演判定；只计模型实际作答的回答。", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from bench.divergence import _suite_decks

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", nargs="+", default=None)
    parser.add_argument("--probe", default=None, help="summarise a --select-facts probe tag instead")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.probe:
        report = probe_summary(args.probe)
        out = ensure_dir(reports_dir("bench"))
        (out / f"{args.out}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (out / f"{args.out}.md").write_text(render_probe(report), encoding="utf-8")
        print(render_probe(report))
        return 0
    if not args.tag:
        parser.error("--tag or --probe is required")
    replays = []
    for tag in args.tag:
        for game in _games(tag):
            replays.append(replay_game(game, _suite_decks(game)))
    report = summarise(replays)
    out = ensure_dir(reports_dir("bench"))
    (out / f"{args.out}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / f"{args.out}.md").write_text(render(report, args.tag), encoding="utf-8")
    raw = ensure_dir(data_dir("bench", args.out))
    with (raw / "replays.jsonl").open("w", encoding="utf-8") as handle:
        for r in replays:
            handle.write(json.dumps({k: v for k, v in r.items() if k != "decisions"}, ensure_ascii=False) + "\n")
    print(render(report, args.tag))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
