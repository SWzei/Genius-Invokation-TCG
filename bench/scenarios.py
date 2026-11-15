"""Decision scenarios with answers the engine verifies (the static track of the benchmark).

A scenario is one decision of one seat, stored as *how to reach it* (decks, seed,
rules version and both seats' option indices up to that point). The engine is
deterministic, so replaying those indices rebuilds the exact decision context --
the prompt a model sees is produced by the same code as in a real game, from the
acting seat's view only. Three kinds:

``lethal``     a position where at least one legal option wins the game on the spot.
               The winning set is found by playing *every* option of that decision
               in the engine and keeping those after which the game is over and
               won with no further decision by anyone. Score: the subject picks a
               winning option. Chance level is ``|winning| / |options|`` per item.
``agreement``  a sampled action decision of a scripted expert; the label is what the
               expert played. This measures *similarity to the script*, not
               quality -- reported separately and never called accuracy.
``quiz``       state-reading questions with answers taken from the structured view
               (hp, dice, hand sizes, round ...) plus one hidden-information probe:
               "is card X in the opponent's hand?" for a card that really is there.
               The only correct answer is "unknown" -- the view does not show it.
               Model subjects only.

Source games are played by scripted experts on seeds reserved for scenarios, so the
experts themselves are *generators* of the lethal positions (the final blow they
played is one of the winning options); their own lethal score is partly
self-fulfilling and is marked as such. ``heuristic``, ``legal_random``, neural and
model subjects did not generate anything.

    python -m bench.scenarios build --name v1 --games 40 --workers 2
    python -m bench.scenarios eval  --name v1 --subjects heuristic legal_random "llm:glm-53-plan"
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

from bench.report import display_path
from bench.suite import BENCH_SEED_BASE
from common.paths import data_dir, ensure_dir, reports_dir

SCENARIO_SEED_BASE = BENCH_SEED_BASE + 500_000
SET_DIR = Path(__file__).resolve().parents[1] / "configs" / "bench" / "scenarios"
GENERATOR = "bench.scenarios/1"
LETHAL_LOOKBACK = 3          # the winner's last N action decisions are searched for lethal
QUIZ_KEYS = ("my_active", "my_active_hp", "opp_active_hp", "my_dice", "my_hand", "opp_hand", "round",
             "opp_has_card")


# --------------------------------------------------------------------------- #
# replay plumbing
# --------------------------------------------------------------------------- #
class _Recorder:
    """Wrap a policy and record the option index of every decision (global order)."""

    def __init__(self, inner: Any, seat: int, log: list[dict[str, Any]]) -> None:
        self.inner, self.seat, self.log = inner, int(seat), log
        self.name = getattr(inner, "name", "recorded")

    def choose(self, built: Any) -> int:
        code = int(self.inner.choose(built))
        context = built.context
        codes = [int(c) for c in context.legal_low_level_codes]
        self.log.append({"seat": self.seat, "index": codes.index(code), "n": len(codes),
                         "request": context.request_type.value, "step": int(context.step_index)})
        return code


class _recording_responses:
    """While active, every seat's protobuf response is stored on the trace entry the
    ``_Recorder`` just appended (one ``choose`` per request, same order)."""

    def __init__(self, trace: list[dict[str, Any]]) -> None:
        self.trace = trace

    def __enter__(self) -> None:
        import base64

        import envs.match as match

        self._original = original = match.PolicyPlayer._on_rpc
        trace = self.trace

        def recording(player: Any, request: Any) -> Any:
            before = len(trace)
            response = original(player, request)
            if len(trace) == before + 1:
                trace[-1]["resp"] = base64.b64encode(response.SerializeToString()).decode("ascii")
            return response

        match.PolicyPlayer._on_rpc = recording

    def __exit__(self, *exc: Any) -> None:
        import envs.match as match

        match.PolicyPlayer._on_rpc = self._original


class _Scripted:
    """Replay ``indices``; then optionally play ``then`` once; then stop the game.

    ``capture=True`` stops *at* the first decision after the prefix and keeps its
    context instead of playing. ``overrun`` tells whether this seat was asked for a
    decision it had no instruction for (i.e. the game went on).
    """

    def __init__(self, indices: Sequence[int], counts: Sequence[int], *, then: int | None = None,
                 capture: bool = False) -> None:
        self.indices, self.counts = list(indices), list(counts)
        self.then, self.capture = then, capture
        self.cursor = 0
        self.played_then = False
        self.overrun = False
        self.mismatch: str | None = None
        self.built: Any = None
        self.name = "scenario-replay"

    def choose(self, built: Any) -> int:
        from agents.human import HumanQuit

        codes = [int(c) for c in built.context.legal_low_level_codes]
        if self.cursor < len(self.indices):
            index = self.indices[self.cursor]
            if len(codes) != self.counts[self.cursor] or not 0 <= index < len(codes):
                self.mismatch = (f"decision {self.cursor}: recorded {self.counts[self.cursor]} options, "
                                 f"replay has {len(codes)}")
                raise HumanQuit("scenario replay mismatch")
            self.cursor += 1
            return codes[index]
        if self.capture and self.built is None:
            self.built = built
            raise HumanQuit("scenario reached")
        if self.then is not None and not self.played_then:
            self.played_then = True
            if not 0 <= self.then < len(codes):
                self.mismatch = f"option {self.then} out of range ({len(codes)})"
                raise HumanQuit("scenario replay mismatch")
            return codes[self.then]
        self.overrun = True
        raise HumanQuit("scenario: game continues")


def _decks(source: Mapping[str, Any]) -> tuple[Any, Any]:
    from bench.suite import resolve_deck

    return resolve_deck(source["deck0"], source.get("decks")), resolve_deck(source["deck1"], source.get("decks"))


def _prefixes(source: Mapping[str, Any], seat: int, ordinal: int) -> tuple[list[dict], list[dict]]:
    """(the seat's decisions before ``ordinal``, the other seat's decisions before that point)."""
    trace = source["trace"]
    mine = [d for d in trace if d["seat"] == seat]
    target_pos = trace.index(mine[ordinal])
    return mine[:ordinal], [d for d in trace[:target_pos] if d["seat"] != seat]


def _run(source: Mapping[str, Any], policies: Sequence[Any], *, full_state: bool = False) -> Any:
    from envs.match import run_match

    deck0, deck1 = _decks(source)
    return run_match(deck0, deck1, policies[0], policies[1], seed=int(source["seed"]),
                     version=source.get("version") or None, full_state_for_agents=full_state)


def context_at(source: Mapping[str, Any], seat: int, ordinal: int, *, full_state: bool = False) -> Any:
    """Rebuild the decision context of ``seat``'s ``ordinal``-th decision (0-based)."""
    mine, other = _prefixes(source, seat, ordinal)
    me = _Scripted([d["index"] for d in mine], [d["n"] for d in mine], capture=True)
    opp = _Scripted([d["index"] for d in other], [d["n"] for d in other])
    _run(source, (me, opp) if seat == 0 else (opp, me), full_state=full_state)
    if me.mismatch or opp.mismatch or me.built is None:
        raise RuntimeError(f"scenario replay failed: {me.mismatch or opp.mismatch or 'decision not reached'}")
    return me.built


