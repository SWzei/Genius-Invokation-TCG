"""Run one lab session: engine loop, seat policies, and the event stream.

The game runs through the ordinary ``gitcg`` binding and ``envs.match.PolicyPlayer``
-- the same path as collection and evaluation -- so a lab game is an ordinary game.
What this module adds is the conversation around each decision:

* a **human seat** asks the channel for a choice and may ask for advice (another
  policy's move on the human's own view), start a discussion with a model, hand the
  rest of the game to a policy (autopilot) or quit;
* a **policy seat** plays its policy; with ``intervene`` it first shows its proposal
  and waits for approval or an override;
* every decision is emitted as an event that carries the acting seat's view, the
  legal options, what was played, by whom, and the policy's own account of it (LLM
  trace or network top-k).

The channel is two callables (``send(event)``, ``recv() -> command``) so the same
code serves the worker process (stdio) and in-process tests (queues).

Information boundary: a seat's events are built from that seat's ``player_view``
only. Advice and discussion at a human's decision use the human's view. Who may
*read* which event is enforced by ``lab.session.project_event``.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Mapping

from common.seeding import derive_seed
from reps.describe import DecisionDescriber, find_mask_option

from .session import SessionSpec

Send = Callable[[Mapping[str, Any]], None]
Recv = Callable[[], Mapping[str, Any]]


def explain_policy(policy: Any, built: Any, describer: DecisionDescriber, *, top_k: int = 5) -> dict[str, Any]:
    """The policy's own account of the decision it just made (best effort, never raises)."""
    try:
        traces = getattr(policy, "traces", None)
        if traces:                                   # agents.llm_policy.LLMPolicy
            return {"kind": "llm", **traces[-1].as_dict()}
        interventions = getattr(policy, "interventions", None)
        if interventions is not None:                # agents.llm_assist.LLMAssistPolicy
            last = interventions[-1].as_dict() if interventions else {}
            return {"kind": "llm_assist", **last}
        model, encoder = getattr(policy, "model", None), getattr(policy, "encoder", None)
        if model is not None and encoder is not None:    # agents.neural.NeuralPolicy
            import torch

            from train.model import collate

            observation = encoder.encode_context(built.context, history=(), include_training_targets=False)
            if not observation.option_features:
                return {"kind": "neural"}
            tokens, token_mask, options, option_mask = collate([observation])
            with torch.no_grad():
                logits, value = model(tokens, token_mask, options, option_mask)
            probs = torch.softmax(logits[0], dim=-1).tolist()
            specs = built.context.legal_low_level_specs
            ranked = sorted(range(len(specs)), key=lambda i: -probs[i])[:top_k]
            return {"kind": "neural", "value": round(float(value.item()), 4),
                    "top": [{"index": i, "prob": round(float(probs[i]), 4),
                             "text": describer.option(built.context, specs[i], i)["text"]} for i in ranked]}
    except Exception as exc:  # explanation is optional; the decision already stands
        return {"kind": "unavailable", "error": f"{type(exc).__name__}: {exc}"}
    return {"kind": "scripted"}


class _Seat:
    def __init__(self, game: "LabGame", seat: int) -> None:
        self.game = game
        self.seat = int(seat)
        self.name = f"lab:p{seat}"

    # -- shared ----------------------------------------------------------------- #
    def _frame(self, built: Any) -> dict[str, Any]:
        context = built.context
        describer = self.game.describer
        return {"seat": self.seat, "step": int(context.step_index),
                "request_type": context.request_type.value,
                "state": describer.state(context), "options": describer.options(context)}

    def _emit_decision(self, built: Any, frame: Mapping[str, Any], index: int, *, actor: str,
                       policy: str, detail: Mapping[str, Any] | None = None,
                       proposed: Mapping[str, Any] | None = None) -> int:
        option = frame["options"][index]
        spec = built.context.legal_low_level_specs[index]
        self.game.send({
            "type": "decision", **frame, "index": int(index), "n_options": len(frame["options"]),
            "label": str(spec.label), "text": option["text"], "public_text": option["public_text"],
            "actor": actor, "policy": policy, "detail": dict(detail or {}),
            "proposed": dict(proposed) if proposed else None,
        })
        return int(built.context.legal_low_level_codes[index])

    def _resolve(self, built: Any, command: Mapping[str, Any]) -> int | None:
        """Option index named by an ``act`` / ``override`` command, or ``None`` if invalid."""
        count = len(built.context.legal_low_level_codes)
        if command.get("positions") is not None:
            try:
                return find_mask_option(built.context, [int(p) for p in command["positions"]])
            except (TypeError, ValueError):
                return None
        try:
            index = int(command.get("index"))
        except (TypeError, ValueError):
            return None
        return index if 0 <= index < count else None

    def _side_request(self, built: Any, frame: Mapping[str, Any], command: Mapping[str, Any]) -> bool:
        """Handle ``advise`` / ``discuss``; True when the command was one of them."""
        kind = command.get("cmd")
        base = {"seat": self.seat, "step": frame["step"]}
        if kind == "advise":
            spec = str(command.get("policy") or "heuristic")
            try:
                from envs.policy import build_policy

                adviser = self.game.advisers.get(spec)
                if adviser is None:
                    adviser = self.game.advisers[spec] = build_policy(
                        spec, seed=derive_seed(self.game.spec.seed, f"advise{self.seat}", spec),
                        role=f"advise{self.seat}")
                code = int(adviser.choose(built))
                codes = [int(c) for c in built.context.legal_low_level_codes]
                index = codes.index(code)
                self.game.send({"type": "advice", **base, "policy": spec, "index": index,
                                "text": frame["options"][index]["text"],
                                "detail": explain_policy(adviser, built, self.game.describer)})
            except Exception as exc:
                self.game.send({"type": "advice", **base, "policy": spec, "index": None,
                                "error": f"{type(exc).__name__}: {exc}"})
            return True
        if kind == "discuss":
            question = str(command.get("question") or "").strip()
            profile = str(command.get("profile") or "mock")
            row: dict[str, Any] = {"type": "chat", **base, "profile": profile,
                                   "kb": command.get("kb") or "none", "question": question}
            try:
                from agents.llm_policy import discuss
                from common.llm_providers import build_client
                from reps.knowledge_pack import KnowledgeSelector, get_knowledge_profile

                client = self.game.clients.get(profile)
                if client is None:
                    client = self.game.clients[profile] = build_client(profile)
                knowledge = get_knowledge_profile(command.get("kb"))
                selector = KnowledgeSelector(knowledge) if knowledge.enabled else None
                result, pack = discuss(client, built, question, describer=self.game.describer,
                                       selector=selector, history=command.get("history") or ())
                row.update({"answer": result.text, "error": result.error, "knowledge": pack,
                            "usage": result.as_dict()})
            except Exception as exc:
                row.update({"answer": None, "error": f"{type(exc).__name__}: {exc}"})
            self.game.send(row)
            return True
        return False


