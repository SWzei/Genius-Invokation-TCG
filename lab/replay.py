"""Re-run stored lab sessions and turn them into analysis and training data.

A session stores *which option was played at each decision*, not tensors. The engine
is deterministic given decks, seed and actions, so re-running it with
:class:`ReplayPolicy` reconstructs every decision context exactly; each replayed
decision is checked against the stored one (option count and engine label) and a
mismatch stops the replay instead of producing misaligned data.

From the replayed contexts this module derives:

* :func:`export_bc` -- a ``train.collect``-format replay directory (``samples.jsonl``
  + ``manifest.json`` with the encoder layout), consumable by
  ``scripts.datafirst_bc_store`` / ``datafirst_bc_train`` unchanged (BC, AWR, PG);
* :func:`export_supervision` -- ``reps.strategy.DecisionSupervision`` records that
  carry the person's input (``HumanSignal``): demonstrations, overrides,
  corrections, ratings; joinable to the exported corpus by ``store_key`` and usable
  as ``--distill-target human`` or as input to counterfactual verification;
* :func:`compare_policies` -- what other policies would have played at each stored
  decision (agreement with the played action and with each other).

A human demonstration made while hidden information was visible
(``information_clean = false``) is exported only on request.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .session import SessionStore

EXPORT_GENERATOR = "lab.replay/1"
HUMAN_ACTORS = ("human", "forced")


class ReplayMismatch(RuntimeError):
    """The re-run game no longer matches the stored decisions."""


class _ReplayDone(Exception):
    """Stored decisions exhausted (a game that was quit or aborted)."""


class ReplayPolicy:
    """Plays one seat's stored decisions back, verifying each against the live context."""

    def __init__(self, seat: int, decisions: Sequence[Mapping[str, Any]],
                 on_decision: Callable[[Mapping[str, Any], Any], None] | None = None) -> None:
        self.seat = int(seat)
        self.decisions = list(decisions)
        self.on_decision = on_decision
        self.cursor = 0
        self.exhausted = False
        self.name = f"replay:p{seat}"

    def choose(self, built: Any) -> int:
        from agents.human import HumanQuit

        codes = [int(c) for c in built.context.legal_low_level_codes]
        if self.cursor >= len(self.decisions):
            self.exhausted = True
            raise HumanQuit("stored decisions exhausted")       # stops run_match cleanly
        stored = self.decisions[self.cursor]
        index = int(stored["index"])
        specs = built.context.legal_low_level_specs
        if (len(codes) != int(stored["n_options"]) or not 0 <= index < len(codes)
                or str(specs[index].label) != str(stored["label"])
                or int(built.context.step_index) != int(stored["step"])):
            raise ReplayMismatch(
                f"seat {self.seat} decision {self.cursor} (step {stored['step']}): stored "
                f"{stored['n_options']} options / {stored['label']!r}, replay has {len(codes)} / "
                f"{specs[index].label if 0 <= index < len(codes) else '?'!r}")
        self.cursor += 1
        if self.on_decision is not None:
            self.on_decision(stored, built)
        return codes[index]


@dataclass
class ReplayedSession:
    store: SessionStore
    meta: dict[str, Any]
    items: list[tuple[dict[str, Any], Any]] = field(default_factory=list)   # (decision event, built)
    winner: int | None = None
    error: str | None = None
    complete: bool = False          # replay reached the stored end of the game

    @property
    def spec(self) -> Any:
        return self.store.spec()


def replay_session(store: SessionStore, *, full_state: bool = False) -> ReplayedSession:
    """Re-run a stored session and return every decision with its rebuilt context."""
    from envs.decks import deck_spec
    from envs.match import run_match

    meta = store.meta()
    spec = store.spec()
    decisions = store.decisions()
    out = ReplayedSession(store=store, meta=meta)
    mismatch: list[str] = []

    def capture(stored: Mapping[str, Any], built: Any) -> None:
        out.items.append((dict(stored), built))

    policies = []
    for seat in (0, 1):
        policy = ReplayPolicy(seat, [d for d in decisions if int(d["seat"]) == seat], capture)
        original = policy.choose

        def guarded(built: Any, _choose=original) -> int:
            try:
                return _choose(built)
            except ReplayMismatch as exc:           # PolicyPlayer would swallow it
                mismatch.append(str(exc))
                from agents.human import HumanQuit

                raise HumanQuit("replay mismatch") from exc

        policy.choose = guarded                     # type: ignore[method-assign]
        policies.append(policy)
    record = run_match(deck_spec(spec.deck0), deck_spec(spec.deck1), policies[0], policies[1],
                       seed=int(spec.seed), full_state_for_agents=full_state)
    if mismatch:
        raise ReplayMismatch(mismatch[0])
    result = meta.get("result") or {}
    played_out = not any(p.exhausted for p in policies) and record.error is None
    out.winner = record.winner if played_out else None
    out.error = None if played_out else (record.error or "incomplete")
    out.complete = played_out and len(out.items) == len(decisions)
    if played_out and result.get("winner") != record.winner:
        raise ReplayMismatch(f"winner differs: stored {result.get('winner')}, replay {record.winner}")
    return out