def _default_response(request: Any) -> Any:
    """A syntactically valid answer for any request (only used to leave a game we are abandoning)."""
    from gitcg.proto.rpc_pb2 import (ActionResponse, ChooseActiveResponse, RerollDiceResponse, Response,
                                     SelectCardResponse, SwitchHandsResponse)

    kind = request.WhichOneof("request")
    if kind == "action":
        return Response(action=ActionResponse(chosen_action_index=max(0, len(request.action.action) - 1)))
    if kind == "choose_active":
        return Response(choose_active=ChooseActiveResponse(active_character_id=request.choose_active.candidate_ids[0]))
    if kind == "reroll_dice":
        return Response(reroll_dice=RerollDiceResponse())
    if kind == "select_card":
        return Response(select_card=SelectCardResponse(
            selected_definition_id=request.select_card.candidate_definition_ids[0]))
    return Response(switch_hands=SwitchHandsResponse())


def _raw_seat(responses: Sequence[bytes], then: bytes | None = None) -> Any:
    """A ``gitcg.Player`` that answers from recorded protobuf responses -- no context
    is built, so a replay runs at engine speed. After the recording (and the optional
    ``then``) it flags ``overrun`` and the driver stops the game."""
    from gitcg import Player
    from gitcg.proto.rpc_pb2 import Response

    class RawSeat(Player):
        def __init__(self) -> None:
            self.cursor = 0
            self.played_then = False
            self.overrun = False

        def _on_rpc(self, request: Any) -> Any:
            if self.cursor < len(responses):
                self.cursor += 1
                return Response.FromString(responses[self.cursor - 1])
            if then is not None and not self.played_then:
                self.played_then = True
                return Response.FromString(then)
            self.overrun = True
            return _default_response(request)

        # the abstract per-request handlers are never reached: ``_on_rpc`` answers everything
        def on_action(self, request: Any) -> Any: raise NotImplementedError
        def on_choose_active(self, request: Any) -> Any: raise NotImplementedError
        def on_reroll_dice(self, request: Any) -> Any: raise NotImplementedError
        def on_select_card(self, request: Any) -> Any: raise NotImplementedError
        def on_switch_hands(self, request: Any) -> Any: raise NotImplementedError

    return RawSeat()


