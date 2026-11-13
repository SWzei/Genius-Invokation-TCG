"""Web server of the lab (standard library only).

    python -m lab.server --port 8780          # then open http://127.0.0.1:8780/

One worker process per running session (``lab.worker``); this process only routes
commands, filters events by what the viewer may see, and stores feedback. It binds
to 127.0.0.1 by default: policy specs sent by the page are executed locally
(``neural:<path>`` loads a checkpoint file), so do not expose it to an untrusted
network.

API (JSON)::

    GET  /api/meta                         decks, policy presets, model + knowledge profiles
    GET  /api/sessions                     stored sessions (newest first)
    POST /api/sessions                     create + start a session
    GET  /api/sessions/<id>/events         ?since=<n>&wait=<seconds>&view=<0|1|all>
    POST /api/sessions/<id>/act            human move / approve / override / autopilot / quit
    POST /api/sessions/<id>/advise         ask a policy for its move at the pending decision
    POST /api/sessions/<id>/discuss        ask a model about the pending decision
    POST /api/sessions/<id>/feedback       rating / correction / comment (decision or game)
    GET  /api/sessions/<id>/review         everything stored, for replay (finished sessions)
    POST /api/sessions/<id>/compare        what other policies would have played
    POST /api/export                       BC corpus / supervision file from sessions
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from common.paths import REPO_ROOT

from .session import (ALL, SeatSpec, SessionSpec, SessionStore, SpecError, lab_dir, list_sessions,
                      next_seed, open_session, project_event, project_events)

STATIC = Path(__file__).parent / "static"
_MAX_WAIT = 20.0
_MAX_BODY = 1 << 20


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class LiveSession:
    """A running worker and the events it has produced so far."""

    def __init__(self, store: SessionStore, spec: SessionSpec, env: Mapping[str, str]) -> None:
        self.store, self.spec = store, spec
        self.events: list[dict[str, Any]] = []
        self.cond = threading.Condition()
        self.done = False
        self._stdin_lock = threading.Lock()
        self._log = (store.path / "worker.log").open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "lab.worker", str(store.path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
            cwd=str(REPO_ROOT), env=dict(env), text=True, encoding="utf-8")
        threading.Thread(target=self._read, name=f"lab-{store.id}", daemon=True).start()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            with self.cond:
                self.events.append(event)
                self.cond.notify_all()
        self.proc.wait()
        with self.cond:
            self.done = True
            self.cond.notify_all()
        self._log.close()
        meta = self.store.meta()
        if meta.get("status") == "running":      # the worker died without closing the record
            self.store.update_meta(status="error", result={"error": f"worker exited ({self.proc.returncode})"})

    @property
    def viewer(self) -> int | str:
        return ALL if self.spec.spectate else self.spec.human_seats[0]

    def pending(self) -> dict[str, Any] | None:
        """The request / proposal that is waiting for an answer, if any."""
        with self.cond:
            for event in reversed(self.events):
                kind = event.get("type")
                if kind in ("decision", "end", "error"):
                    return None
                if kind in ("request", "proposal"):
                    return event
        return None

    def command(self, command: Mapping[str, Any]) -> None:
        if self.done or self.proc.stdin is None:
            raise ApiError("the session is not running", 409)
        with self._stdin_lock:
            try:
                self.proc.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise ApiError(f"the session is not running ({exc})", 409) from exc

    def wait_events(self, since: int, wait: float) -> list[dict[str, Any]]:
        with self.cond:
            if wait > 0 and not self.done and not any(int(e.get("n", 0)) > since for e in self.events):
                self.cond.wait(timeout=min(wait, _MAX_WAIT))
            return [e for e in self.events if int(e.get("n", 0)) > since]

    def stop(self) -> None:
        if self.proc.poll() is None:
            try:
                self.command({"cmd": "quit"})
            except ApiError:
                pass
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class LabManager:
    def __init__(self, root: str | Path | None = None, *, env: Mapping[str, str] | None = None) -> None:
        self.root = lab_dir(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.env = dict(os.environ if env is None else env)
        self.env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + self.env.get("PYTHONPATH", "")
        self.live: dict[str, LiveSession] = {}
        self._lock = threading.Lock()

    # -- catalogue ---------------------------------------------------------------- #
    def meta(self) -> dict[str, Any]:
        from common.llm_providers import load_profiles, profile_status
        from common.paths import data_dir
        from eval.opponents import scripted_opponents
        from reps.knowledge import KB_ENV
        from reps.knowledge_pack import load_knowledge_profiles

        decks = [{"slug": o.deck, "name": o.display} for o in scripted_opponents()]
        checkpoints = sorted(str(p) for p in (data_dir() / "checkpoints").glob("*.pt")) \
            if (data_dir() / "checkpoints").exists() else []
        errors = []
        models: list[dict[str, Any]] = []
        knowledge: list[dict[str, Any]] = []
        try:
            models = [profile_status(p) for p in load_profiles().values()]
        except Exception as exc:          # a broken config file must not hide the page
            errors.append(f"models config: {exc}")
        try:
            knowledge = [p.as_dict() for p in load_knowledge_profiles().values()]
        except Exception as exc:
            errors.append(f"knowledge config: {exc}")
        kb_root = os.environ.get(KB_ENV, "")
        return {
            "decks": decks,
            "policies": [{"spec": "expert:<deck>", "label": "脚本专家（本牌组）"},
                         {"spec": "heuristic", "label": "启发式"},
                         {"spec": "legal_random", "label": "随机合法"}]
            + [{"spec": f"neural:{path}#t=0", "label": f"网络 {Path(path).name}"} for path in checkpoints],
            "models": models, "knowledge": knowledge,
            "kb": {"env": KB_ENV, "root": kb_root,
                   "available": bool(kb_root) and (Path(kb_root) / "data" / "derived").exists()},
            "next_seed": next_seed(self.root), "errors": errors,
        }

    # -- sessions ----------------------------------------------------------------- #
    def create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        from envs.decks import deck_spec

        try:
            seats = []
            for index, raw in enumerate(payload.get("seats") or ()):
                kind = str(raw.get("kind", "policy"))
                policy = str(raw.get("policy") or "heuristic").replace(
                    "<deck>", str(payload.get(f"deck{index}", "")))
                seats.append(SeatSpec(kind=kind, policy=policy))
            spec = SessionSpec(
                deck0=str(payload["deck0"]), deck1=str(payload["deck1"]), seats=tuple(seats),  # type: ignore[arg-type]
                # No seed = pick an unused one; an explicit 0 is an error, not "no seed".
                seed=next_seed(self.root) if payload.get("seed") is None else int(payload["seed"]),
                intervene=bool(payload.get("intervene", False)), reveal=bool(payload.get("reveal", False)),
                note=str(payload.get("note", ""))[:500])
            deck_spec(spec.deck0), deck_spec(spec.deck1)
            for seat in spec.seats:
                if not seat.is_human:
                    _check_policy_spec(seat.policy)
        except (SpecError, KeyError, ValueError, TypeError) as exc:
            raise ApiError(f"invalid session: {exc}") from exc
        store = SessionStore.create(spec, root=self.root)
        with self._lock:
            self.live[store.id] = LiveSession(store, spec, self.env)
        return store.meta()

    def get_live(self, session_id: str) -> LiveSession | None:
        with self._lock:
            return self.live.get(session_id)

    def store(self, session_id: str) -> SessionStore:
        try:
            return open_session(session_id, self.root)
        except KeyError as exc:
            raise ApiError(str(exc), 404) from exc

    def events(self, session_id: str, since: int, wait: float, view: str | None) -> dict[str, Any]:
        store = self.store(session_id)
        live = self.get_live(session_id)
        if live is not None and not live.done:
            viewer = live.viewer
            if viewer == ALL and view in ("0", "1"):
                viewer = int(view)          # a spectator may narrow the view, never widen it
            events = project_events(live.wait_events(since, wait), viewer)
            pending = live.pending()
            pending = project_event(pending, viewer) if pending is not None else None
            return {"id": session_id, "status": "running", "viewer": viewer, "events": events,
                    "pending": pending, "spec": live.spec.as_dict(), "result": None}
        meta = store.meta()
        viewer = int(view) if view in ("0", "1") else ALL       # the game is over: review is open
        events = project_events([e for e in store.events() if int(e.get("n", 0)) > since], viewer)
        return {"id": session_id, "status": meta.get("status"), "viewer": viewer, "events": events,
                "pending": None, "spec": meta.get("spec"), "result": meta.get("result")}

    def act(self, session_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        live = self.get_live(session_id)
        if live is None or live.done:
            raise ApiError("the session is not running", 409)
        command = str(payload.get("cmd", "act"))
        if command not in ("act", "approve", "approve_all", "override", "autopilot", "quit"):
            raise ApiError(f"unknown command {command!r}")
        pending = live.pending()
        if command != "quit" and pending is None:
            raise ApiError("no decision is waiting for input", 409)
        if pending is not None:
            expected = "request" if command in ("act", "autopilot") else "proposal"
            if command != "quit" and pending["type"] != expected:
                raise ApiError(f"{command!r} does not apply to a pending {pending['type']}", 409)
        body = {"cmd": command}
        for key in ("index", "positions", "policy"):
            if payload.get(key) is not None:
                body[key] = payload[key]
        if command == "autopilot":
            _check_policy_spec(str(body.get("policy") or "heuristic"))
        live.command(body)
        return {"ok": True}

    def side_request(self, session_id: str, kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        live = self.get_live(session_id)
        if live is None or live.done or live.pending() is None:
            raise ApiError("advice and discussion need a decision that is waiting for input", 409)
        if kind == "advise":
            spec = str(payload.get("policy") or "heuristic").replace(
                "<deck>", live.spec.deck(int(live.pending()["seat"])))  # type: ignore[index]
            _check_policy_spec(spec)
            live.command({"cmd": "advise", "policy": spec})
        else:
            question = str(payload.get("question") or "").strip()
            if not question:
                raise ApiError("empty question")
            live.command({"cmd": "discuss", "question": question[:2000],
                          "profile": str(payload.get("profile") or "mock"),
                          "kb": payload.get("kb") or None,
                          "history": list(payload.get("history") or ())[-8:]})
        return {"ok": True}

    def feedback(self, session_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        store = self.store(session_id)
        live = self.get_live(session_id)
        running = live is not None and not live.done
        scope = str(payload.get("scope", "decision"))
        comment = str(payload.get("comment", ""))[:2000]
        annotator = str(payload.get("annotator", ""))[:80]
        try:
            rating = int(payload.get("rating") or 0)
        except (TypeError, ValueError) as exc:
            raise ApiError("rating must be an integer") from exc
        if scope == "game":
            return store.add_feedback({"scope": "game", "rating": rating, "comment": comment,
                                       "annotator": annotator})
        try:
            seat, step = int(payload["seat"]), int(payload["step"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError("decision feedback needs 'seat' and 'step'") from exc
        decision = next((d for d in store.decisions() if int(d["seat"]) == seat and int(d["step"]) == step), None)
        if decision is None:
            raise ApiError("no such decision", 404)
        preferred = payload.get("preferred_index")
        view = str(payload.get("view", ALL))
        viewer: int | str = live.viewer if running else (int(view) if view in ("0", "1") else ALL)  # type: ignore[union-attr]
        if preferred is not None:
            if viewer != ALL and viewer != seat:
                raise ApiError("the options of that decision are not visible from this view; "
                               "rate it now and correct it in the post-game review", 403)
            try:
                preferred = int(preferred)
            except (TypeError, ValueError) as exc:
                raise ApiError("preferred_index must be an integer") from exc
            if not 0 <= preferred < int(decision["n_options"]):
                raise ApiError("preferred_index is not one of that decision's options")
        # Clean = the annotator judged the decision with the acting seat's information
        # and nothing more (a single-seat view of that seat).
        clean = viewer == seat
        return store.add_feedback({"scope": "decision", "seat": seat, "step": step, "rating": rating,
                                   "preferred_index": preferred, "comment": comment,
                                   "annotator": annotator, "view": viewer, "information_clean": clean,
                                   "live": running})

    def review(self, session_id: str, view: str | None) -> dict[str, Any]:
        store = self.store(session_id)
        live = self.get_live(session_id)
        if live is not None and not live.done:
            raise ApiError("the game is still running; review opens when it ends", 409)
        viewer: int | str = int(view) if view in ("0", "1") else ALL
        meta = store.meta()
        return {"meta": meta, "viewer": viewer, "events": project_events(store.events(), viewer),
                "feedback": store.feedback(), "chat": store.chat(),
                "calls": _summarise_calls(store.calls())}

    def tool(self, *args: str, timeout: float = 900.0) -> dict[str, Any]:
        """Run ``lab.export`` in its own process (the engine must not run in this one)."""
        proc = subprocess.run([sys.executable, "-m", "lab.export", "--root", str(self.root), *args],
                              cwd=str(REPO_ROOT), env=self.env, capture_output=True, text=True,
                              encoding="utf-8", timeout=timeout)
        if proc.returncode != 0:
            raise ApiError((proc.stderr or proc.stdout).strip().splitlines()[-1][:500]
                           if (proc.stderr or proc.stdout).strip() else "tool failed", 500)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def shutdown(self) -> None:
        with self._lock:
            sessions = list(self.live.values())
        for live in sessions:
            live.stop()


def _check_policy_spec(spec: str) -> None:
    """Reject specs that cannot be built, without building them (no engine in this process)."""
    spec = spec.strip()
    if spec.startswith(("llm:", "llm-assist:")):
        from agents.llm_policy import parse_llm_spec
        from common.llm_providers import get_profile
        from reps.knowledge_pack import get_knowledge_profile

        try:
            name, options = parse_llm_spec(spec.split(":", 1)[1])
            get_profile(name)
            get_knowledge_profile(options.get("kb"))
        except Exception as exc:
            raise ApiError(f"policy {spec!r}: {exc}") from exc
        if "fallback" in options:
            _check_policy_spec(options["fallback"])
        if "base" in options:
            _check_policy_spec(options["base"])
        return
    if spec.startswith("neural:"):
        path = spec.split(":", 1)[1].split("#", 1)[0]
        if not Path(path).exists():
            raise ApiError(f"policy {spec!r}: checkpoint not found")
        return
    if spec.startswith("expert:"):
        from envs.decks import deck_spec

        try:
            deck_spec(spec.split(":", 1)[1])
        except Exception as exc:
            raise ApiError(f"policy {spec!r}: unknown deck") from exc
        return
    if spec not in ("heuristic", "legal_random", "random"):
        raise ApiError(f"unknown policy spec {spec!r}")


def _summarise_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for call in calls:
        row = out.setdefault(call.get("profile", "?"), {"calls": 0, "errors": 0, "prompt_tokens": 0,
                                                         "completion_tokens": 0, "seconds": 0.0, "cost": 0.0,
                                                         "cost_known": True, "by_error": {}})
        row["calls"] += 1
        row["prompt_tokens"] += int(call.get("prompt_tokens", 0))
        row["completion_tokens"] += int(call.get("completion_tokens", 0))
        row["seconds"] = round(row["seconds"] + float(call.get("latency_seconds", 0.0)), 3)
        if call.get("cost") is None:
            row["cost_known"] = False
        else:
            row["cost"] = round(row["cost"] + float(call["cost"]), 6)
        if not call.get("ok"):
            row["errors"] += 1
            kind = str(call.get("error"))
            row["by_error"][kind] = row["by_error"].get(kind, 0) + 1
    return out


def make_handler(manager: LabManager) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "gitcg-lab/1"

        def log_message(self, format: str, *args: Any) -> None:  # quiet by default
            if os.environ.get("GITCG_LAB_ACCESS_LOG"):
                super().log_message(format, *args)

        def _send(self, status: int, payload: Any, content_type: str = "application/json; charset=utf-8") -> None:
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length > _MAX_BODY:
                raise ApiError("request body too large", 413)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except ValueError as exc:
                raise ApiError("request body is not JSON") from exc
            if not isinstance(payload, dict):
                raise ApiError("request body must be a JSON object")
            return payload

        def _route(self, method: str) -> None:
            url = urlparse(self.path)
            query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            parts = [p for p in url.path.split("/") if p]
            try:
                if method == "GET" and not parts:
                    return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                if parts[:1] != ["api"]:
                    raise ApiError("not found", 404)
                if parts == ["api", "meta"] and method == "GET":
                    return self._send(200, manager.meta())
                if parts == ["api", "sessions"]:
                    if method == "GET":
                        return self._send(200, {"sessions": list_sessions(manager.root)})
                    return self._send(200, manager.create(self._body()))
                if parts == ["api", "export"] and method == "POST":
                    return self._send(200, _export(manager, self._body()))
                if len(parts) == 4 and parts[1] == "sessions":
                    session_id, action = parts[2], parts[3]
                    if method == "GET" and action == "events":
                        return self._send(200, manager.events(session_id, int(query.get("since", 0)),
                                                              float(query.get("wait", 0)), query.get("view")))
                    if method == "GET" and action == "review":
                        return self._send(200, manager.review(session_id, query.get("view")))
                    if method == "POST" and action == "act":
                        return self._send(200, manager.act(session_id, self._body()))
                    if method == "POST" and action in ("advise", "discuss"):
                        return self._send(200, manager.side_request(session_id, action, self._body()))
                    if method == "POST" and action == "feedback":
                        return self._send(200, manager.feedback(session_id, self._body()))
                    if method == "POST" and action == "compare":
                        body = self._body()
                        specs = [str(s) for s in body.get("policies") or ()][:6]
                        if not specs:
                            raise ApiError("give at least one policy spec")
                        store = manager.store(session_id)
                        deck_by_seat = store.spec()
                        seat = body.get("seat")
                        specs = [s.replace("<deck>", deck_by_seat.deck(int(seat or 0))) for s in specs]
                        for spec in specs:
                            _check_policy_spec(spec)
                        args = ["compare", session_id, "--policies", *specs]
                        if seat is not None:
                            args += ["--seat", str(int(seat))]
                        if body.get("limit"):
                            args += ["--limit", str(int(body["limit"]))]
                        return self._send(200, manager.tool(*args))
                raise ApiError("not found", 404)
            except ApiError as exc:
                self._send(exc.status, {"error": str(exc)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:  # never take the server down for one request
                self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

        def do_GET(self) -> None:  # noqa: N802
            self._route("GET")

        def do_POST(self) -> None:  # noqa: N802
            # Cross-site forms cannot set this header: a page on another origin
            # cannot drive the local lab through the browser.
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                return self._send(415, {"error": "Content-Type must be application/json"})
            self._route("POST")

    return Handler


def _export(manager: LabManager, body: Mapping[str, Any]) -> dict[str, Any]:
    sessions = [str(s) for s in body.get("sessions") or ()]
    if not sessions:
        raise ApiError("select at least one session")
    for session_id in sessions:
        manager.store(session_id)
    kind = str(body.get("kind", "bc"))
    name = "".join(c for c in str(body.get("name") or "") if c.isalnum() or c in "-_")
    if not name:
        raise ApiError("give the export a name (letters, digits, - and _)")
    if kind == "bc":
        args = ["bc", "--tag", name, "--seats", str(body.get("seats", "human")), "--sessions", *sessions]
        if body.get("include_autopilot"):
            args.append("--include-autopilot")
        if body.get("include_unclean"):
            args.append("--include-unclean")
    elif kind == "supervision":
        args = ["supervision", "--name", name, "--sessions", *sessions]
    else:
        raise ApiError(f"unknown export kind {kind!r}")
    return manager.tool(*args)


def serve(host: str = "127.0.0.1", port: int = 8780, root: str | Path | None = None) -> tuple[ThreadingHTTPServer, LabManager]:
    manager = LabManager(root)
    server = ThreadingHTTPServer((host, int(port)), make_handler(manager))
    server.daemon_threads = True
    return server, manager


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--root", default=None, help="session directory (default: <data>/lab)")
    args = parser.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"[warn] binding to {args.host}: anyone who can reach this port can run local policy "
              "specs and spend your model budget", file=sys.stderr)
    server, manager = serve(args.host, args.port, args.root)
    print(f"lab: http://{args.host}:{server.server_address[1]}/  (sessions in {manager.root})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        manager.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