class HumanSeat(_Seat):
    """A seat played over the channel."""

    def __init__(self, game: "LabGame", seat: int) -> None:
        super().__init__(game, seat)
        self.autopilot: Any = None
        self.autopilot_spec = ""

    def choose(self, built: Any) -> int:
        from agents.human import HumanQuit

        frame = self._frame(built)
        codes = [int(c) for c in built.context.legal_low_level_codes]
        if self.autopilot is not None:
            return self._auto(built, frame)
        if len(codes) == 1:
            return self._emit_decision(built, frame, 0, actor="forced", policy="human")
        self.game.send({"type": "request", **frame})
        while True:
            command = self.game.recv()
            kind = command.get("cmd")
            if kind == "quit":
                raise HumanQuit("human quit")
            if kind == "autopilot":
                from envs.policy import build_policy

                self.autopilot_spec = str(command.get("policy") or "heuristic")
                self.autopilot = build_policy(
                    self.autopilot_spec, seed=derive_seed(self.game.spec.seed, f"auto{self.seat}"),
                    role=f"auto{self.seat}")
                return self._auto(built, frame)
            if self._side_request(built, frame, command):
                continue
            if kind == "act":
                index = self._resolve(built, command)
                if index is not None:
                    return self._emit_decision(built, frame, index, actor="human", policy="human")
            self.game.send({"type": "rejected", "seat": self.seat, "step": frame["step"],
                            "command": dict(command), "reason": "not a legal choice for this decision"})

    def _auto(self, built: Any, frame: Mapping[str, Any]) -> int:
        codes = [int(c) for c in built.context.legal_low_level_codes]
        try:
            code = int(self.autopilot.choose(built))
        except Exception:
            code = codes[0]
        index = codes.index(code) if code in codes else 0
        return self._emit_decision(built, frame, index, actor="autopilot",
                                   policy=self.autopilot_spec,
                                   detail=explain_policy(self.autopilot, built, self.game.describer))


class PolicySeat(_Seat):
    """A seat played by a policy, optionally gated by human approval."""

    def __init__(self, game: "LabGame", seat: int, policy: Any, spec: str) -> None:
        super().__init__(game, seat)
        self.policy = policy
        self.spec = spec

    def choose(self, built: Any) -> int:
        from agents.human import HumanQuit

        frame = self._frame(built)
        codes = [int(c) for c in built.context.legal_low_level_codes]
        error = None
        try:
            code = int(self.policy.choose(built))
        except Exception as exc:
            code, error = codes[0], f"{type(exc).__name__}: {exc}"
        if code not in codes:
            code, error = codes[0], error or "policy returned an illegal code"
        index = codes.index(code)
        detail = explain_policy(self.policy, built, self.game.describer)
        if error:
            detail = {**detail, "policy_error": error}
        if not self.game.spec.intervene or len(codes) == 1:
            return self._emit_decision(built, frame, index, actor="policy", policy=self.spec, detail=detail)
        self.game.send({"type": "proposal", **frame, "proposed": index, "detail": detail,
                        "policy": self.spec})
        while True:
            command = self.game.recv()
            kind = command.get("cmd")
            if kind == "quit":
                raise HumanQuit("experiment stopped")
            if kind == "approve":
                return self._emit_decision(built, frame, index, actor="policy", policy=self.spec, detail=detail)
            if kind == "approve_all":           # stop asking for the rest of the game
                self.game.spec = _without_intervene(self.game.spec)
                return self._emit_decision(built, frame, index, actor="policy", policy=self.spec, detail=detail)
            if self._side_request(built, frame, command):
                continue
            if kind == "override":
                chosen = self._resolve(built, command)
                if chosen is not None:
                    actor = "policy" if chosen == index else "override"
                    proposed = None if chosen == index else {
                        "index": index, "text": frame["options"][index]["text"]}
                    return self._emit_decision(built, frame, chosen, actor=actor, policy=self.spec,
                                               detail=detail, proposed=proposed)
            self.game.send({"type": "rejected", "seat": self.seat, "step": frame["step"],
                            "command": dict(command), "reason": "not a legal choice for this decision"})


