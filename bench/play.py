"""Play one benchmark cell for one subject (one game, one process).

``python -m bench.play`` reads a JSON task on stdin and prints one JSON row. The
runner starts one such process per game: the action codebook is process-global, and
a game with a model in it mostly waits on the network, so games run side by side.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Mapping

DEGRADED_BELOW = 0.9     # a model that answered fewer of its decisions than this did not play the game


def _llm_side(policy: Any) -> tuple[dict[str, Any], str | None]:
    summary = policy.summary() if callable(getattr(policy, "summary", None)) else {}
    client = getattr(policy, "client", None)
    fatal = None
    if getattr(client, "disabled", None) is not None:
        fatal = f"{client.disabled.error}: {client.disabled.detail}"[:300]
    return summary, fatal


def _degraded(summary: Mapping[str, Any]) -> bool:
    rate = summary.get("llm_rate") if summary else None
    return bool(summary) and rate is not None and float(rate) < DEGRADED_BELOW


def play_cell(subject: str, cell: Mapping[str, Any], decks: Mapping[str, Any] | None = None,
              *, max_steps: int = 5000, trace_path: str | None = None) -> dict[str, Any]:
    from bench.suite import Cell, resolve_deck
    from common.seeding import derive_seed
    from envs.match import run_match
    from envs.policy import build_policy
    from eval.stats import outcome_score

    c = Cell.from_dict(cell)
    side = int(c.side)
    deck, opp_deck = resolve_deck(c.deck, decks), resolve_deck(c.opponent_deck, decks)
    role, opp_role = ("p0", "p1") if side == 0 else ("p1", "p0")
    spec = subject.replace("<deck>", c.deck)
    started = time.perf_counter()
    row: dict[str, Any] = {"subject": subject, "cell": c.key, **c.as_dict()}
    try:
        contestant = build_policy(spec, seed=derive_seed(c.seed, role, c.deck), role=role)
        rival = build_policy(c.opponent_policy, seed=derive_seed(c.seed, opp_role, c.opponent_deck), role=opp_role)
        if trace_path:                              # D34: keep what each model saw, for analysis of train games
            for policy in (contestant, rival):
                if hasattr(policy, "traces"):
                    policy.keep_prompts = True
        if side == 0:
            record = run_match(deck, opp_deck, contestant, rival, seed=c.seed, version=c.version or None,
                               max_steps=max_steps)
        else:
            record = run_match(opp_deck, deck, rival, contestant, seed=c.seed, version=c.version or None,
                               max_steps=max_steps)
    except Exception as exc:                       # a cell that cannot be played is a row, not a crash
        row.update({"score": None, "error": f"{type(exc).__name__}: {exc}"[:300], "truncated": False,
                    "wall_seconds": round(time.perf_counter() - started, 2)})
        return row
    summary, fatal = _llm_side(contestant)
    rival_summary, rival_fatal = _llm_side(rival)
    row.update({
        "winner": record.winner,
        "score": None if record.error else outcome_score(record.winner, side),
        "error": record.error, "truncated": bool(record.truncated), "rounds": record.rounds,
        "decisions": record.decisions0 if side == 0 else record.decisions1,
        "engine_fallbacks": record.fallbacks0 if side == 0 else record.fallbacks1,
        "io_errors": len(record.io_errors0 if side == 0 else record.io_errors1),
        "wall_seconds": round(time.perf_counter() - started, 2),
        "llm": summary,
        # The model did not really play this game: its fallback policy did.
        "degraded": _degraded(summary),
        "fatal": fatal,
        # D37: per-seat public end state (seat order, not subject order); see bench.metrics
        "outcome": record.outcome,
    })
    if rival_summary:                               # model-vs-model games (D34): the opponent is a model too
        row.update({"rival_llm": rival_summary, "rival_degraded": _degraded(rival_summary),
                    "rival_fatal": rival_fatal})
    if trace_path:
        from pathlib import Path

        out = Path(trace_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "subject": subject, "cell": c.as_dict(), "winner": record.winner, "rounds": record.rounds,
            "score": row["score"],
            "subject_traces": [t.as_dict() for t in getattr(contestant, "traces", [])],
            "rival_traces": [t.as_dict() for t in getattr(rival, "traces", [])],
        }, ensure_ascii=False), encoding="utf-8")
    return row


def main() -> int:
    task = json.loads(sys.stdin.read())
    row = play_cell(task["subject"], task["cell"], task.get("decks"), max_steps=int(task.get("max_steps", 5000)),
                    trace_path=task.get("trace_path"))
    sys.stdout.write("\n@@ROW@@" + json.dumps(row, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