# --------------------------------------------------------------------------- #
# feedback -> per-decision human signals
# --------------------------------------------------------------------------- #
def human_signals(store: SessionStore) -> dict[tuple[int, int], Any]:
    """(seat, step) -> the strongest ``HumanSignal`` recorded for that decision.

    Precedence: correction > override > demonstration > rating. A later feedback row
    for the same decision replaces an earlier one of the same kind.
    """
    from reps.strategy import HumanSignal

    meta = store.meta()
    clean = bool(meta.get("information_clean", True))
    rank = {"rating": 0, "demonstration": 1, "override": 2, "correction": 3}
    out: dict[tuple[int, int], HumanSignal] = {}

    def put(key: tuple[int, int], signal: HumanSignal) -> None:
        current = out.get(key)
        if current is None or rank[signal.kind] >= rank[current.kind]:
            out[key] = signal

    for event in store.decisions():
        key = (int(event["seat"]), int(event["step"]))
        if event.get("actor") == "human":
            put(key, HumanSignal("demonstration", preferred_index=int(event["index"]), information_clean=clean))
        elif event.get("actor") == "override":
            proposed = event.get("proposed") or {}
            # An override is made with the AI seat's view on screen by design.
            put(key, HumanSignal("override", preferred_index=int(event["index"]),
                                 rejected_index=proposed.get("index"), information_clean=True))
    played = {(int(e["seat"]), int(e["step"])): int(e["index"]) for e in store.decisions()}
    for row in store.feedback():
        if row.get("scope") == "game" or row.get("step") is None:
            continue
        key = (int(row["seat"]), int(row["step"]))
        if key not in played:
            continue
        preferred = row.get("preferred_index")
        common = {"rating": int(row.get("rating", 0) or 0), "comment": str(row.get("comment", "")),
                  "annotator": str(row.get("annotator", "")),
                  # Post-game review sees the acting seat's full view on purpose: the
                  # reviewer judges the decision with what that seat knew.
                  "information_clean": bool(row.get("information_clean", True))}
        if preferred is not None and int(preferred) != played[key]:
            put(key, HumanSignal("correction", preferred_index=int(preferred),
                                 rejected_index=played[key], **common))
        elif common["rating"] or common["comment"]:
            existing = out.get(key)
            if existing is None or existing.kind == "rating":
                put(key, HumanSignal("rating", preferred_index=None, **common))
    return out


# --------------------------------------------------------------------------- #
# exports
# --------------------------------------------------------------------------- #
def _seat_selected(spec: Any, seat: int, events: Sequence[Mapping[str, Any]], seats: str) -> bool:
    if seats == "all":
        return True
    if seats == "human":
        return spec.seats[seat].is_human
    if seats == "corrected":        # policy seats whose trajectory a person edited
        return any(int(e["seat"]) == seat and e.get("actor") == "override" for e in events)
    raise ValueError(f"unknown seat selector {seats!r} (human | corrected | all)")