def _without_intervene(spec: SessionSpec) -> SessionSpec:
    from dataclasses import replace

    return replace(spec, intervene=False)


class LabGame:
    """One session, played to the end over a channel."""

    def __init__(self, spec: SessionSpec, send: Send, recv: Recv, *,
                 describer: DecisionDescriber | None = None, max_steps: int = 5000) -> None:
        self.spec = spec
        self._send, self.recv = send, recv
        self.describer = describer or DecisionDescriber()
        self.max_steps = int(max_steps)
        self.advisers: dict[str, Any] = {}
        self.clients: dict[str, Any] = {}
        self._n = 0

    def send(self, event: Mapping[str, Any]) -> None:
        self._n += 1
        self._send({"n": self._n, "t": round(time.time(), 3), **event})

    def run(self) -> dict[str, Any]:
        from gitcg import Game, GameStatus

        from envs.decks import deck_spec
        from envs.match import PolicyPlayer, _build_create_param
        from envs.policy import build_policy
        from reps.snapshot import snapshot_notification
        from reps.action_hierarchy import reset_default_hierarchical_action_codebook

        spec = self.spec
        seats: list[Any] = []
        for index, seat in enumerate(spec.seats):
            if seat.is_human:
                seats.append(HumanSeat(self, index))
            else:
                role = f"p{index}"
                policy = build_policy(seat.policy, seed=derive_seed(spec.seed, role, spec.deck(index)), role=role)
                seats.append(PolicySeat(self, index, policy, seat.policy))
        decks = [deck_spec(spec.deck0), deck_spec(spec.deck1)]
        self.send({"type": "start", "spec": spec.as_dict(),
                   "decks": [{"name": d.name,
                              "characters": [self.describer.assets.name(c) for c in d.characters]}
                             for d in decks]})

        reset_default_hierarchical_action_codebook()
        game = Game(create_param=_build_create_param(decks[0], decks[1], seed=int(spec.seed), version=None))
        players = [PolicyPlayer(i, seats[i]) for i in (0, 1)]
        game.set_player(0, players[0])
        game.set_player(1, players[1])
        watched = (0, 1) if spec.spectate else spec.human_seats
        last_view: dict[int, str] = {}

        def publish_views() -> None:
            for seat in watched:
                notification = players[seat].notification
                if notification is None:
                    continue
                state = self.describer.view(snapshot_notification(notification), seat)
                encoded = json.dumps(state, ensure_ascii=False, sort_keys=True)
                if last_view.get(seat) != encoded:
                    last_view[seat] = encoded
                    self.send({"type": "state", "seat": seat, "state": state})

        started = time.perf_counter()
        error: str | None = None
        truncated = False
        quit_by: int | None = None
        steps = 0
        try:
            game.start()
            while game.is_running():
                if steps >= self.max_steps:
                    truncated = True
                    break
                game.step()
                steps += 1
                publish_views()
                quit_by = next((p.who for p in players if p.quit_requested), None)
                if quit_by is not None:
                    break
        except Exception as exc:  # engine / IO failures are otherwise swallowed by cffi
            error = f"{type(exc).__name__}: {exc}"
        winner, rounds = None, 0
        try:
            winner, rounds = game.winner(), int(game.round_number())
            if game.status() == GameStatus.ABORTED and error is None:
                error = f"aborted: {game.error()}"
        except Exception:
            pass
        if quit_by is not None:
            error, winner = f"quit: P{quit_by}", None

        def seat_summary(index: int) -> dict[str, Any]:
            seat, player = seats[index], players[index]
            out: dict[str, Any] = {"decisions": player.decisions, "fallbacks": player.fallbacks,
                                   "io_errors": list(player.io_errors),
                                   "policy": "human" if spec.seats[index].is_human else spec.seats[index].policy}
            summary = getattr(getattr(seat, "policy", None), "summary", None)
            if callable(summary):
                out["llm"] = summary()
            return out

        end = {"type": "end", "winner": winner, "rounds": rounds, "error": error,
               "truncated": truncated, "steps": steps,
               "wall_seconds": round(time.perf_counter() - started, 2),
               "seats": [seat_summary(0), seat_summary(1)]}
        self.send(end)
        return end
