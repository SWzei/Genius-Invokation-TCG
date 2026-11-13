"""The lab: sessions, worker protocol, visibility, replay, exports, server (PLAN D29).

Real engine, no network (model seats use the built-in ``mock`` provider). Two games
are played once per module: a human-vs-model game driven over the worker protocol,
and an AI-vs-AI game with human intervention driven over the HTTP API.

Slow tests: counterfactual verification of an override, and the browser end-to-end
run (skipped when no interpreter with Playwright is available).
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import torch

from lab.session import (ALL, SeatSpec, SessionSpec, SessionStore, SpecError, list_sessions, next_seed,
                         open_session, project_event, project_events)

REPO = Path(__file__).resolve().parents[1]
DECK0, DECK1 = "natlan_battleship", "superconduct_aggro"


@pytest.fixture(scope="module")
def data_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("labdata")
    patch = pytest.MonkeyPatch()
    patch.setenv("GITCG_DATA_DIR", str(root))
    patch.delenv("GITCG_KB_DIR", raising=False)
    yield root
    patch.undo()


def _worker(store: SessionStore, driver, env=None):
    """Run a worker to the end; ``driver(event, tell)`` answers requests."""
    env = {**os.environ, **(env or {}), "PYTHONPATH": str(REPO)}
    proc = subprocess.Popen([sys.executable, "-m", "lab.worker", str(store.path)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                            cwd=str(REPO), env=env)

    def tell(command):
        proc.stdin.write(json.dumps(command) + "\n")
        proc.stdin.flush()

    events = []
    for line in proc.stdout:
        event = json.loads(line)
        events.append(event)
        driver(event, tell)
    assert proc.wait(timeout=30) == 0
    return events


@pytest.fixture(scope="module")
def human_game(data_root):
    """Seat 0 = a person (scripted here), seat 1 = a mock model. Returns (store, live events)."""
    spec = SessionSpec(DECK0, DECK1, (SeatSpec("human"), SeatSpec("policy", "llm:mock:random")), seed=7)
    store = SessionStore.create(spec)
    count = {"n": 0}

    def driver(event, tell):
        if event["type"] != "request":
            return
        count["n"] += 1
        n = count["n"]
        if n == 2:
            tell({"cmd": "advise", "policy": "heuristic"})
        if n == 3:
            tell({"cmd": "discuss", "question": "该怎么打？", "profile": "mock"})
        if n == 4:
            tell({"cmd": "act", "index": 999})                       # illegal: must be rejected, not played
        if n <= 9:
            tell({"cmd": "act", "positions": [0]} if event["request_type"] in ("reroll_dice", "switch_hands")
                 else {"cmd": "act", "index": len(event["options"]) - 1 if n == 6 else 0})
        else:
            tell({"cmd": "autopilot", "policy": f"expert:{DECK0}"})

    return store, _worker(store, driver)


# --------------------------------------------------------------------------- #
# spec, store, visibility
# --------------------------------------------------------------------------- #
def test_session_spec_rules(tmp_path):
    human, bot = SeatSpec("human"), SeatSpec("policy", "heuristic")
    with pytest.raises(SpecError, match="seed must be >= 1"):
        SessionSpec(DECK0, DECK1, (human, bot), seed=0)
    with pytest.raises(SpecError, match="requires 'reveal'"):
        SessionSpec(DECK0, DECK1, (human, bot), seed=1, intervene=True)
    spec = SessionSpec(DECK0, DECK1, (human, bot), seed=1, intervene=True, reveal=True)
    assert spec.mode == "human_vs_ai" and spec.spectate and spec.human_seats == (0,)
    assert SessionSpec(DECK0, DECK1, (bot, bot), seed=2, intervene=True).mode == "ai_vs_ai"
    assert SessionSpec.from_dict(spec.as_dict()) == spec
    store = SessionStore.create(spec, root=tmp_path)
    meta = store.meta()
    assert meta["information_clean"] is False and meta["status"] == "running" and meta["engine_lock"]
    assert SessionStore.create(SessionSpec(DECK0, DECK1, (human, bot), seed=3), root=tmp_path).meta()["information_clean"]
    assert next_seed(tmp_path) == 2 and len(list_sessions(tmp_path)) == 2
    with pytest.raises(KeyError):
        open_session("../etc", tmp_path)


def test_projection_hides_the_other_seat():
    decision = {"type": "decision", "n": 5, "seat": 1, "step": 3, "request_type": "action", "actor": "policy",
                "policy": "x", "public_text": "打出手牌【甲】", "text": "打出手牌【甲】，支付 冰冰", "index": 2,
                "state": {"me": {"hand": ["secret"]}}, "options": [{"text": "secret option"}], "detail": {"raw": "secret"}}
    public = project_event(decision, 0)
    assert set(public) == {"type", "n", "seat", "step", "request_type", "actor", "policy", "public_text"}
    assert project_event(decision, 1) == decision and project_event(decision, ALL) == decision
    for kind in ("state", "request", "proposal", "advice", "chat"):
        assert project_event({"type": kind, "seat": 1, "state": {}}, 0) is None
        assert project_event({"type": kind, "seat": 1, "state": {}}, 1) is not None
    assert project_event({"type": "end", "winner": 0}, 0) == {"type": "end", "winner": 0}
    assert len(project_events([decision, {"type": "state", "seat": 1}], 0)) == 1


# --------------------------------------------------------------------------- #
# a human-vs-model game over the worker protocol
# --------------------------------------------------------------------------- #
def test_worker_game_runs_to_the_end_and_records_everything(human_game):
    store, live = human_game
    stored = store.events()
    assert stored == live                                             # the worker is the single writer
    kinds = [e["type"] for e in stored]
    assert kinds[0] == "start" and kinds[-1] == "end" and [e["n"] for e in stored] == list(range(1, len(stored) + 1))
    end = stored[-1]
    assert end["error"] is None and end["winner"] in (0, 1) and end["seats"][1]["fallbacks"] == 0
    meta = store.meta()
    assert meta["status"] == "finished" and meta["result"]["winner"] == end["winner"]
    decisions = store.decisions()
    actors = {(d["seat"], d["actor"]) for d in decisions}
    assert (0, "human") in actors and (0, "autopilot") in actors and (1, "policy") in actors
    assert sum(1 for d in decisions if d["seat"] == 0) == end["seats"][0]["decisions"]
    # an illegal command is refused and the request stays open
    rejected = [e for e in stored if e["type"] == "rejected"]
    assert len(rejected) == 1 and rejected[0]["command"]["index"] == 999
    # advice and discussion happened on the human's own decision
    advice = next(e for e in stored if e["type"] == "advice")
    assert advice["seat"] == 0 and advice["policy"] == "heuristic" and advice["text"]
    chat = store.chat()
    assert len(chat) == 1 and chat[0]["question"] == "该怎么打？" and chat[0]["answer"] and chat[0]["seat"] == 0
    # the model seat's decisions carry its trace; its calls are logged without prompt text
    model_decision = next(d for d in decisions if d["seat"] == 1 and d["n_options"] > 1)
    assert model_decision["detail"]["kind"] == "llm" and model_decision["detail"]["source"] == "llm"
    calls = store.calls()
    assert {c["profile"] for c in calls} == {"mock:random", "mock"} and all("prompt_sha" in c for c in calls)
    assert [c["tag"] for c in calls if c["profile"] == "mock"] == ["discuss"]          # the discussion is billed too
    assert "该怎么打" not in (store.path / "calls.jsonl").read_text(encoding="utf-8")
    assert end["seats"][1]["llm"]["llm_rate"] == 1.0


def test_live_view_of_the_human_never_contains_the_model_seats_private_data(human_game):
    store, _ = human_game
    events = store.events()
    visible = project_events(events, 0)
    for event in visible:
        if event.get("seat") == 1:
            assert event["type"] == "decision" and "state" not in event and "options" not in event and "detail" not in event
    # states are only published for the human seat in a normal game
    assert {e["seat"] for e in events if e["type"] == "state"} == {0}
    # and the human's own view shows the opponent's hand as a count
    request = next(e for e in events if e["type"] == "request")
    assert "hand" not in request["state"]["opponent"] and "hand_count" in request["state"]["opponent"]
    # the model's hand card names (its own view) do not appear in what the human saw
    model_view = next(d for d in events if d["type"] == "decision" and d["seat"] == 1 and d["state"]["me"]["hand"])
    hidden = {card["name"] for card in model_view["state"]["me"]["hand"]}
    own = {card["name"] for e in events if e.get("seat") == 0 and "state" in e for card in e["state"]["me"]["hand"]}
    early = json.dumps([e for e in visible if e["n"] <= model_view["n"]], ensure_ascii=False)
    played = {d["public_text"] for d in visible if d["type"] == "decision"}
    leaked = [name for name in hidden - own if f'"{name}"' in early and not any(name in text for text in played)]
    assert leaked == []


# --------------------------------------------------------------------------- #
# replay and exports
# --------------------------------------------------------------------------- #
def test_replay_reconstructs_every_decision(human_game, tmp_path):
    from lab.replay import ReplayMismatch, replay_session

    store, _ = human_game
    replayed = replay_session(store)
    decisions = store.decisions()
    assert replayed.complete and replayed.winner == store.meta()["result"]["winner"]
    assert len(replayed.items) == len(decisions)
    for (event, built), stored in zip(replayed.items, decisions):
        context = built.context
        assert (event["seat"], event["step"]) == (stored["seat"], stored["step"]) == (context.acting_player, context.step_index)
        assert len(context.legal_low_level_codes) == stored["n_options"]
        assert str(context.legal_low_level_specs[stored["index"]].label) == stored["label"]
    # a record that no longer matches the engine is refused, not silently exported
    broken = tmp_path / "broken"
    shutil.copytree(store.path, broken)
    lines = (broken / "events.jsonl").read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        event = json.loads(line)
        if event["type"] == "decision" and event["seat"] == 0 and event["n_options"] > 2:
            event["label"] = "not what was played"
            lines[i] = json.dumps(event, ensure_ascii=False)
            break
    (broken / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ReplayMismatch):
        replay_session(SessionStore(broken))


def test_demonstrations_feed_the_existing_bc_trainer(human_game, data_root):
    from lab.replay import export_bc
    from scripts import datafirst_bc_store, datafirst_bc_train
    from scripts.train_bc_scale import _game_key

    store, _ = human_game
    decisions = store.decisions()
    out = data_root / "replays" / "lab_human"
    manifest = export_bc([store], out)
    human_steps = [d for d in decisions if d["seat"] == 0 and d["actor"] in ("human", "forced")]
    assert manifest["games"] == 1 and manifest["samples"] == len(human_steps) and manifest["encoder_config"]
    record = json.loads((out / "samples.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert (record["deck"], record["opponent"], record["seed"]) == (DECK0, DECK1, 7) and "side" not in record
    assert [s["step_index"] for s in record["samples"]] == [d["step"] for d in human_steps]
    assert [s["teacher_index"] for s in record["samples"]] == [d["index"] for d in human_steps]
    outcome = 1.0 if store.meta()["result"]["winner"] == 0 else 0.0
    assert {s["value_target"] for s in record["samples"]} == {outcome}
    with pytest.raises(FileExistsError):
        export_bc([store], out)                                       # corpora are append-only

    # whole trajectories of both seats -> store -> one epoch of the unchanged trainer
    full = data_root / "replays" / "lab_all"
    manifest = export_bc([store], full, seats="all", include_autopilot=True)
    assert manifest["games"] == 2 and manifest["samples"] == len(decisions)
    cache = data_root / "lab_all.pt"
    assert datafirst_bc_store.main(["--replays", str(full), "--store-cache", str(cache), "--seed-start", "1",
                                    "--val-every", "0"]) == 0
    payload = torch.load(cache, weights_only=False)
    assert len(payload["train"].keys) == len(decisions)
    assert set(k[:-1] for k in payload["train"].keys) == {
        _game_key({"deck": DECK0, "opponent": DECK1, "seed": 7}),
        _game_key({"deck": DECK1, "opponent": DECK0, "seed": 7, "side": 1})}
    checkpoint = data_root / "lab_bc.pt"
    assert datafirst_bc_train.main(["--store-cache", str(cache), "--d-model", "16", "--epochs", "1",
                                    "--batch-size", "32", "--out", str(checkpoint)]) == 0
    assert checkpoint.exists()
    # the same store drives the outcome-based losses too (value target = the seat's game result)
    for loss in ("pg", "awr"):
        assert datafirst_bc_train.main(["--store-cache", str(cache), "--d-model", "16", "--epochs", "1",
                                        "--batch-size", "32", "--loss", loss,
                                        "--out", str(data_root / f"lab_{loss}.pt")]) == 0

    # a game played with hidden information visible is not exported as demonstration
    unclean = SessionStore(data_root / "lab" / "unclean_copy")
    shutil.copytree(store.path, unclean.path)
    unclean.update_meta(information_clean=False)
    skipped = export_bc([unclean], data_root / "replays" / "lab_unclean")
    assert skipped["games"] == 0 and "hidden information" in skipped["skipped"][0]["reason"]
    shutil.rmtree(unclean.path)


def test_feedback_becomes_supervision_the_trainer_accepts(human_game, data_root):
    from lab.replay import export_supervision, human_signals
    from reps.strategy import DecisionSupervision, HumanSignal, read_supervision
    from scripts import datafirst_bc_train
    from train.strategy_targets import DecisionTargets, TargetSpec

    store, _ = human_game
    decisions = store.decisions()
    model_steps = [d for d in decisions if d["seat"] == 1 and d["n_options"] > 2]
    corrected, rated = model_steps[2], model_steps[4]
    better = (corrected["index"] + 1) % corrected["n_options"]
    store.add_feedback({"scope": "decision", "seat": 1, "step": corrected["step"], "rating": -1,
                        "preferred_index": better, "comment": "应该先铺场", "annotator": "tester",
                        "information_clean": True})
    store.add_feedback({"scope": "decision", "seat": 1, "step": rated["step"], "rating": 1, "comment": "好棋"})
    store.add_feedback({"scope": "game", "rating": 4, "comment": "整体不错"})
    signals = human_signals(store)
    assert signals[(1, corrected["step"])].kind == "correction"
    assert signals[(1, corrected["step"])].rejected_index == corrected["index"]
    assert signals[(1, rated["step"])].kind == "rating" and signals[(1, rated["step"])].rating == 1
    demos = [s for s in signals.values() if s.kind == "demonstration"]
    assert len(demos) == sum(1 for d in decisions if d["actor"] == "human")

    path = data_root / "lab_exports" / "t" / "supervision.jsonl"
    path.parent.mkdir(parents=True)
    report = export_supervision([store], path)
    assert report["by_kind"] == {"demonstration": len(demos), "correction": 1, "rating": 1}
    records = list(read_supervision(path))
    correction = next(r for r in records if r.human.kind == "correction")
    assert correction.store_key == (DECK1, DECK0, 7, 1, corrected["step"])
    assert correction.expert_index == corrected["index"] and correction.human.preferred_index == better
    assert correction.human.evidence_kind == "human_preference" and correction.evidence is None
    assert correction.as_dict()["human"]["comment"] == "应该先铺场" and len(correction.options) == corrected["n_options"]
    assert next(r for r in records if r.human.kind == "demonstration").human.evidence_kind == "human_demonstration"
    # additive schema: a record without a human signal serialises as before
    plain = dataclasses.replace(correction, human=None)
    assert "human" not in plain.as_dict() and DecisionSupervision.from_dict(plain.as_dict()).human is None
    assert HumanSignal.from_dict(correction.human.as_dict()) == correction.human
    with pytest.raises(ValueError):
        HumanSignal("vibes")

    # targets: only the correction is a preference; it aligns with the exported corpus by key
    cache = torch.load(data_root / "lab_all.pt", weights_only=False)
    targets = DecisionTargets.for_store(cache["train"], records, TargetSpec(mode="human"))
    assert targets.stats["targets"] == 1 and targets.stats["by_source"] == {"human_preference:correction": 1}
    assert targets.stats["mismatched_records"] == 0 and targets.stats["unmatched_records"] == 0
    assert DecisionTargets.for_store(cache["train"], records, TargetSpec(mode="evidence_gated")).stats["targets"] == 0
    unclean = [dataclasses.replace(correction, human=dataclasses.replace(correction.human, information_clean=False))]
    assert DecisionTargets.for_store(cache["train"], unclean, TargetSpec(mode="human")).stats["targets"] == 0
    report_path = data_root / "lab_human_distill.json"
    assert datafirst_bc_train.main(["--store-cache", str(data_root / "lab_all.pt"), "--d-model", "16", "--epochs", "1",
                                    "--batch-size", "32", "--supervision", str(path), "--distill-coef", "1.0",
                                    "--distill-target", "human", "--out", str(data_root / "lab_distill.pt"),
                                    "--report", str(report_path)]) == 0
    assert json.loads(report_path.read_text(encoding="utf-8"))["distill"]["targets"] == 1


def test_other_policies_can_be_asked_about_a_stored_game(human_game):
    from lab.replay import compare_policies

    store, _ = human_game
    report = compare_policies(store, ["heuristic", "llm:mock:first", f"expert:{DECK1}"], seat=1, limit=10)
    assert report["decisions"] == 10 and set(report["policies"]) == {"heuristic", "llm:mock:first", f"expert:{DECK1}"}
    assert all(row["seat"] == 1 and set(row["choices"]) == set(report["policies"]) for row in report["rows"])
    assert report["policies"]["llm:mock:first"]["llm"]["calls"] == 10
    assert len(report["pairwise"]) == 3 and all(0.0 <= p["agree"] <= 1.0 for p in report["pairwise"])
    first = report["rows"][0]["choices"]["llm:mock:first"]
    assert first["index"] == 0 and first["text"]


# --------------------------------------------------------------------------- #
# HTTP API
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def server(data_root):
    from lab.server import serve

    http, manager = serve("127.0.0.1", 0, data_root / "lab")
    threading.Thread(target=http.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{http.server_address[1]}", manager
    manager.shutdown()
    http.shutdown()


def _call(base, path, body=None, *, content_type="application/json"):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data, headers={"Content-Type": content_type} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _play(base, session_id, on_pending, *, timeout=120):
    """Poll a session to its end; ``on_pending(pending)`` returns the act body."""
    since, events, deadline = 0, [], time.time() + timeout
    handled = set()
    while time.time() < deadline:
        status, data = _call(base, f"/api/sessions/{session_id}/events?since={since}&wait=5")
        assert status == 200
        events += data["events"]
        since = max([since] + [e["n"] for e in data["events"]])
        pending = data["pending"]
        if data["status"] != "running":
            return events, data
        if pending is not None and pending["n"] not in handled:
            handled.add(pending["n"])
            body = on_pending(pending)
            if body is not None:
                assert _call(base, f"/api/sessions/{session_id}/act", body)[0] == 200
    raise AssertionError("session did not finish")


@pytest.fixture(scope="module")
def intervened_game(server):
    """AI vs AI with intervention: approve a few, override one action, then auto-approve."""
    base, manager = server
    status, meta = _call(base, "/api/sessions", {
        "deck0": DECK0, "deck1": DECK1, "seed": 21, "intervene": True, "note": "api test",
        "seats": [{"kind": "policy", "policy": "expert:<deck>"}, {"kind": "policy", "policy": "llm:mock:first"}]})
    assert status == 200 and meta["spec"]["seats"][0]["policy"] == f"expert:{DECK0}"
    state = {"proposals": 0, "override": None}

    def on_pending(pending):
        assert pending["type"] == "proposal"
        state["proposals"] += 1
        if (state["override"] is None and pending["request_type"] == "action" and pending["seat"] == 0
                and len(pending["options"]) > 2 and pending["state"]["round"] >= 2):
            other = next(o["index"] for o in pending["options"] if o["index"] != pending["proposed"])
            state["override"] = (pending["seat"], pending["step"], pending["proposed"], other)
            return {"cmd": "override", "index": other}
        return {"cmd": "approve_all"} if state["override"] is not None else {"cmd": "approve"}

    events, final = _play(base, meta["id"], on_pending)
    return meta["id"], events, final, state


def test_api_catalogue_and_validation(server):
    base, _ = server
    status, meta = _call(base, "/api/meta")
    assert status == 200 and len(meta["decks"]) == 20 and meta["next_seed"] >= 1
    assert {m["name"] for m in meta["models"]} >= {"mock", "deepseek-chat"} and all("api_key" not in m for m in meta["models"])
    assert {k["name"] for k in meta["knowledge"]} >= {"none", "rules-strategy"}
    seats = [{"kind": "policy", "policy": "heuristic"}, {"kind": "policy", "policy": "heuristic"}]
    assert _call(base, "/api/sessions", {"deck0": DECK0, "deck1": DECK1, "seed": 0, "seats": seats})[0] == 400
    assert _call(base, "/api/sessions", {"deck0": "nope", "deck1": DECK1, "seed": 1, "seats": seats})[0] == 400
    bad = [{"kind": "policy", "policy": "llm:missing-profile"}, seats[1]]
    status, error = _call(base, "/api/sessions", {"deck0": DECK0, "deck1": DECK1, "seed": 1, "seats": bad})
    assert status == 400 and "missing-profile" in error["error"]
    assert _call(base, "/api/sessions", {"deck0": DECK0, "deck1": DECK1, "seed": 1,
                                         "seats": [{"kind": "policy", "policy": "rm -rf"}, seats[1]]})[0] == 400
    # a form post from another site cannot drive the lab
    assert _call(base, "/api/sessions", {"deck0": DECK0}, content_type="text/plain")[0] == 415
    assert _call(base, "/api/sessions/unknown/events")[0] == 404
    html = urllib.request.urlopen(base + "/", timeout=10).read().decode("utf-8")
    assert "七圣召唤 实验台" in html and "/api/meta" in html


def test_api_intervention_and_review(server, intervened_game):
    base, _ = server
    session_id, events, final, state = intervened_game
    assert final["status"] == "finished" and final["result"]["error"] is None and final["viewer"] == ALL
    assert state["proposals"] >= 3 and state["override"] is not None
    seat, step, proposed, chosen = state["override"]
    status, review = _call(base, f"/api/sessions/{session_id}/review?view=all")
    assert status == 200 and review["meta"]["spec"]["intervene"] is True
    decisions = [e for e in review["events"] if e["type"] == "decision"]
    overridden = next(d for d in decisions if (d["seat"], d["step"]) == (seat, step))
    assert overridden["actor"] == "override" and overridden["index"] == chosen
    assert overridden["proposed"]["index"] == proposed
    assert sum(1 for d in decisions if d["actor"] == "override") == 1
    assert "mock:first" in review["calls"] and review["calls"]["mock:first"]["calls"] > 0
    # a single-seat review hides the other seat's options
    status, one = _call(base, f"/api/sessions/{session_id}/review?view=1")
    assert all("options" not in e for e in one["events"] if e["type"] == "decision" and e["seat"] == 0)
    assert any("options" in e for e in one["events"] if e["type"] == "decision" and e["seat"] == 1)

    # feedback: clean only when judged from the acting seat's own view
    target = next(d for d in decisions if d["seat"] == 1 and d["n_options"] > 2)
    better = (target["index"] + 1) % target["n_options"]
    body = {"seat": 1, "step": target["step"], "rating": -1, "preferred_index": better, "comment": "c"}
    status, clean = _call(base, f"/api/sessions/{session_id}/feedback", {**body, "view": "1"})
    assert status == 200 and clean["information_clean"] is True
    status, omniscient = _call(base, f"/api/sessions/{session_id}/feedback", {**body, "view": "all"})
    assert status == 200 and omniscient["information_clean"] is False
    assert _call(base, f"/api/sessions/{session_id}/feedback", {**body, "view": "0"})[0] == 403
    assert _call(base, f"/api/sessions/{session_id}/feedback", {**body, "preferred_index": 999, "view": "1"})[0] == 400
    assert _call(base, f"/api/sessions/{session_id}/feedback", {"seat": 1, "step": 99999, "rating": 1})[0] == 404
    assert _call(base, f"/api/sessions/{session_id}/feedback", {"scope": "game", "rating": 5, "comment": "ok"})[0] == 200
    # nothing can be played once the game is over
    assert _call(base, f"/api/sessions/{session_id}/act", {"cmd": "approve"})[0] == 409

    status, report = _call(base, f"/api/sessions/{session_id}/compare",
                           {"policies": ["heuristic", "expert:<deck>"], "seat": 0, "limit": 6})
    assert status == 200 and report["decisions"] == 6 and f"expert:{DECK0}" in report["policies"]
    status, exported = _call(base, "/api/export", {"kind": "bc", "sessions": [session_id], "name": "api_corrected",
                                                   "seats": "corrected"})
    assert status == 200 and exported["games"] == 1 and exported["samples"] > 0     # the seat a person corrected
    status, sup = _call(base, "/api/export", {"kind": "supervision", "sessions": [session_id], "name": "api_fb"})
    assert status == 200 and sup["by_kind"].get("override") == 1 and sup["by_kind"].get("correction") == 1
    assert _call(base, "/api/export", {"kind": "bc", "sessions": [session_id], "name": "api_corrected"})[0] == 500
    assert _call(base, "/api/export", {"kind": "bc", "sessions": [session_id], "name": "../x"})[0] in (200, 400, 500)


def test_api_human_game_keeps_the_ai_seat_private(server):
    base, _ = server
    status, meta = _call(base, "/api/sessions", {
        "deck0": DECK0, "deck1": DECK1, "seed": 22,
        "seats": [{"kind": "policy", "policy": "heuristic"}, {"kind": "human"}]})
    assert status == 200
    session_id = meta["id"]
    moves = {"n": 0}
    seen = []

    def on_pending(pending):
        assert pending["type"] == "request" and pending["seat"] == 1
        moves["n"] += 1
        if moves["n"] == 3:
            # the AI's last decision is visible only as a public action; correcting it live is refused
            status, data = _call(base, f"/api/sessions/{session_id}/events?since=0")
            ai = [e for e in data["events"] if e["type"] == "decision" and e["seat"] == 0]
            seen.extend(ai)
            body = {"seat": 0, "step": ai[-1]["step"], "rating": -1}
            assert _call(base, f"/api/sessions/{session_id}/feedback", body)[0] == 200
            assert _call(base, f"/api/sessions/{session_id}/feedback", {**body, "preferred_index": 0})[0] == 403
            assert _call(base, f"/api/sessions/{session_id}/review")[0] == 409           # no review while running
            assert _call(base, f"/api/sessions/{session_id}/act", {"cmd": "approve"})[0] == 409
            assert _call(base, f"/api/sessions/{session_id}/advise", {"policy": "expert:<deck>"})[0] == 200
            assert _call(base, f"/api/sessions/{session_id}/discuss", {"question": "?", "profile": "mock"})[0] == 200
            assert _call(base, f"/api/sessions/{session_id}/discuss", {"question": ""})[0] == 400
        if moves["n"] >= 5:
            return {"cmd": "quit"}
        return {"cmd": "act", "positions": []} if pending["request_type"] in ("reroll_dice", "switch_hands") \
            else {"cmd": "act", "index": 0}

    events, final = _play(base, session_id, on_pending)
    assert final["status"] == "aborted" and "quit" in final["result"]["error"]
    assert seen and all("options" not in e and "state" not in e and "detail" not in e for e in seen)
    assert any(e["type"] == "advice" and e["policy"] == f"expert:{DECK1}" for e in events)
    assert any(e["type"] == "chat" and e["answer"] for e in events)
    # an unfinished game has no result: it is not exported as demonstration
    status, exported = _call(base, "/api/export", {"kind": "bc", "sessions": [session_id], "name": "api_quit"})
    assert status == 200 and exported["games"] == 0 and exported["skipped"][0]["reason"] == "no game result"


# --------------------------------------------------------------------------- #
# slow: counterfactual check of an override; browser end-to-end
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_an_override_can_be_checked_by_counterfactual_rollouts(server, intervened_game, data_root):
    from lab.verify import verify_session
    from reps.strategy import read_supervision

    _, manager = server
    session_id, _, _, state = intervened_game
    seat, step, proposed, chosen = state["override"]
    out = data_root / "verified.jsonl"
    report = verify_session(manager.store(session_id), out, rollouts=2, workers=2, min_pairs=2)
    assert report["signals"] >= 1 and report["checked"] + len(report["skipped"]) >= 1
    records = list(read_supervision(out))
    checked = [r for r in records if (r.side, r.step_index) == (seat, step)]
    if checked:                       # the decision sat on a clean boundary: evidence was produced
        record = checked[0]
        assert record.human.kind == "override" and record.expert_index == chosen
        assert record.evidence.is_information_legal and record.evidence.baseline_index == chosen
        assert {c.option_index for c in record.evidence.candidates} == {chosen, proposed}
        assert all(len(c.scores) == 2 for c in record.evidence.candidates)
        assert sum(report["verdicts"].values()) == report["checked"]
    else:                             # otherwise it must be reported as skipped, never estimated
        assert any(s.get("step") == step for s in report["skipped"])


def _playwright_python():
    for candidate in (os.environ.get("GITCG_PLAYWRIGHT_PYTHON"), sys.executable, shutil.which("python3"),
                      "/usr/bin/python3"):
        if candidate and subprocess.run([candidate, "-c", "import playwright"], capture_output=True).returncode == 0:
            return candidate
    return None


@pytest.mark.slow
def test_browser_end_to_end(server, data_root):
    python = _playwright_python()
    if python is None:
        pytest.skip("no Python interpreter with Playwright (set GITCG_PLAYWRIGHT_PYTHON)")
    base, _ = server
    result = subprocess.run([python, str(REPO / "tests" / "e2e" / "lab_browser.py"), base + "/"],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["console_errors"] == [] and report["finished"] and report["human_moves"] >= 5
    assert report["advice_shown"] and report["chat_answered"] and report["feedback_saved"]
    assert report["review_decisions"] > 20 and report["compare_rows"] > 0 and report["export_ok"]
    assert report["intervene_overrides"] == 1