def _raw_prefixes(source: Mapping[str, Any], seat: int, ordinal: int) -> tuple[list[bytes], list[bytes]]:
    import base64

    mine, other = _prefixes(source, seat, ordinal)
    return ([base64.b64decode(d["resp"]) for d in mine], [base64.b64decode(d["resp"]) for d in other])


def option_response(built: Any, index: int) -> bytes:
    """The protobuf ``Response`` that plays option ``index`` of an *action* decision."""
    from gitcg.proto.rpc_pb2 import ActionResponse, Response

    codes = [int(c) for c in built.context.legal_low_level_codes]
    payload = built.payload_by_low_level_code[codes[int(index)]]
    return Response(action=ActionResponse(
        chosen_action_index=int(payload.get("chosen_action_index", 0)),
        used_dice=[int(d) for d in payload.get("used_dice", ())])).SerializeToString()


def boundaries(source: Mapping[str, Any]) -> list[tuple[int, int, str]]:
    """Replay the recorded game at engine speed and snapshot every resumable point.

    -> ``[(responses given by seat 0, by seat 1, state json), ...]``. A fork is only
    exact from ``Game.is_resumable()`` boundaries (``envs/snapshot.py``)."""
    import base64

    from gitcg import Game

    from envs.match import _build_create_param

    raw = [[base64.b64decode(d["resp"]) for d in source["trace"] if d["seat"] == s] for s in (0, 1)]
    seats = [_raw_seat(raw[0]), _raw_seat(raw[1])]
    deck0, deck1 = _decks(source)
    game = Game(create_param=_build_create_param(deck0, deck1, seed=int(source["seed"]),
                                                 version=source.get("version") or None))
    game.set_player(0, seats[0])
    game.set_player(1, seats[1])
    out: list[tuple[int, int, str]] = []
    game.start()
    steps = 0
    while game.is_running() and not (seats[0].overrun or seats[1].overrun) and steps < 5000:
        if game.is_resumable():
            out.append((seats[0].cursor, seats[1].cursor, game.state().json()))
        game.step()
        steps += 1
    if seats[0].overrun or seats[1].overrun or game.winner() != source["winner"]:
        raise RuntimeError("scenario source game did not replay from its recorded responses")
    return out


def option_wins_now(source: Mapping[str, Any], points: Sequence[tuple[int, int, str]], seat: int,
                    ordinal: int, response: bytes) -> bool:
    """True when answering that decision with ``response`` ends the game, won, with no
    further decision by either seat. Forks from the last resumable snapshot before the
    decision and replays the recorded responses in between."""
    from envs.snapshot import fork_game

    mine, other = _raw_prefixes(source, seat, ordinal)
    usable = [p for p in points if p[seat] <= len(mine) and p[1 - seat] <= len(other)]
    if not usable:
        return False
    given = usable[-1]
    me, opp = _raw_seat(mine[given[seat]:], response), _raw_seat(other[given[1 - seat]:])
    game = fork_game(given[2])
    game.set_player(seat, me)
    game.set_player(1 - seat, opp)
    game.start()
    steps = 0
    while game.is_running() and not (me.overrun or opp.overrun) and steps < 5000:
        game.step()
        steps += 1
    if me.overrun or opp.overrun or not me.played_then or game.is_running():
        return False
    try:
        return game.winner() == seat
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def _source_game(task: Mapping[str, Any]) -> dict[str, Any]:
    """Play one source game and derive its scenarios (runs in a worker process)."""
    from common.seeding import derive_seed
    from envs.decks import deck_spec
    from envs.match import run_match
    from envs.policy import build_policy

    deck0, deck1, seed = task["deck0"], task["deck1"], int(task["seed"])
    trace: list[dict[str, Any]] = []
    pilots = (f"expert:{deck0}", f"expert:{deck1}")
    policies = [_Recorder(build_policy(pilots[s], seed=derive_seed(seed, f"p{s}", (deck0, deck1)[s]), role=f"p{s}"),
                          s, trace) for s in (0, 1)]
    with _recording_responses(trace):
        record = run_match(deck_spec(deck0), deck_spec(deck1), policies[0], policies[1], seed=seed)
    source = {"deck0": deck0, "deck1": deck1, "pilots": list(pilots), "seed": seed, "version": "",
              "trace": trace, "winner": record.winner, "rounds": record.rounds}
    out: dict[str, Any] = {"source": source, "scenarios": [], "error": record.error}
    if record.error or record.truncated or record.fallbacks0 or record.fallbacks1:
        out["error"] = record.error or "truncated or fallback"
        return out
    rng = random.Random(derive_seed(seed, "scenario-sample"))
    # -- lethal: search the winner's last action decisions ------------------------- #
    if record.winner in (0, 1):
        seat = int(record.winner)
        mine = [d for d in trace if d["seat"] == seat]
        points = boundaries(source)
        actions = [i for i, d in enumerate(mine) if d["request"] == "action"][-LETHAL_LOOKBACK:]
        for ordinal in actions:
            n = mine[ordinal]["n"]
            if n < 2:
                continue
            built = context_at(source, seat, ordinal)          # one full replay per candidate decision
            winning = [o for o in range(n)
                       if option_wins_now(source, points, seat, ordinal, option_response(built, o))]
            if winning and len(winning) < n:
                out["scenarios"].append({"kind": "lethal", "seat": seat, "ordinal": ordinal, "n_options": n,
                                         "winning": winning, "generator_index": mine[ordinal]["index"],
                                         "is_final_decision": ordinal == actions[-1]})
    # -- agreement / quiz: sampled action decisions --------------------------------- #
    for seat in (0, 1):
        mine = [d for d in trace if d["seat"] == seat]
        pool = [i for i, d in enumerate(mine) if d["request"] == "action" and d["n"] >= 3]
        for ordinal in rng.sample(pool, min(int(task.get("agreement_per_seat", 2)), len(pool))):
            out["scenarios"].append({"kind": "agreement", "seat": seat, "ordinal": ordinal,
                                     "n_options": mine[ordinal]["n"], "expert_index": mine[ordinal]["index"],
                                     "expert": pilots[seat]})
        if pool and task.get("quiz", True):
            out["scenarios"].append({"kind": "quiz", "seat": seat, "ordinal": rng.choice(pool),
                                     "n_options": 0})
    return out


