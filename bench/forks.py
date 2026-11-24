"""Replay and fork traced model-vs-model games (D35).

A traced game (``bench.run --trace``) keeps, for both seats, every decision with the
option index and option count. That is enough to replay the game exactly (same seed,
decks, version) and to *fork* it: stop at any decision, play a chosen option, then
let a common continuation policy finish the game for both seats.

* :func:`game_source` -- a traced game -> a replayable source;
* :func:`replay` -- replay a source to the end (fidelity check), or record every
  decision's context on the way (``on_decision``);
* :func:`query` -- ask another policy what it would choose at a recorded position;
* :func:`fork` -- play ``choice`` at a seat's ``ordinal``-th decision and finish the game
  with ``continuation`` (one spec per seat).

Only seat views (``notification.state``) are given to policies; full state is never
used to choose (AGENTS.md hard constraint 2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


def load_traces(trace_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(trace_dir).glob("*.json"))]


def game_source(payload: Mapping[str, Any], decks: Mapping[str, Any]) -> dict[str, Any]:
    """Traced game -> ``{deck0, deck1, decks, seed, version, seats: {0: [...], 1: [...]}, ...}``.

    Each seat list holds the decisions in order: ``index`` (into the legal options),
    ``n`` (option count), ``request``, ``source`` (llm / fallback / forced) and the reply."""
    cell = payload["cell"]
    side = int(cell["side"])
    subject_deck, rival_deck = cell["deck"], cell["opponent_deck"]
    deck0, deck1 = (subject_deck, rival_deck) if side == 0 else (rival_deck, subject_deck)
    seats: dict[int, list[dict[str, Any]]] = {}
    for seat, traces, role in ((side, payload["subject_traces"], "subject"),
                               (1 - side, payload["rival_traces"], "rival")):
        seats[seat] = [{"index": int(t["final_index"]), "n": int(t["n_options"]), "request": t["request_type"],
                        "source": t["source"], "final_text": t.get("final_text"), "reason": t.get("reason"),
                        "knowledge": [i.get("id") for i in (t.get("knowledge") or {}).get("items", [])],
                        "role": role} for t in traces]
    return {"deck0": deck0, "deck1": deck1, "decks": dict(decks), "seed": int(cell["seed"]),
            "version": cell.get("version") or "", "seats": seats, "subject_seat": side,
            "winner": payload.get("winner"), "rounds": payload.get("rounds"),
            "subject": payload.get("subject"), "pair": int(cell.get("rep", 0)), "group": cell.get("group")}


class _Shared:
    def __init__(self) -> None:
        self.forked = False


class _Seat:
    """Replays its seat's recorded decisions; at ``(fork_at, choice)`` plays ``choice`` and
    flags the fork; once forked (by either seat) hands every decision to ``continuation``."""

    def __init__(self, seat: int, decisions: Sequence[Mapping[str, Any]], shared: _Shared, *,
                 fork_at: int | None = None, choice: int | None = None, continuation: Any = None,
                 on_decision: Callable[[int, int, Any], None] | None = None,
                 stop_at: int | None = None) -> None:
        self.seat, self.decisions, self.shared = seat, list(decisions), shared
        self.fork_at, self.choice, self.continuation = fork_at, choice, continuation
        self.on_decision, self.stop_at = on_decision, stop_at
        self.cursor, self.mismatch, self.at = 0, None, None
        self.name = "fork-replay"

    def choose(self, built: Any) -> int:
        from agents.human import HumanQuit

        codes = [int(c) for c in built.context.legal_low_level_codes]
        if self.shared.forked:
            if self.continuation is None:
                raise HumanQuit("fork: no continuation")
            return int(self.continuation.choose(built))
        if self.stop_at is not None and self.cursor == self.stop_at:
            self.at = built
            raise HumanQuit("fork: captured")
        if self.fork_at is not None and self.cursor == self.fork_at:
            if self.choice is None or not 0 <= self.choice < len(codes):
                self.mismatch = f"fork choice {self.choice} outside {len(codes)} options"
                raise HumanQuit("fork: bad choice")
            self.shared.forked, self.at = True, built
            self.cursor += 1
            return codes[self.choice]
        if self.cursor >= len(self.decisions):
            self.mismatch = f"seat {self.seat}: ran past its {len(self.decisions)} recorded decisions"
            raise HumanQuit("fork: overrun")
        d = self.decisions[self.cursor]
        if len(codes) != d["n"] or not 0 <= d["index"] < len(codes):
            self.mismatch = f"seat {self.seat} decision {self.cursor}: recorded {d['n']} options, replay has {len(codes)}"
            raise HumanQuit("fork: mismatch")
        if self.on_decision is not None:
            self.on_decision(self.seat, self.cursor, built)
        self.cursor += 1
        return codes[d["index"]]


def _run(source: Mapping[str, Any], seats: Sequence[_Seat]) -> Any:
    from bench.suite import resolve_deck
    from envs.match import run_match

    deck0 = resolve_deck(source["deck0"], source.get("decks"))
    deck1 = resolve_deck(source["deck1"], source.get("decks"))
    return run_match(deck0, deck1, seats[0], seats[1], seed=int(source["seed"]), version=source.get("version") or None)


def replay(source: Mapping[str, Any], *,
           on_decision: Callable[[int, int, Any], None] | None = None) -> dict[str, Any]:
    """Replay to the end. ``ok``: no mismatch, every recorded decision used, same winner."""
    shared = _Shared()
    seats = [_Seat(s, source["seats"][s], shared, on_decision=on_decision) for s in (0, 1)]
    record = _run(source, seats)
    mismatch = seats[0].mismatch or seats[1].mismatch
    used = all(seats[s].cursor == len(source["seats"][s]) for s in (0, 1))
    same = record.winner == source.get("winner")
    return {"ok": not mismatch and used and same, "mismatch": mismatch, "all_used": used,
            "winner": record.winner, "recorded_winner": source.get("winner"), "rounds": record.rounds}


def context_at(source: Mapping[str, Any], seat: int, ordinal: int) -> Any:
    """The built decision context of ``seat``'s ``ordinal``-th decision (seat view only)."""
    shared = _Shared()
    seats = [_Seat(s, source["seats"][s], shared, stop_at=ordinal if s == seat else None) for s in (0, 1)]
    _run(source, seats)
    if seats[seat].at is None:
        raise RuntimeError(seats[0].mismatch or seats[1].mismatch or "decision not reached")
    return seats[seat].at


