"""Divergence-point evaluation (D35): compare two policies on the positions where they disagree.

Full model-vs-model games measure a whole policy at once and are noisy (D34: 80 pairs
give a 95% CI of about +/-0.06, and two thirds of the pairs are even). Here the unit is a
*divergence point* (DP): a real position from a traced **train** game where two policies
choose differently. Both choices are played from the same position and each branch is
finished by the same continuation policy for both seats, so the only difference
between the branches is that one decision.

    probe    replay traced games, sample positions, ask every compared policy what it
             would choose there (one model call per policy per position) -> dps.jsonl
    rollout  fork each DP once per branch (and per repetition) with a continuation
             (``heuristic`` = free scripted bot; or a model spec) -> rollouts.jsonl
    report   per comparison: disagreement rate, decisive DPs, mean branch difference with
             CI, bot-vs-model continuation agreement, cost per DP

    python -m bench.divergence probe --games d34_ab_v10_train --tag d35_dp --per-seat 8 \
        --policy none="llm:deepseek-flash#reply=reason_first" v10="llm:deepseek-flash#kb=kbt3-trig,reply=reason_first"
    python -m bench.divergence rollout --tag d35_dp --compare v10:none --continuation heuristic
    python -m bench.divergence report --tag d35_dp --compare v10:none s1:v10

The branch difference of a DP is ``score(A's choice) - score(B's choice)`` for the seat that
decides, in [-1, 1]. Only positions of train games are used (the teacher may look at them).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from common.paths import data_dir, ensure_dir, reports_dir

ALLOWED_GROUPS = ("mirror-train",)


# ------------------------------------------------------------------------------- helpers

def _games(tag: str) -> list[Path]:
    root = data_dir("bench", tag, "traces")
    return sorted(p for d in sorted(root.iterdir()) if d.is_dir() for p in sorted(d.glob("*.json")))


def _suite_decks(payload: Mapping[str, Any]) -> dict[str, Any]:
    from bench.suite import SUITE_DIR

    group = str(payload["cell"].get("group", ""))
    if not group.startswith(ALLOWED_GROUPS):
        raise SystemExit(f"divergence evaluation reads train games only (group {group!r})")
    return json.loads((SUITE_DIR / "mirror_train.lock.json").read_text(encoding="utf-8"))["decks"]


def _source(path: Path) -> dict[str, Any]:
    from bench.forks import game_source

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return game_source(payload, _suite_decks(payload))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def sample_ordinals(decisions: Sequence[Mapping[str, Any]], per_seat: int, rng: random.Random) -> list[int]:
    """Up to ``per_seat`` decisions of one seat with a real choice (not forced, >= 2 options),
    spread over the game (one random pick in each of ``per_seat`` equal slices)."""
    eligible = [i for i, d in enumerate(decisions) if d["source"] != "forced" and d["n"] >= 2]
    if len(eligible) <= per_seat:
        return eligible
    out = []
    for k in range(per_seat):
        lo, hi = len(eligible) * k // per_seat, len(eligible) * (k + 1) // per_seat
        out.append(eligible[rng.randrange(lo, hi)])
    return out


# ------------------------------------------------------------------------------- probe

def _past(until: str | None) -> bool:
    """``until`` = local "HH:MM" (e.g. the end of the provider's off-peak window): stop submitting
    work after it. A deadline earlier than now's hour block is taken as tomorrow."""
    if not until:
        return False
    hour, minute = (int(x) for x in until.split(":"))
    now = _dt.datetime.now()
    deadline = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    started = getattr(_past, "_started", None) or now
    _past._started = started                      # type: ignore[attr-defined]
    if deadline < started:
        deadline += _dt.timedelta(days=1)
    return now >= deadline


def _over_budget(run: Path, max_cost: float | None) -> float | None:
    """Spend so far of this tag (probes + rollouts, from the call log); the spend if over ``max_cost``."""
    if max_cost is None:
        return None
    from bench.run import _CallLog

    _calls, cost = _CallLog(run / "calls.jsonl").totals()
    return cost if cost >= max_cost else None


def probe(games_tag: str, tag: str, policies: Mapping[str, str], *, per_seat: int, workers: int,
          max_games: int | None = None, max_cost: float | None = None, until: str | None = None,
          select_units: Sequence[str] = (), select_version: str = "") -> dict[str, Any]:
    """``select_units``: instead of spreading ``per_seat`` picks over the game, take up to
    ``per_seat`` decisions per seat where one of these strategy units' detectors fires
    (detector table of ``select_version``) -- a targeted mechanism check for a candidate."""
    """Ask every policy for its choice at sampled positions of the traced games."""
    from bench.forks import replay
    from envs.policy import build_policy

    run = ensure_dir(data_dir("bench", tag))
    os.environ["GITCG_LLM_CALL_LOG"] = str(run / "calls.jsonl")
    meta_path = run / "meta.json"
    meta = {"games": games_tag, "policies": dict(policies), "per_seat": per_seat,
            **({"select_units": list(select_units), "select_version": select_version} if select_units else {}),
            "created": _dt.datetime.now().isoformat(timespec="seconds")}
    if meta_path.exists():
        old = json.loads(meta_path.read_text(encoding="utf-8"))
        if old.get("games") != games_tag or old.get("per_seat") != per_seat or \
                old.get("select_units", []) != list(select_units):
            raise SystemExit(f"{meta_path}: run was probed with other settings; use a new --tag")
        meta["policies"] = {**old.get("policies", {}), **dict(policies)}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    out_path = run / "positions.jsonl"
    done = {(r["game"], r["seat"], r["ordinal"], r["policy"]) for r in _jsonl(out_path)}
    paths = _games(games_tag)[: max_games or None]
    asked = 0
    for g_index, path in enumerate(paths):
        spent = _over_budget(run, max_cost)
        if spent is not None or _past(until):
            print(f"[divergence] stopping probes: {'budget' if spent is not None else 'time ' + str(until)}", flush=True)
            break
        source = _source(path)
        game_id = f"{source['seed']}|{source['subject_seat']}"
        rng = random.Random(f"{games_tag}:{game_id}")
        targets = {seat: set(sample_ordinals(source["seats"][seat], per_seat, rng)) for seat in (0, 1)}
        captured: dict[tuple[int, int], Any] = {}
        triggered: dict[int, list[tuple[int, Any]]] = {0: [], 1: []}

        def keep(seat: int, ordinal: int, built: Any) -> None:
            if select_units:
                from reps.knowledge import matching_units

                rec = source["seats"][seat][ordinal]
                if rec["source"] != "forced" and rec["n"] >= 2 and \
                        set(matching_units(built.context, version=select_version)) & set(select_units):
                    triggered[seat].append((ordinal, built))
            elif ordinal in targets[seat]:
                captured[(seat, ordinal)] = built

        result = replay(source, on_decision=keep)
        if not result["ok"]:
            print(f"[divergence] {path.name}: replay failed ({result}); skipped", flush=True)
            continue
        for seat, found in triggered.items():
            for ordinal, built in (rng.sample(found, per_seat) if len(found) > per_seat else found):
                captured[(seat, ordinal)] = built
        jobs = [(seat, ordinal, name, spec) for (seat, ordinal) in sorted(captured) for name, spec in policies.items()
                if (game_id, seat, ordinal, name) not in done]

        def ask(job: tuple[int, int, str, str]) -> dict[str, Any]:
            from bench.forks import query

            seat, ordinal, name, spec = job
            policy = build_policy(spec, seed=int(source["seed"]), role=f"p{seat}")
            built = captured[(seat, ordinal)]
            index = query(policy, built)
            trace = policy.traces[-1].as_dict() if getattr(policy, "traces", None) else {}
            rec = source["seats"][seat][ordinal]
            return {"game": game_id, "path": str(path), "seat": seat, "ordinal": ordinal, "policy": name,
                    "spec": spec, "index": index, "n": rec["n"], "request": rec["request"],
                    "actor": rec["role"], "recorded_index": rec["index"], "recorded_text": rec["final_text"],
                    "text": trace.get("final_text"), "reason": trace.get("reason"), "source": trace.get("source"),
                    "knowledge": [i.get("id") for i in (trace.get("knowledge") or {}).get("items", [])]}

        rows = []
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for future in as_completed([pool.submit(ask, job) for job in jobs]):
                rows.append(future.result())
        _append(out_path, rows)
        asked += len(rows)
        print(f"[divergence] {g_index + 1}/{len(paths)} {path.name}: {len(captured)} positions, {len(rows)} answers",
              flush=True)
    return {"asked": asked}


def divergence_points(tag: str, a: str, b: str) -> list[dict[str, Any]]:
    """Positions where policies ``a`` and ``b`` chose different options (model answers only)."""
    by_pos: dict[tuple, dict[str, Any]] = {}
    for row in _jsonl(data_dir("bench", tag, "positions.jsonl")):
        by_pos.setdefault((row["game"], row["seat"], row["ordinal"]), {})[row["policy"]] = row
    out = []
    for key, answers in sorted(by_pos.items()):
        if a not in answers or b not in answers:
            continue
        ra, rb = answers[a], answers[b]
        if ra.get("source") != "llm" or rb.get("source") != "llm":
            continue                                  # a fallback answer is not the policy's choice
        if ra["index"] != rb["index"]:
            dp_id = hashlib.sha256(f"{a}:{b}:{key}".encode()).hexdigest()[:12]
            out.append({"dp": dp_id, "a": a, "b": b, "game": key[0], "seat": key[1], "ordinal": key[2],
                        "path": ra["path"], "request": ra["request"], "actor": ra["actor"],
                        "index_a": ra["index"], "index_b": rb["index"], "text_a": ra["text"], "text_b": rb["text"],
                        "knowledge_a": ra.get("knowledge"), "knowledge_b": rb.get("knowledge")})
    return out


# ------------------------------------------------------------------------------- rollout

def _rollout_job(job: Mapping[str, Any]) -> dict[str, Any]:
    """One branch of one DP, in a worker process (engine runtimes are per process)."""
    import os as _os

    if job.get("call_log"):
        _os.environ["GITCG_LLM_CALL_LOG"] = job["call_log"]
    from bench.forks import fork
    from envs.policy import build_policy

    source = _source(Path(job["path"]))
    seed = int(source["seed"]) + 7919 * int(job["rep"])
    continuation = [build_policy(job["continuation"], seed=seed, role=f"p{s}") for s in (0, 1)]
    out = fork(source, int(job["seat"]), int(job["ordinal"]), int(job["choice"]), continuation)
    usage = 0.0
    for policy in continuation:
        summary = policy.summary() if callable(getattr(policy, "summary", None)) else {}
        usage += float(((summary or {}).get("usage") or {}).get("cost") or 0.0)
    return {**{k: job[k] for k in ("dp", "branch", "rep", "continuation")}, **out, "cost": round(usage, 6)}


def rollout(tag: str, compare: Sequence[str], continuation: str, *, reps: int, workers: int,
            max_dps: int | None, sample_seed: str = "d35", max_cost: float | None = None,
            first_reps_only: int | None = None, until: str | None = None) -> dict[str, Any]:
    """``first_reps_only``: repetitions beyond the first only for the first N sampled DPs
    of each comparison (to measure repeat noise without paying for it everywhere)."""
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing as mp

    run = data_dir("bench", tag)
    out_path = run / "rollouts.jsonl"
    done = {(r["dp"], r["branch"], r["rep"], r["continuation"]) for r in _jsonl(out_path) if r.get("score") is not None}
    jobs = []
    for pair in compare:
        a, b = pair.split(":")
        dps = divergence_points(tag, a, b)
        if max_dps is not None and len(dps) > max_dps:
            dps = sorted(random.Random(f"{sample_seed}:{pair}").sample(dps, max_dps), key=lambda d: d["dp"])
        for k, dp in enumerate(dps):
            for branch, choice in (("a", dp["index_a"]), ("b", dp["index_b"])):
                for rep in range(reps if first_reps_only is None or k < first_reps_only else 1):
                    if (dp["dp"], branch, rep, continuation) in done:
                        continue
                    jobs.append({"dp": dp["dp"], "branch": branch, "rep": rep, "continuation": continuation,
                                 "path": dp["path"], "seat": dp["seat"], "ordinal": dp["ordinal"], "choice": choice,
                                 "call_log": str(run / "calls.jsonl")})
    print(f"[divergence] {len(jobs)} branch rollouts with {continuation!r}, workers={workers}", flush=True)
    finished, stopped = 0, None
    queue = list(jobs)
    with ProcessPoolExecutor(max_workers=max(1, workers), mp_context=mp.get_context("spawn")) as pool:
        running = set()
        while queue or running:
            while queue and len(running) < max(1, workers) and stopped is None:
                spent = _over_budget(run, max_cost)      # live: includes branches still being played
                if spent is not None or _past(until):
                    stopped = f"budget reached ({spent:.4f} >= {max_cost})" if spent is not None else f"time {until}"
                    print(f"[divergence] {stopped}; no new rollouts", flush=True)
                    break
                running.add(pool.submit(_rollout_job, queue.pop(0)))
            if not running:
                break
            done_now = next(as_completed(running))
            running.discard(done_now)
            _append(out_path, [done_now.result()])
            finished += 1
            if finished % 20 == 0 or (not queue and not running):
                print(f"[divergence] {finished}/{len(jobs)} rollouts", flush=True)
    return {"rollouts": finished, "stopped": stopped}


# ------------------------------------------------------------------------------- report

def _mean_ci(values: Sequence[float]) -> dict[str, Any]:
    n = len(values)
    if n == 0:
        return {"n": 0}
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n else 0.0
    return {"n": n, "mean": round(mean, 4), "sd": round(sd, 4), "se": round(se, 4),
            "ci95": [round(mean - 1.96 * se, 4), round(mean + 1.96 * se, 4)]}


def summarise(tag: str, compare: Sequence[str]) -> dict[str, Any]:
    run = data_dir("bench", tag)
    positions = _jsonl(run / "positions.jsonl")
    rollouts = _jsonl(run / "rollouts.jsonl")
    calls = _jsonl(run / "calls.jsonl")
    by_branch: dict[tuple, list[float]] = {}
    cost_by_cont: dict[str, list[float]] = {}
    for r in rollouts:
        if r.get("score") is None:
            continue
        by_branch.setdefault((r["dp"], r["continuation"], r["branch"]), []).append(float(r["score"]))
        cost_by_cont.setdefault(r["continuation"], []).append(float(r.get("cost") or 0.0))
    continuations = sorted({r["continuation"] for r in rollouts})
    # The call log holds probe *and* model-continuation calls; rollout rows carry their own cost.
    total_cost = sum(float(c.get("cost") or 0) for c in calls)
    rollout_cost = sum(float(r.get("cost") or 0) for r in rollouts)
    out = {"generated": _dt.datetime.now().isoformat(timespec="seconds"), "tag": tag,
           "probe_calls": sum(1 for r in positions if str(r.get("spec", "")).startswith("llm")),
           "probe_cost": round(max(0.0, total_cost - rollout_cost), 4),
           "model_calls_total": len(calls), "cost_total": round(total_cost, 4), "rollout_cost": round(rollout_cost, 4),
           "continuation_cost_per_branch": {c: round(sum(v) / len(v), 5) for c, v in cost_by_cont.items() if v},
           "comparisons": []}
    by_pos: dict[tuple, dict[str, Any]] = {}
    for row in positions:
        by_pos.setdefault((row["game"], row["seat"], row["ordinal"]), {})[row["policy"]] = row
    for pair in compare:
        a, b = pair.split(":")
        both = [v for v in by_pos.values() if a in v and b in v and v[a].get("source") == "llm" and v[b].get("source") == "llm"]
        dps = {d["dp"]: d for d in divergence_points(tag, a, b)}
        per_req: dict[str, list[int]] = {}
        for v in both:
            per_req.setdefault(v[a]["request"], [0, 0])
            per_req[v[a]["request"]][0] += 1
            per_req[v[a]["request"]][1] += int(v[a]["index"] != v[b]["index"])
        entry: dict[str, Any] = {"pair": pair, "positions": len(both), "dps": len(dps),
                                 "disagreement": round(len(dps) / len(both), 3) if both else None,
                                 "by_request": {k: {"positions": n, "dps": d} for k, (n, d) in sorted(per_req.items())},
                                 "by_continuation": {}}
        deltas_by_cont: dict[str, dict[str, float]] = {}
        for cont in continuations:
            deltas, decisive, noise = [], 0, []
            by_req: dict[str, list[float]] = {}
            by_item: dict[str, list[float]] = {}
            for dp_id, dp in dps.items():
                sa, sb = by_branch.get((dp_id, cont, "a")), by_branch.get((dp_id, cont, "b"))
                if not sa or not sb:
                    continue
                delta = sum(sa) / len(sa) - sum(sb) / len(sb)
                deltas.append(delta)
                deltas_by_cont.setdefault(cont, {})[dp_id] = delta
                decisive += int(delta != 0)
                by_req.setdefault(dp["request"], []).append(delta)
                # which knowledge the policies were shown at this DP: counterfactual evidence per item
                for item in set(dp.get("knowledge_a") or []) ^ set(dp.get("knowledge_b") or []) or set(dp.get("knowledge_a") or []):
                    by_item.setdefault(str(item), []).append(delta)
                for scores in (sa, sb):
                    if len(scores) >= 2:
                        noise.append(float(scores[0] != scores[1]))
            entry["by_continuation"][cont] = {
                **_mean_ci(deltas), "decisive": decisive,
                "decisive_rate": round(decisive / len(deltas), 3) if deltas else None,
                "repeat_branch_differs": round(sum(noise) / len(noise), 3) if noise else None,
                "repeat_branches": len(noise),
                "by_request": {k: _mean_ci(v) for k, v in sorted(by_req.items())},
                "by_knowledge": {k: _mean_ci(v) for k, v in sorted(by_item.items()) if len(v) >= 3}}
        if len(deltas_by_cont) >= 2:
            names = sorted(deltas_by_cont)
            x, y = deltas_by_cont[names[0]], deltas_by_cont[names[1]]
            common = sorted(set(x) & set(y))
            both_decisive = [k for k in common if x[k] != 0 and y[k] != 0]
            entry["agreement"] = {"continuations": names, "common": len(common),
                                  "both_decisive": len(both_decisive),
                                  "same_sign": sum(1 for k in both_decisive if (x[k] > 0) == (y[k] > 0)),
                                  "either_decisive": sum(1 for k in common if x[k] != 0 or y[k] != 0)}
        out["comparisons"].append(entry)
    return out


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [f"# 分歧点评测：{report['tag']}", "",
             f"生成于 {report['generated']}。探测 {report['probe_calls']} 次（估算 {report['probe_cost']} 美元）；"
             f"模型调用合计 {report.get('model_calls_total')} 次、估算 {report.get('cost_total')} 美元（其中续打 {report.get('rollout_cost')}）；"
             f"每个分支续打的估算费用（美元）：{json.dumps(report['continuation_cost_per_branch'], ensure_ascii=False)}。", "",
             "分支差 = A 的选择续打得分 − B 的选择续打得分（做决定的一方，胜 1 平 0.5 负 0）；两个分支由同一续打策略替双方打完。", ""]
    for c in report["comparisons"]:
        lines += [f"## {c['pair']}（A:B）", "",
                  f"共同局面 {c['positions']}，分歧点 {c['dps']}（分歧率 {c['disagreement']}）。", "",
                  "| 决策类型 | 局面 | 分歧点 |", "|---|---|---|"]
        lines += [f"| {k} | {v['positions']} | {v['dps']} |" for k, v in c["by_request"].items()]
        lines += ["", "| 续打 | 有结果的分歧点 | 决定性（两支结果不同） | 平均分支差 [95% CI] | 分支差标准差 | 同一分支重打结果不同 |",
                  "|---|---|---|---|---|---|"]
        for cont, s in c["by_continuation"].items():
            if not s.get("n"):
                continue
            lines.append(f"| `{cont}` | {s['n']} | {s['decisive']}（{s['decisive_rate']}） | {s['mean']:+.3f} "
                         f"[{s['ci95'][0]:+.3f}, {s['ci95'][1]:+.3f}] | {s['sd']} | "
                         f"{s['repeat_branch_differs']}（{s['repeat_branches']} 个分支） |")
        for cont, s in c["by_continuation"].items():
            items = sorted(((k, v) for k, v in (s.get("by_knowledge") or {}).items()), key=lambda kv: kv[1]["mean"])
            if items:
                lines += ["", f"按注入的知识条目（`{cont}` 续打；只列 ≥ 3 个分歧点的条目；A、B 只有一方看到的条目，若都看到则按 A 的）：", "",
                          "| 条目 | 分歧点 | 平均分支差 [95% CI] |", "|---|---|---|"]
                lines += [f"| {k} | {v['n']} | {v['mean']:+.3f} [{v['ci95'][0]:+.3f}, {v['ci95'][1]:+.3f}] |" for k, v in items]
        if "agreement" in c:
            g = c["agreement"]
            lines += ["", f"续打一致性（{' 对 '.join(g['continuations'])}）：共同 {g['common']}，至少一方决定性 {g['either_decisive']}，"
                      f"双方都决定性 {g['both_decisive']}，其中同号 {g['same_sign']}。"]
        lines.append("")
    lines += ["口径：局面取自 train 对局（教师可看）；分歧点只计两个策略都由模型作答（非回退）的局面。模拟器内结果，不进强度验收。", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("probe")
    p.add_argument("--games", required=True, help="tag of a traced mirror_train run")
    p.add_argument("--tag", required=True)
    p.add_argument("--policy", nargs="+", required=True, help="name=spec ...")
    p.add_argument("--per-seat", type=int, default=8)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--max-games", type=int, default=None)
    p.add_argument("--max-cost", type=float, default=None, help="USD (estimate), whole tag")
    p.add_argument("--until", default=None, help="local HH:MM: no new game probed after it (rerun resumes)")
    p.add_argument("--select-units", nargs="*", default=[], help="only positions where these units' detectors fire")
    p.add_argument("--select-version", default="", help="KB version string of the detector table, e.g. 1.0-s1")
    r = sub.add_parser("rollout")
    r.add_argument("--tag", required=True)
    r.add_argument("--compare", nargs="+", required=True, help="a:b ...")
    r.add_argument("--continuation", required=True, help="policy spec for both seats after the fork")
    r.add_argument("--reps", type=int, default=1)
    r.add_argument("--workers", type=int, default=2)
    r.add_argument("--max-dps", type=int, default=None, help="per comparison, sampled with a fixed seed")
    r.add_argument("--first-reps-only", type=int, default=None,
                   help="repetitions beyond the first only for the first N sampled DPs per comparison")
    r.add_argument("--max-cost", type=float, default=None, help="USD (estimate), whole tag: no new rollout beyond it")
    r.add_argument("--until", default=None, help="local HH:MM: no new rollout after it (rerun resumes)")
    s = sub.add_parser("report")
    s.add_argument("--tag", required=True)
    s.add_argument("--compare", nargs="+", required=True)
    s.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    if args.command == "probe":
        policies = dict(item.split("=", 1) for item in args.policy)
        print(json.dumps(probe(args.games, args.tag, policies, per_seat=args.per_seat, workers=args.workers,
                               max_games=args.max_games, max_cost=args.max_cost, until=args.until,
                               select_units=args.select_units, select_version=args.select_version)))
    elif args.command == "rollout":
        print(json.dumps(rollout(args.tag, args.compare, args.continuation, reps=args.reps, workers=args.workers,
                                 max_dps=args.max_dps, max_cost=args.max_cost, first_reps_only=args.first_reps_only,
                                 until=args.until)))
    else:
        report = summarise(args.tag, args.compare)
        out = ensure_dir(reports_dir("bench"))
        name = args.out or args.tag
        (out / f"{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (out / f"{name}.md").write_text(render_markdown(report), encoding="utf-8")
        print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