def build_set(name: str, *, games: int, workers: int = 2, decks: Sequence[str] | None = None,
              agreement_per_seat: int = 2) -> dict[str, Any]:
    from envs.decks import expert_decks_by_name

    pool = list(decks or sorted(expert_decks_by_name()))
    tasks = []
    for i in range(int(games)):
        deck0 = pool[i % len(pool)]
        deck1 = pool[(i * 7 + 3) % len(pool)]              # a fixed, spread-out pairing
        if deck1 == deck0:
            deck1 = pool[(i * 7 + 4) % len(pool)]
        tasks.append({"deck0": deck0, "deck1": deck1, "seed": SCENARIO_SEED_BASE + i,
                      "agreement_per_seat": agreement_per_seat})
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=max(1, int(workers))) as pool_exec:
        results = list(pool_exec.map(_source_game, tasks))
    sources, scenarios, errors = [], [], 0
    for result in results:
        if result.get("error"):
            errors += 1
            continue
        source_id = len(sources)
        sources.append(result["source"])
        for scenario in result["scenarios"]:
            scenarios.append({"id": f"{scenario['kind']}-{len(scenarios):04d}", "source": source_id, **scenario})
    counts: dict[str, int] = {}
    for scenario in scenarios:
        counts[scenario["kind"]] = counts.get(scenario["kind"], 0) + 1
    lethal = [s for s in scenarios if s["kind"] == "lethal"]
    payload = {
        "name": name, "generator": GENERATOR, "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "seed_base": SCENARIO_SEED_BASE, "source_games": len(sources), "source_errors": errors,
        "counts": counts,
        "lethal_chance_level": round(sum(len(s["winning"]) / s["n_options"] for s in lethal) / len(lethal), 4)
        if lethal else None,
        "lethal_generator_took_it": sum(1 for s in lethal if s["generator_index"] in s["winning"]),
        "build_seconds": round(time.perf_counter() - started, 1),
        "sources": sources, "scenarios": scenarios,
    }
    from common.lock import load_engine_lock

    payload["engine_lock"] = load_engine_lock()
    path = Path(ensure_dir(SET_DIR)) / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {k: v for k, v in payload.items() if k not in ("sources", "scenarios")} | {"path": str(path)}


def load_set(name_or_path: str) -> dict[str, Any]:
    path = Path(name_or_path)
    if not path.exists():
        path = SET_DIR / f"{name_or_path}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# quiz
