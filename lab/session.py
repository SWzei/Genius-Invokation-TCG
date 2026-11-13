"""Lab sessions: what a game is (spec) and how it is stored.

A session is one game between two *seats*; a seat is a human or a policy spec
(``envs.policy.build_policy``: scripted, neural, ``llm:<profile>``...). Everything
needed to reproduce the game is in the spec (decks, seed, policy specs) plus the
ordered decisions in ``events.jsonl`` -- ``lab.replay`` re-runs the engine from
them, which is how demonstrations and feedback become training data without
storing tensors here.

Layout (``<data>/lab/<session id>/``, append-only while the game runs)::

    session.json     spec, engine lock, runtime, status, result
    events.jsonl     every event of the game, in order (full information)
    feedback.jsonl   ratings / corrections / comments, one per line
    chat.jsonl       strategy discussions, one exchange per line
    calls.jsonl      one line per model API call (no prompt text, no key)

``events.jsonl`` holds both seats' private views: it is the experimenter's record.
What a *player* may see while the game is live is decided by
:func:`project_event`.
"""

from __future__ import annotations

import datetime as _dt
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from common.paths import data_dir

SCHEMA = "lab.session/1"
HUMAN = "human"
SPEC_FILE, EVENTS_FILE, FEEDBACK_FILE, CHAT_FILE, CALLS_FILE = (
    "session.json", "events.jsonl", "feedback.jsonl", "chat.jsonl", "calls.jsonl")
ACTORS = ("human", "policy", "override", "autopilot", "forced")


class SpecError(ValueError):
    pass


@dataclass(frozen=True)
class SeatSpec:
    kind: str = "policy"            # "human" | "policy"
    policy: str = "heuristic"       # policy spec for kind == "policy"

    @property
    def is_human(self) -> bool:
        return self.kind == HUMAN

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "policy": "" if self.is_human else self.policy}


@dataclass(frozen=True)
class SessionSpec:
    deck0: str
    deck1: str
    seats: tuple[SeatSpec, SeatSpec]
    seed: int
    # AI seats wait for approval / override before each action (needs full visibility).
    intervene: bool = False
    # A human player may see the AI seats' private views and decision traces while
    # playing. Demonstrations recorded this way are flagged and excluded from BC export.
    reveal: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        if int(self.seed) <= 0:
            raise SpecError("seed must be >= 1 (engine seed 0 is degenerate: every die rolls the same face)")
        if len(self.seats) != 2:
            raise SpecError("a session has exactly two seats")
        for seat in self.seats:
            if seat.kind not in (HUMAN, "policy"):
                raise SpecError(f"unknown seat kind {seat.kind!r}")
            if not seat.is_human and not seat.policy.strip():
                raise SpecError("a policy seat needs a policy spec")
        if self.intervene and self.human_seats and not self.reveal:
            raise SpecError("'intervene' shows the AI seat's private view; with a human player "
                            "it requires 'reveal' (the game is then flagged as not information-clean)")

    @property
    def human_seats(self) -> tuple[int, ...]:
        return tuple(i for i, seat in enumerate(self.seats) if seat.is_human)

    @property
    def mode(self) -> str:
        return {0: "ai_vs_ai", 1: "human_vs_ai", 2: "human_vs_human"}[len(self.human_seats)]

    @property
    def spectate(self) -> bool:
        """The viewer may see both seats' private information."""
        return not self.human_seats or self.reveal

    def deck(self, seat: int) -> str:
        return self.deck0 if int(seat) == 0 else self.deck1

    def as_dict(self) -> dict[str, Any]:
        return {"deck0": self.deck0, "deck1": self.deck1,
                "seats": [seat.as_dict() for seat in self.seats], "seed": int(self.seed),
                "intervene": bool(self.intervene), "reveal": bool(self.reveal),
                "note": self.note, "mode": self.mode}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SessionSpec":
        seats = tuple(SeatSpec(kind=str(s.get("kind", "policy")), policy=str(s.get("policy") or "heuristic"))
                      for s in payload.get("seats", ()))
        return cls(deck0=str(payload["deck0"]), deck1=str(payload["deck1"]), seats=seats,  # type: ignore[arg-type]
                   seed=int(payload["seed"]), intervene=bool(payload.get("intervene", False)),
                   reveal=bool(payload.get("reveal", False)), note=str(payload.get("note", "")))


def lab_dir(root: str | Path | None = None) -> Path:
    return Path(root) if root is not None else data_dir() / "lab"


def new_session_id() -> str:
    return _dt.datetime.now().strftime("%Y%m%dT%H%M%S") + "_" + secrets.token_hex(3)


