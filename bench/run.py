"""Run a benchmark suite for one or more subjects (resumable, budgeted, parallel).

    python -m bench.run --suite lite --subjects heuristic legal_random "expert:<deck>" --workers 2
    python -m bench.run --suite lite --subjects "llm:glm-53-plan" "llm:glm-53-plan#kb=rules-strategy" \\
        --workers 4 --max-calls 8000 --tag glm53
    python -m bench.run --suite lite --tag glm53 --report-only

Rows are appended game by game to ``<data>/bench/<tag>/games.jsonl``; re-running the
same command plays only the missing (subject, cell) pairs. A ``meta.json`` pins the
suite fingerprint: resuming against a changed suite is refused. The aggregate goes
to ``reports/bench/<tag>.json`` (+ ``.md``).

Model subjects: calls cost money or quota. ``--max-calls`` / ``--max-cost`` stop the
run when the total over all rows reaches the cap; a fatal API error (bad key, no
balance, unknown model) stops the subject at once instead of letting its fallback
policy play the rest. Games where the model answered < 90% of its decisions are
kept but flagged ``degraded`` and excluded from that subject's rates.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

from common.paths import REPO_ROOT, data_dir, ensure_dir, reports_dir


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--suite", required=True, help="suite name in configs/bench/ or a TOML path")
    p.add_argument("--subjects", nargs="*", default=[], help="policy specs; '<deck>' expands to the cell's deck")
    p.add_argument("--tag", default=None, help="run directory / report name (default: the suite name)")
    p.add_argument("--workers", type=int, default=2, help="games in parallel (one process each)")
    p.add_argument("--groups", nargs="*", default=None, help="only these groups")
    p.add_argument("--replicates", type=int, default=None,
                   help="only the first N seed replicates of every matchup (a balanced subset)")
    p.add_argument("--max-cells", type=int, default=None, help="only the first N cells of the suite (smoke)")
    p.add_argument("--max-calls", type=int, default=None)
    p.add_argument("--max-cost", type=float, default=None)
    p.add_argument("--game-timeout", type=float, default=3600.0, help="seconds before a game process is killed")
    p.add_argument("--reference", default=None, help="subject the paired differences are taken against")
    p.add_argument("--rival", default=None,
                   help="model-vs-model suites (bench.mirror): the policy spec that replaces '<rival>' in cells")
    p.add_argument("--trace", action="store_true",
                   help="keep every decision (prompt, reply, knowledge) of both sides under <run>/traces/ (D34 train games)")
    p.add_argument("--report-only", action="store_true")
    return p


def _spawn(task: dict[str, Any], timeout: float, call_log: Path) -> dict[str, Any]:
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(REPO_ROOT))
    env["GITCG_LLM_CALL_LOG"] = str(call_log)
    try:
        proc = subprocess.run([sys.executable, "-m", "bench.play"], input=json.dumps(task), text=True,
                              capture_output=True, cwd=REPO_ROOT, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"subject": task["subject"], "cell": task["key"], **task["cell"], "score": None,
                "error": f"game process exceeded {timeout:.0f}s", "truncated": True}
    marker = proc.stdout.rfind("@@ROW@@")
    if proc.returncode != 0 or marker < 0:
        return {"subject": task["subject"], "cell": task["key"], **task["cell"], "score": None,
                "error": f"game process failed ({proc.returncode}): {proc.stderr[-300:]}", "truncated": False}
    return json.loads(proc.stdout[marker + len("@@ROW@@"):].strip().splitlines()[0])


def _totals(rows: list[dict[str, Any]]) -> tuple[int, float]:
    calls = cost = 0
    for row in rows:
        for side in ("llm", "rival_llm"):         # a model-vs-model game spends on both sides
            usage = (row.get(side) or {}).get("usage") or {}
            calls += int(usage.get("calls", 0)) + int(usage.get("errors", 0))
            cost += float(usage.get("cost") or 0.0)
    return calls, float(cost)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from bench.report import build_report, display_path, render_markdown
    from bench.suite import load_suite, subject_applies
    from common.lock import load_engine_lock, runtime_metadata

    suite = load_suite(args.suite)
    tag = args.tag or suite.name
    run_dir = ensure_dir(data_dir() / "bench" / tag)
    games_path, meta_path = run_dir / "games.jsonl", run_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else None
    if meta is not None and meta.get("fingerprint") != suite.fingerprint:
        raise SystemExit(f"[bench] {meta_path} was written for suite fingerprint {meta.get('fingerprint')}, "
                         f"the suite is now {suite.fingerprint}: use a new --tag")
    rows: list[dict[str, Any]] = []
    if games_path.exists():
        with games_path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    break
    subjects = list(dict.fromkeys(list((meta or {}).get("subjects", [])) + list(args.subjects)))
    needs_rival = any("<rival>" in cell.opponent_policy for cell in suite.cells)
    rival = args.rival or (meta or {}).get("rival")
    if needs_rival and not rival:
        raise SystemExit("[bench] this suite plays model against model: pass --rival SPEC")
    if meta is not None and meta.get("rival") and args.rival and args.rival != meta["rival"]:
        raise SystemExit(f"[bench] {meta_path} was played against rival {meta['rival']!r}: use a new --tag")
    meta_path.write_text(json.dumps({"suite": suite.as_dict(), "fingerprint": suite.fingerprint,
                                     "subjects": subjects, **({"rival": rival} if needs_rival else {}),
                                     "engine_lock": load_engine_lock(),
                                     "runtime": runtime_metadata()}, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    cells = [c for c in suite.cells if (args.groups is None or c.group in args.groups)
             and (args.replicates is None or c.rep < args.replicates)]
    if args.max_cells is not None:
        cells = cells[: args.max_cells]
    stopped: str | None = None
    if not args.report_only:
        # A row with an infrastructure error (process died / timed out) is retried on resume.
        done = {(r["subject"], r["cell"]) for r in rows if not str(r.get("error") or "").startswith("game process")}
        todo = [(s, c) for c in cells for s in args.subjects
                if subject_applies(s, c) and (s, c.key) not in done]
        lock = threading.Lock()
        dead: dict[str, str] = {}                  # subject -> fatal reason
        print(f"[bench] suite {suite.name} ({suite.fingerprint}): {len(cells)} cells, "
              f"{len(args.subjects)} subject(s), {len(todo)} game(s) to play, workers={args.workers}", flush=True)

        def submit_next(pool: ThreadPoolExecutor, queue: list, running: dict) -> None:
            nonlocal stopped
            while queue and len(running) < max(1, args.workers) and stopped is None:
                subject, cell = queue.pop(0)
                if subject in dead:
                    continue
                calls, cost = _totals(rows)
                if args.max_calls is not None and calls >= args.max_calls:
                    stopped = f"max_calls reached ({calls})"
                    return
                if args.max_cost is not None and cost >= args.max_cost:
                    stopped = f"max_cost reached ({cost:.4f})"
                    return
                cell_dict = cell.as_dict()
                if needs_rival:
                    cell_dict["opponent_policy"] = cell.opponent_policy.replace("<rival>", rival)
                task = {"subject": subject, "cell": cell_dict, "key": cell.key, "decks": suite.decks}
                if args.trace:
                    slug = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:10]
                    task["trace_path"] = str(run_dir / "traces" / slug / f"{cell.key.translate(str.maketrans('/|: ', '____'))}.json")
                running[pool.submit(_spawn, task, args.game_timeout, run_dir / "calls.jsonl")] = (subject, cell)

        queue, running = list(todo), {}
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            submit_next(pool, queue, running)
            while running:
                finished, _ = wait(list(running), return_when=FIRST_COMPLETED)
                for future in finished:
                    subject, cell = running.pop(future)
                    row = future.result()
                    with lock:
                        rows.append(row)
                        with games_path.open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    if row.get("fatal") or row.get("rival_fatal"):
                        dead[subject] = str(row.get("fatal") or f"rival: {row['rival_fatal']}")
                    flag = " DEGRADED" if row.get("degraded") else ""
                    print(f"[bench] {len(rows)} {subject} | {cell.group} {cell.deck} vs {cell.opponent} "
                          f"seed={cell.seed} side={cell.side} -> score={row.get('score')} "
                          f"err={row.get('error')} {row.get('wall_seconds')}s{flag}", flush=True)
                submit_next(pool, queue, running)
        for subject, reason in dead.items():
            print(f"[bench] subject {subject!r} stopped: {reason}", flush=True)
        if dead and stopped is None:
            stopped = "fatal API error: " + "; ".join(f"{s}: {r}" for s, r in dead.items())
        print(f"[bench] played in {time.perf_counter() - started:.0f}s", flush=True)

    report = build_report(suite, rows, subjects, reference=args.reference)
    calls, cost = _totals(rows)
    report.update({"tag": tag, "generated": _dt.datetime.now().isoformat(timespec="seconds"),
                   "stopped": stopped, "total_calls": calls, "total_cost": round(cost, 6),
                   "engine_lock": load_engine_lock(), "runtime": runtime_metadata(),
                   "raw": display_path(games_path)})
    out_dir = Path(ensure_dir(reports_dir() / "bench"))
    (out_dir / f"{tag}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{tag}.md").write_text(render_markdown(report), encoding="utf-8")
    print(render_markdown(report))
    print(f"[bench] raw {games_path}\n[bench] report {out_dir / (tag + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