def query(policy: Any, built: Any) -> int:
    """Option index ``policy`` chooses at a recorded position."""
    code = int(policy.choose(built))
    return [int(c) for c in built.context.legal_low_level_codes].index(code)


def fork(source: Mapping[str, Any], seat: int, ordinal: int, choice: int,
         continuation: Sequence[Any]) -> dict[str, Any]:
    """Play ``choice`` at ``seat``'s ``ordinal``-th decision, finish with ``continuation[s]``.

    Returns the outcome for ``seat``: ``score`` 1 / 0.5 / 0 (None if the game broke)."""
    shared = _Shared()
    seats = [_Seat(s, source["seats"][s], shared, fork_at=ordinal if s == seat else None,
                   choice=choice if s == seat else None, continuation=continuation[s]) for s in (0, 1)]
    record = _run(source, seats)
    mismatch = seats[0].mismatch or seats[1].mismatch
    if mismatch or not shared.forked or record.error and "quit" in str(record.error).lower():
        return {"score": None, "error": mismatch or record.error or "fork point not reached"}
    if record.winner is None:
        score = 0.5 if not record.error else None
    else:
        score = 1.0 if int(record.winner) == seat else 0.0
    return {"score": score, "winner": record.winner, "rounds": record.rounds, "error": record.error,
            "truncated": bool(record.truncated)}