# --------------------------------------------------------------------------- #
def quiz_items(built: Any, describer: Any) -> tuple[str, dict[str, Any]]:
    """(question block, answer key) for one decision; needs ``full_state`` for the hidden probe."""
    context = built.context
    seat = int(context.acting_player)
    state = describer.state(context)
    me, opp = state["me"], state["opponent"]
    my_active = next((c for c in me["characters"] if c.get("active")), None)
    opp_active = next((c for c in opp["characters"] if c.get("active")), None)
    key: dict[str, Any] = {
        "my_active": my_active["name"] if my_active else None,
        "my_active_hp": my_active["hp"] if my_active else None,
        "opp_active_hp": opp_active["hp"] if opp_active else None,
        "my_dice": len(me.get("dice") or ()), "my_hand": len(me.get("hand") or ()),
        "opp_hand": opp.get("hand_count"), "round": state["round"],
    }
    questions = [
        '"my_active"：我方出战角色的名字（字符串）',
        '"my_active_hp"：我方出战角色当前生命值（整数）',
        '"opp_active_hp"：对方出战角色当前生命值（整数）',
        '"my_dice"：我方现有骰子总数（整数）',
        '"my_hand"：我方手牌张数（整数）',
        '"opp_hand"：对方手牌张数（整数）',
        '"round"：当前是第几回合（整数）',
    ]
    # Hidden-information probe: name a card that really is in the opponent's hand
    # (privileged, from the full state -- used for the *question*, never the prompt).
    full = getattr(context, "full_state", None)
    card_name = None
    try:
        hidden = full.players[1 - seat].hand_cards
        names = [describer.assets.name(int(c.definition_id)) for c in hidden if int(c.definition_id) > 0]
        visible = {c["name"] for c in me.get("hand") or ()}
        names = [n for n in names if n and n not in visible]
        card_name = sorted(names)[0] if names else None
    except Exception:
        card_name = None
    if card_name:
        key["opp_has_card"] = "unknown"
        key["_probe_card"] = card_name
        questions.append(f'"opp_has_card"：对方手牌里现在有没有【{card_name}】？只能回答 "yes"、"no" 或 "unknown"（看不到就答 unknown）')
    block = ("根据上面的局面回答下列问题，只输出一个 JSON 对象，键名如下：\n" + "\n".join(f"- {q}" for q in questions))
    return block, key


def _quiz_score(key: Mapping[str, Any], reply: Mapping[str, Any] | None) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for name, truth in key.items():
        if name.startswith("_") or truth is None:
            continue
        answer = (reply or {}).get(name)
        if isinstance(truth, str):
            out[name] = isinstance(answer, str) and answer.strip().strip("【】").lower() == truth.lower()
        else:
            try:
                out[name] = int(answer) == int(truth)
            except (TypeError, ValueError):
                out[name] = False
    return out


# --------------------------------------------------------------------------- #
# evaluate
# --------------------------------------------------------------------------- #
def _eval_one(task: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate one subject on one scenario (one process: the codebook is process-global)."""
    from common.llm import extract_json_object
    from common.seeding import derive_seed
    from envs.policy import build_policy
    from reps.describe import DecisionDescriber

    scenario, source, subject = task["scenario"], task["source"], task["subject"]
    seat, ordinal = int(scenario["seat"]), int(scenario["ordinal"])
    deck = source["deck0"] if seat == 0 else source["deck1"]
    row: dict[str, Any] = {"subject": subject, "id": scenario["id"], "kind": scenario["kind"]}
    started = time.perf_counter()
    try:
        built = context_at(source, seat, ordinal, full_state=scenario["kind"] == "quiz")
        policy = build_policy(subject.replace("<deck>", deck), seed=derive_seed(source["seed"], "scenario", seat),
                              role=f"p{seat}")
        codes = [int(c) for c in built.context.legal_low_level_codes]
        if scenario["kind"] == "quiz":
            client = getattr(policy, "client", None)
            if client is None:
                return {**row, "skipped": "quiz needs a model subject"}
            from agents.llm_policy import SYSTEM_PROMPT

            describer = getattr(policy, "describer", None) or DecisionDescriber()
            block, key = quiz_items(built, describer)
            # The prompt shows the acting seat's view only; ``full_state`` supplied one card name for the question.
            messages = [{"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": describer.state_text(_view_only(built.context), detail=False)
                         + "\n\n" + block}]
            result = client.complete(messages, want_json=True, tag="quiz")
            parsed = extract_json_object(result.text) if result.ok else None
            scores = _quiz_score(key, parsed)
            row.update({"ok": result.ok, "error": result.error, "scores": scores,
                        "probe_answer": (parsed or {}).get("opp_has_card"),
                        "latency_seconds": round(result.latency_seconds, 3),
                        "prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens,
                        "cost": result.cost})
            return row
        code = int(policy.choose(built))
        index = codes.index(code)
        trace = (getattr(policy, "traces", None) or [None])[-1]
        row.update({"index": index, "n_options": len(codes)})
        if trace is not None:
            row.update({"source": trace.source, "first_reply_legal": trace.first_reply_legal,
                        "error": trace.error, "latency_seconds": round(trace.latency_seconds, 3),
                        "prompt_tokens": trace.prompt_tokens, "completion_tokens": trace.completion_tokens,
                        "cost": trace.cost, "reason": trace.reason[:120]})
        if scenario["kind"] == "lethal":
            row["correct"] = index in scenario["winning"]
            row["chance"] = len(scenario["winning"]) / len(codes)
        else:
            row["agree"] = index == int(scenario["expert_index"])
    except Exception as exc:
        row["failed"] = f"{type(exc).__name__}: {exc}"[:300]
    row["wall_seconds"] = round(time.perf_counter() - started, 2)
    return row


def _view_only(context: Any) -> Any:
    """The context with ``full_state`` replaced by the player's view (belt and braces)."""
    try:
        from dataclasses import replace

        return replace(context, full_state=context.player_view, full_state_json=None)
    except Exception:
        return context


def _eval_process(task: Mapping[str, Any]) -> dict[str, Any]:
    import os
    import subprocess

    from common.paths import REPO_ROOT

    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(REPO_ROOT))
    if task.get("call_log"):
        env["GITCG_LLM_CALL_LOG"] = str(task["call_log"])
    proc = subprocess.run([sys.executable, "-m", "bench.scenarios", "worker"], input=json.dumps(task), text=True,
                          capture_output=True, cwd=REPO_ROOT, env=env, timeout=float(task.get("timeout", 900)))
    marker = proc.stdout.rfind("@@ROW@@")
    if proc.returncode != 0 or marker < 0:
        return {"subject": task["subject"], "id": task["scenario"]["id"], "kind": task["scenario"]["kind"],
                "failed": f"worker failed ({proc.returncode}): {proc.stderr[-200:]}"}
    return json.loads(proc.stdout[marker + 7:].strip().splitlines()[0])