def next_seed(root: str | Path | None = None) -> int:
    """A seed no stored session used yet (>= 1), so exported game keys stay unique."""
    used = {int(meta.get("spec", {}).get("seed", 0)) for meta in list_sessions(root)}
    seed = 1
    while seed in used:
        seed += 1
    return seed


def _append(path: Path, row: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                rows.append(json.loads(line))
            except ValueError:
                break       # torn trailing line of a killed worker
    return rows


@dataclass
class SessionStore:
    """One session directory."""

    path: Path

    @property
    def id(self) -> str:
        return self.path.name

    @classmethod
    def create(cls, spec: SessionSpec, *, root: str | Path | None = None,
               session_id: str | None = None) -> "SessionStore":
        from common.lock import load_engine_lock, runtime_metadata

        path = lab_dir(root) / (session_id or new_session_id())
        path.mkdir(parents=True, exist_ok=False)
        store = cls(path)
        store.write_meta({
            "schema": SCHEMA, "id": path.name,
            "created": _dt.datetime.now().isoformat(timespec="seconds"),
            "spec": spec.as_dict(), "status": "running", "result": None,
            "engine_lock": load_engine_lock(), "runtime": runtime_metadata(),
            # A human who could see hidden information did not play a fair game.
            "information_clean": not (spec.reveal and bool(spec.human_seats)),
        })
        return store

    def meta(self) -> dict[str, Any]:
        return json.loads((self.path / SPEC_FILE).read_text(encoding="utf-8"))

    def write_meta(self, meta: Mapping[str, Any]) -> None:
        tmp = self.path / (SPEC_FILE + ".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path / SPEC_FILE)

    def update_meta(self, **changes: Any) -> dict[str, Any]:
        meta = self.meta()
        meta.update(changes)
        self.write_meta(meta)
        return meta

    def spec(self) -> SessionSpec:
        return SessionSpec.from_dict(self.meta()["spec"])

    def append_event(self, event: Mapping[str, Any]) -> None:
        _append(self.path / EVENTS_FILE, event)

    def events(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.path / EVENTS_FILE)

    def decisions(self) -> list[dict[str, Any]]:
        return [e for e in self.events() if e.get("type") == "decision"]

    def add_feedback(self, row: Mapping[str, Any]) -> dict[str, Any]:
        row = {"t": _dt.datetime.now().isoformat(timespec="seconds"), **row}
        _append(self.path / FEEDBACK_FILE, row)
        return row

    def feedback(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.path / FEEDBACK_FILE)

    def add_chat(self, row: Mapping[str, Any]) -> None:
        _append(self.path / CHAT_FILE, {"t": _dt.datetime.now().isoformat(timespec="seconds"), **row})

    def chat(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.path / CHAT_FILE)

    def calls(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.path / CALLS_FILE)


def list_sessions(root: str | Path | None = None) -> list[dict[str, Any]]:
    """Stored sessions' metadata, newest first."""
    base = lab_dir(root)
    if not base.exists():
        return []
    out = []
    for path in sorted(base.iterdir(), reverse=True):
        if (path / SPEC_FILE).exists():
            try:
                out.append(SessionStore(path).meta())
            except (OSError, ValueError):
                continue
    return out


def open_session(session_id: str, root: str | Path | None = None) -> SessionStore:
    path = lab_dir(root) / session_id
    if "/" in session_id or "\\" in session_id or ".." in session_id or not (path / SPEC_FILE).exists():
        raise KeyError(f"unknown session {session_id!r}")
    return SessionStore(path)


# --------------------------------------------------------------------------- #
# visibility
# --------------------------------------------------------------------------- #
_PUBLIC_DECISION_KEYS = ("type", "n", "seat", "step", "request_type", "actor", "policy", "public_text")
ALL = "all"


def project_event(event: Mapping[str, Any], viewer: int | str) -> dict[str, Any] | None:
    """The part of ``event`` that ``viewer`` (a seat, or ``"all"``) may see; ``None`` = nothing."""
    if viewer == ALL:
        return dict(event)
    kind = event.get("type")
    seat = event.get("seat")
    if kind in ("start", "end", "error"):
        return dict(event)
    if seat == viewer:
        return dict(event)
    if kind == "decision":
        return {key: event[key] for key in _PUBLIC_DECISION_KEYS if key in event}
    return None       # another seat's state / request / proposal / advice / chat


def project_events(events: Iterable[Mapping[str, Any]], viewer: int | str) -> list[dict[str, Any]]:
    return [p for p in (project_event(e, viewer) for e in events) if p is not None]