def export_bc(
    stores: Iterable[SessionStore],
    out_dir: str | Path,
    *,
    encoder_profile: str = "v2",
    seats: str = "human",
    include_autopilot: bool = False,
    include_unclean: bool = False,
    tag: str | None = None,
) -> dict[str, Any]:
    """Write a ``train.collect``-format corpus from finished sessions.

    ``seats``: ``human`` (the people's own decisions), ``corrected`` (policy seats in
    which a person overrode at least one action -- the played, corrected trajectory),
    or ``all``. One record per (session, seat); ``value_target`` is that seat's game
    outcome, so only games that reached a result are exported.
    """
    from common.lock import load_engine_lock, runtime_metadata
    from envs.observation import encoder_for_profile
    from eval.stats import outcome_score
    from train.data import Sample, sample_to_payload

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    samples_path = out / "samples.jsonl"
    if samples_path.exists():
        raise FileExistsError(f"{samples_path} exists; export to a new directory (corpora are append-only)")
    encoder = encoder_for_profile(encoder_profile)
    report: dict[str, Any] = {"games": 0, "samples": 0, "skipped": [], "sessions": []}
    seen_keys: set[tuple[Any, ...]] = set()
    lines: list[str] = []
    for store in stores:
        meta = store.meta()
        if meta.get("status") != "finished" or (meta.get("result") or {}).get("winner") is None:
            report["skipped"].append({"session": store.id, "reason": "no game result"})
            continue
        if not meta.get("information_clean", True) and not include_unclean:
            report["skipped"].append({"session": store.id, "reason": "hidden information was visible to the player"})
            continue
        try:
            replayed = replay_session(store, full_state=True)
        except ReplayMismatch as exc:
            report["skipped"].append({"session": store.id, "reason": f"replay mismatch: {exc}"})
            continue
        spec = replayed.spec
        events = [event for event, _built in replayed.items]
        for seat in (0, 1):
            if not _seat_selected(spec, seat, events, seats):
                continue
            actors = set(HUMAN_ACTORS) if spec.seats[seat].is_human else {"policy", "override", "forced"}
            if include_autopilot:
                actors.add("autopilot")
            deck, opponent = spec.deck(seat), spec.deck(1 - seat)
            key = (deck, opponent, int(spec.seed), seat)
            if key in seen_keys:
                report["skipped"].append({"session": store.id, "seat": seat,
                                          "reason": f"duplicate game key {key}"})
                continue
            value = float(outcome_score(replayed.winner, seat))
            payloads = []
            for event, built in replayed.items:
                if int(event["seat"]) != seat or event.get("actor") not in actors:
                    continue
                context = built.context
                observation = encoder.encode_context(context, history=(), include_training_targets=True)
                if not observation.option_features:
                    continue
                payloads.append(sample_to_payload(Sample(
                    observation=observation, teacher_index=int(event["index"]), value_target=value,
                    request_type=context.request_type.value, step_index=int(context.step_index),
                    deck=deck, opponent=opponent)))
            if not payloads:
                continue
            seen_keys.add(key)
            record: dict[str, Any] = {"index": report["games"], "deck": deck, "opponent": opponent,
                                      "seed": int(spec.seed), "error": None, "samples": payloads}
            if seat != 0:
                record["side"] = seat
            lines.append(json.dumps(record, ensure_ascii=False))
            report["games"] += 1
            report["samples"] += len(payloads)
            report["sessions"].append({"session": store.id, "seat": seat, "samples": len(payloads),
                                       "value_target": value})
    samples_path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    manifest = {
        "tag": tag or out.name, "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "generator": EXPORT_GENERATOR, "source": "lab sessions",
        "spec": {"seats": seats, "include_autopilot": include_autopilot,
                 "include_unclean": include_unclean, "encoder_profile": encoder_profile,
                 "teacher": "human" if seats == "human" else seats},
        "encoder_config": encoder.to_dict(),
        "engine_lock": load_engine_lock(), "runtime": runtime_metadata(), **report,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def export_supervision(
    stores: Iterable[SessionStore],
    out_path: str | Path,
    *,
    kinds: Sequence[str] = ("demonstration", "override", "correction", "rating"),
    annotate: bool = True,
) -> dict[str, Any]:
    """Write ``DecisionSupervision`` records for every decision that has a human signal."""
    from eval.stats import outcome_score
    from reps.knowledge import matching_units
    from reps.strategy import DecisionSupervision, Provenance, write_supervision
    from train.evidence import default_describer, option_refs

    records: list[DecisionSupervision] = []
    report: dict[str, Any] = {"records": 0, "by_kind": {}, "skipped": [], "sessions": []}
    created = _dt.datetime.now().isoformat(timespec="seconds")
    for store in stores:
        signals = {k: v for k, v in human_signals(store).items() if v.kind in kinds}
        if not signals:
            continue
        try:
            replayed = replay_session(store)
        except ReplayMismatch as exc:
            report["skipped"].append({"session": store.id, "reason": f"replay mismatch: {exc}"})
            continue
        spec = replayed.spec
        ordinals = {0: 0, 1: 0}
        count = 0
        for event, built in replayed.items:
            seat = int(event["seat"])
            ordinal = ordinals[seat]
            ordinals[seat] += 1
            signal = signals.get((seat, int(event["step"])))
            if signal is None:
                continue
            context = built.context
            describer = default_describer(spec.deck(1 - seat))
            view = context.player_view
            outcome = float(outcome_score(replayed.winner, seat)) if replayed.winner is not None else 0.5
            records.append(DecisionSupervision(
                deck=spec.deck(seat), opponent=spec.deck(1 - seat), seed=int(spec.seed), side=seat,
                step_index=int(context.step_index), ordinal=ordinal,
                round_number=int(view.round_number) if view is not None else 0,
                request_type=context.request_type.value,
                options=option_refs(context, describer),
                expert_index=int(event["index"]),
                expert_policy="human" if event.get("actor") in ("human", "override") else str(event.get("policy", "")),
                outcome=outcome,
                text=describer.describe_state(context) if view is not None else "",
                knowledge=tuple(matching_units(context)) if annotate else (),
                evidence=None,
                provenance=Provenance(source="genshin-gitcg/lab", version=EXPORT_GENERATOR,
                                      generator=EXPORT_GENERATOR, created=created,
                                      extra={"session": store.id, "actor": event.get("actor"),
                                             "game_complete": replayed.complete}),
                human=signal,
            ))
            report["by_kind"][signal.kind] = report["by_kind"].get(signal.kind, 0) + 1
            count += 1
        report["sessions"].append({"session": store.id, "records": count})
    report["records"] = write_supervision(out_path, records)
    report["path"] = str(out_path)
    return report


def compare_policies(store: SessionStore, specs: Sequence[str], *, seat: int | None = None,
                     limit: int | None = None) -> dict[str, Any]:
    """Ask other policies what they would play at each stored decision.

    Every policy sees the acting seat's context exactly as it was (same information),
    so the comparison is like-for-like. Policies with a model budget stop being
    asked when it runs out (their later cells are ``None``).
    """
    from common.seeding import derive_seed
    from envs.policy import build_policy

    replayed = replay_session(store)
    spec = replayed.spec
    policies = {name: build_policy(name, seed=derive_seed(spec.seed, "compare", name), role="compare")
                for name in specs}
    rows = []
    agree = {name: 0 for name in specs}
    asked = {name: 0 for name in specs}
    pair: dict[tuple[str, str], list[int]] = {}
    for event, built in replayed.items:
        if seat is not None and int(event["seat"]) != int(seat):
            continue
        if int(event["n_options"]) <= 1:
            continue
        if limit is not None and len(rows) >= limit:
            break
        codes = [int(c) for c in built.context.legal_low_level_codes]
        choices: dict[str, int | None] = {}
        for name, policy in policies.items():
            try:
                code = int(policy.choose(built))
                choices[name] = codes.index(code) if code in codes else None
            except Exception:
                choices[name] = None
            if choices[name] is not None:
                asked[name] += 1
                agree[name] += int(choices[name] == int(event["index"]))
        names = list(specs)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if choices[a] is not None and choices[b] is not None:
                    hits = pair.setdefault((a, b), [0, 0])
                    hits[0] += int(choices[a] == choices[b])
                    hits[1] += 1
        options = event.get("options") or []
        rows.append({"seat": int(event["seat"]), "step": int(event["step"]),
                     "request_type": event["request_type"], "round": (event.get("state") or {}).get("round"),
                     "played": int(event["index"]), "played_text": event.get("text", ""),
                     "actor": event.get("actor"),
                     "choices": {name: (None if c is None else
                                        {"index": c, "text": options[c]["text"] if c < len(options) else ""})
                                 for name, c in choices.items()}})
    summaries = {}
    for name, policy in policies.items():
        summary = getattr(policy, "summary", None)
        summaries[name] = {"decisions": asked[name],
                           "agree_with_played": round(agree[name] / asked[name], 4) if asked[name] else None,
                           **({"llm": summary()} if callable(summary) else {})}
    return {"session": store.id, "seat": seat, "decisions": len(rows), "policies": summaries,
            "pairwise": [{"a": a, "b": b, "agree": round(h[0] / h[1], 4) if h[1] else None, "n": h[1]}
                         for (a, b), h in pair.items()],
            "rows": rows}