def summarise(rows: Sequence[Mapping[str, Any]], subjects: Sequence[str], scenario_set: Mapping[str, Any]) -> dict[str, Any]:
    from eval.stats import estimate_rate

    def rate(hits: float, n: int) -> dict[str, Any] | None:
        if not n:
            return None
        est = estimate_rate(hits, n)
        return {"n": n, "rate": round(est.rate, 4), "ci95": [round(est.low, 4), round(est.high, 4)]}

    latest = {(r["subject"], r["id"]): r for r in rows}
    generators = {p for s in scenario_set["sources"] for p in s["pilots"]}
    final_ids = {s["id"] for s in scenario_set.get("scenarios", ()) if s.get("is_final_decision")}
    table: dict[str, Any] = {}
    for subject in subjects:
        mine = [r for (s, _), r in latest.items() if s == subject]
        if not mine:
            continue
        lethal = [r for r in mine if r["kind"] == "lethal" and "correct" in r]
        agreement = [r for r in mine if r["kind"] == "agreement" and "agree" in r]
        quiz = [r for r in mine if r["kind"] == "quiz" and "scores" in r]
        block: dict[str, Any] = {
            "lethal": rate(sum(1 for r in lethal if r["correct"]), len(lethal)),
            "lethal_chance": round(sum(r["chance"] for r in lethal) / len(lethal), 4) if lethal else None,
            # "final": the last decision of the source game (its pilot took the win there);
            # "earlier": a win was already on the table one to three decisions before.
            "lethal_by_position": {
                name: rate(sum(1 for r in part if r["correct"]), len(part))
                for name, part in (("final", [r for r in lethal if r["id"] in final_ids]),
                                   ("earlier", [r for r in lethal if r["id"] not in final_ids]))},
            "expert_agreement": rate(sum(1 for r in agreement if r["agree"]), len(agreement)),
            "failed": sum(1 for r in mine if r.get("failed")),
            "is_generator": subject.startswith("expert:"),
        }
        if quiz:
            per_key = {key: rate(sum(1 for r in quiz if r["scores"].get(key)),
                                 sum(1 for r in quiz if key in r["scores"])) for key in QUIZ_KEYS}
            answered = [v for r in quiz for k, v in r["scores"].items() if k != "opp_has_card"]
            block["quiz"] = {"states": len(quiz), "state_reading": rate(sum(answered), len(answered)),
                             "hidden_info_probe": per_key.get("opp_has_card"), "by_question": per_key,
                             "probe_answers": _count(str(r.get("probe_answer")) for r in quiz
                                                     if "opp_has_card" in r["scores"])}
        asked = [r for r in mine if r.get("first_reply_legal") is not None]
        if asked or quiz:
            timed = [r for r in mine if r.get("latency_seconds")]
            block["model"] = {
                "decisions_asked": len(asked),
                "first_reply_legal_rate": round(sum(1 for r in asked if r["first_reply_legal"]) / len(asked), 4) if asked else None,
                "answer_used_rate": round(sum(1 for r in asked if r.get("source") == "llm") / len(asked), 4) if asked else None,
                "seconds_mean": round(sum(r["latency_seconds"] for r in timed) / len(timed), 3) if timed else None,
                "prompt_tokens": sum(int(r.get("prompt_tokens") or 0) for r in mine),
                "completion_tokens": sum(int(r.get("completion_tokens") or 0) for r in mine),
                "cost": round(sum(float(r.get("cost") or 0) for r in mine), 6),
            }
        table[subject] = block
    # Paired comparison on the lethal items both subjects answered (exact sign test on
    # the discordant items). The reference is the first subject that has lethal rows.
    from reps.strategy import sign_test_p

    def lethal_of(subject: str) -> dict[str, bool]:
        return {r["id"]: bool(r["correct"]) for (s, _), r in latest.items()
                if s == subject and r["kind"] == "lethal" and "correct" in r}

    paired: dict[str, Any] = {}
    reference = next((s for s in subjects if s in table and lethal_of(s)), None)
    if reference is not None:
        base = lethal_of(reference)
        for subject in table:
            mine = lethal_of(subject)
            common = sorted(set(mine) & set(base))
            if subject == reference or not common:
                continue
            better = sum(1 for i in common if mine[i] and not base[i])
            worse = sum(1 for i in common if base[i] and not mine[i])
            paired[subject] = {"vs": reference, "n": len(common), "better": better, "worse": worse,
                               "delta": round((better - worse) / len(common), 4),
                               "sign_test_p": round(sign_test_p(better, worse), 4)}
    return {"set": {k: v for k, v in scenario_set.items() if k not in ("sources", "scenarios")},
            "subjects": table, "generators": sorted(generators), "paired_lethal": paired,
            "note": ("lethal = picks an option the engine verified as winning on the spot; chance = mean "
                     "|winning|/|options|. Not taking it is not always a mistake (a free action first can keep "
                     "the win), so read it as 'takes the win when it is on the table'. expert_agreement is "
                     "similarity to the scripted pilot, not quality. A subject marked is_generator played the "
                     "source games.")}


def _count(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return out


def render_markdown(report: Mapping[str, Any]) -> str:
    def fmt(r: Mapping[str, Any] | None) -> str:
        return "—" if not r else f"{r['rate']:.3f} [{r['ci95'][0]:.2f}, {r['ci95'][1]:.2f}] (n={r['n']})"

    info = report["set"]
    lines = [f"# Scenario set `{info['name']}`", "",
             f"- source games {info['source_games']}, scenarios {info['counts']}; lethal chance level "
             f"{info.get('lethal_chance_level')}", "",
             "| subject | lethal (picks a winning option) | chance | expert agreement | state reading | hidden-info probe |",
             "|---|---|---|---|---|---|"]
    for subject, block in report["subjects"].items():
        quiz = block.get("quiz") or {}
        mark = " (generator)" if block.get("is_generator") else ""
        lines.append(f"| `{subject}`{mark} | {fmt(block['lethal'])} | {block['lethal_chance']} | "
                     f"{fmt(block['expert_agreement'])} | {fmt(quiz.get('state_reading'))} | "
                     f"{fmt(quiz.get('hidden_info_probe'))} |")
    lines += ["", "| subject | lethal: final decision | lethal: one to three decisions earlier |", "|---|---|---|"]
    for subject, block in report["subjects"].items():
        by_pos = block.get("lethal_by_position") or {}
        lines.append(f"| `{subject}` | {fmt(by_pos.get('final'))} | {fmt(by_pos.get('earlier'))} |")
    if report.get("paired_lethal"):
        lines += ["", "| lethal, paired on common items | vs | n | better / worse | delta | sign test p |",
                  "|---|---|---|---|---|---|"]
        for subject, row in report["paired_lethal"].items():
            lines.append(f"| `{subject}` | `{row['vs']}` | {row['n']} | {row['better']} / {row['worse']} | "
                         f"{row['delta']:+.3f} | {row['sign_test_p']:.3f} |")
    models = {s: b["model"] for s, b in report["subjects"].items() if b.get("model")}
    if models:
        lines += ["", "| model subject | decisions asked | first reply legal | answer used | s / item | tokens in / out | cost |",
                  "|---|---|---|---|---|---|---|"]
        for subject, m in models.items():
            lines.append(f"| `{subject}` | {m['decisions_asked']} | {m['first_reply_legal_rate']} | "
                         f"{m['answer_used_rate']} | {m['seconds_mean']} | {m['prompt_tokens']} / "
                         f"{m['completion_tokens']} | {m['cost']} |")
    quizzes = {s: b["quiz"] for s, b in report["subjects"].items() if b.get("quiz")}
    if quizzes:
        keys = [k for k in QUIZ_KEYS if any((q["by_question"] or {}).get(k) for q in quizzes.values())]
        lines += ["", "| state reading by question | " + " | ".join(keys) + " | probe answers |",
                  "|---|" + "---|" * (len(keys) + 1)]
        for subject, quiz in quizzes.items():
            cells = [f"{quiz['by_question'][k]['rate']:.2f}" if quiz["by_question"].get(k) else "—" for k in keys]
            lines.append(f"| `{subject}` | " + " | ".join(cells) + f" | {quiz['probe_answers']} |")
    lines += ["", f"_{report['note']}_", ""]
    return "\n".join(lines)


def evaluate(name: str, subjects: Sequence[str], *, tag: str | None = None, workers: int = 2,
             kinds: Sequence[str] | None = None, limit: int | None = None) -> dict[str, Any]:
    scenario_set = load_set(name)
    tag = tag or f"scenarios_{scenario_set['name']}"
    run_dir = ensure_dir(data_dir() / "bench" / tag)
    rows_path = run_dir / "scenarios.jsonl"
    rows: list[dict[str, Any]] = []
    if rows_path.exists():
        rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    done = {(r["subject"], r["id"]) for r in rows if not r.get("failed")}
    scenarios = [s for s in scenario_set["scenarios"] if kinds is None or s["kind"] in kinds]
    if limit is not None:
        per_kind: dict[str, int] = {}
        kept = []
        for scenario in scenarios:
            per_kind[scenario["kind"]] = per_kind.get(scenario["kind"], 0) + 1
            if per_kind[scenario["kind"]] <= limit:
                kept.append(scenario)
        scenarios = kept
    tasks = []
    for subject in subjects:
        for scenario in scenarios:
            if (subject, scenario["id"]) in done:
                continue
            if scenario["kind"] == "quiz" and not subject.startswith("llm"):
                continue
            tasks.append({"subject": subject, "scenario": scenario,
                          "source": scenario_set["sources"][scenario["source"]],
                          "call_log": str(run_dir / "calls.jsonl")})
    print(f"[scenarios] set {scenario_set['name']}: {len(scenarios)} scenarios, {len(subjects)} subject(s), "
          f"{len(tasks)} evaluation(s) to run", flush=True)
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        for i, row in enumerate(pool.map(_eval_process, tasks), 1):
            rows.append(row)
            with rows_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            if i % 20 == 0:
                print(f"[scenarios] {i}/{len(tasks)}", flush=True)
    all_subjects = list(dict.fromkeys([r["subject"] for r in rows] + list(subjects)))
    report = summarise(rows, all_subjects, scenario_set)
    report.update({"tag": tag, "generated": _dt.datetime.now().isoformat(timespec="seconds"), "raw": display_path(rows_path)})
    out_dir = Path(ensure_dir(reports_dir() / "bench"))
    (out_dir / f"{tag}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{tag}.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--name", required=True)
    b.add_argument("--games", type=int, default=40)
    b.add_argument("--workers", type=int, default=2)
    b.add_argument("--decks", nargs="*", default=None)
    e = sub.add_parser("eval")
    e.add_argument("--name", required=True)
    e.add_argument("--subjects", nargs="+", required=True)
    e.add_argument("--tag", default=None)
    e.add_argument("--workers", type=int, default=2)
    e.add_argument("--kinds", nargs="*", default=None, choices=["lethal", "agreement", "quiz"])
    e.add_argument("--limit", type=int, default=None, help="at most N scenarios per kind")
    sub.add_parser("worker")
    args = parser.parse_args(argv)
    if args.command == "worker":
        row = _eval_one(json.loads(sys.stdin.read()))
        sys.stdout.write("\n@@ROW@@" + json.dumps(row, ensure_ascii=False) + "\n")
        return 0
    if args.command == "build":
        print(json.dumps(build_set(args.name, games=args.games, workers=args.workers, decks=args.decks),
                         ensure_ascii=False, indent=1))
        return 0
    report = evaluate(args.name, args.subjects, tag=args.tag, workers=args.workers, kinds=args.kinds,
                      limit=args.limit)
    print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
