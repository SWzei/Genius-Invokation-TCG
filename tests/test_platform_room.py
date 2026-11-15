"""Remote seat on a genius-invokation battle platform (``envs.platform_room``, PLAN D30).

Fast tests cover the client's own logic against a small in-process HTTP server:
request shapes, the server-sent event reader, the hand-decoded ``select_option``
request, de-duplication of replayed rpcs, the wait-for-opponent bound.

The slow test plays a whole game through that server with the real engine behind
it: the server forwards the engine's protobuf notifications and requests exactly as
the platform does (base64 in JSON events) and takes the answers from HTTP posts.

Neither is the upstream server. The protocol itself was checked against a locally
built ``@gi-tcg/server`` (see ``reports/review/2026-11_platform_review.md``); to
repeat that, start one and run::

    GITCG_PLATFORM_TEST_SERVER=http://127.0.0.1:3411 pytest tests/test_platform_room.py -m slow
"""

from __future__ import annotations

import base64
import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from envs.platform_room import (
    BOT_PREFIX,
    PlatformError,
    RoomClient,
    Seat,
    _write_varint,
    encode_select_option_response,
    is_loopback,
    parse_select_option,
    play_seat,
)

ROOM = 7


def _len_delimited(field: int, payload: bytes) -> bytes:
    return bytes([(field << 3) | 2]) + _write_varint(len(payload)) + payload


def select_option_request(prompt: str, options: list[tuple[str, str]]) -> bytes:
    """A ``Request{select_option}`` as upstream ``main`` encodes it (field 6)."""
    inner = _len_delimited(1, prompt.encode())
    for key, text in options:
        inner += _len_delimited(2, _len_delimited(1, key.encode()) + _len_delimited(2, text.encode()))
    return _len_delimited(6, inner)


class _FakeRoom:
    """One room: seats, per-seat event queues, pending rpcs, optionally a real game."""

    def __init__(self, *, with_engine: bool = False, seed: int = 5, inject_select_option: bool = False,
                 replay_first_rpc: bool = False) -> None:
        self.with_engine, self.seed = with_engine, seed
        self.inject_select_option, self.replay_first_rpc = inject_select_option, replay_first_rpc
        self.seats: dict[str, dict] = {}
        self.pending: dict[int, queue.Queue] = {}
        self.posts: dict[int, int] = {}
        self.requests: list[dict] = []
        self.rpc_id = 0
        self.lock = threading.Lock()
        self.started = False
        self.winner: int | None = None
        self.select_option_answer: bytes | None = None
        self.error: str | None = None

    # -- seats ------------------------------------------------------------- #
    def add_seat(self, body: dict) -> dict:
        who = len(self.seats)
        pid = f"guest-{'ab'[who]}"
        self.seats[pid] = {"token": f"token-{who}", "who": who, "events": queue.Queue(), "deck": body["deck"],
                           "name": body["name"], "connected": False}
        return {"playerId": pid, "accessToken": f"token-{who}",
                "room": {"id": ROOM, "config": {"randomSeed": self.seed}}}

    def connect(self, pid: str) -> None:
        with self.lock:
            self.seats[pid]["connected"] = True
            ready = len(self.seats) == 2 and all(s["connected"] for s in self.seats.values())
            if ready and not self.started and self.with_engine:
                self.started = True
                threading.Thread(target=self._run, daemon=True).start()

    def _seat(self, who: int) -> dict:
        return next(s for s in self.seats.values() if s["who"] == who)

    def ask(self, who: int, raw_request: bytes, *, timeout: float = 120.0) -> bytes:
        with self.lock:
            self.rpc_id += 1
            rpc_id = self.rpc_id
            box = self.pending[rpc_id] = queue.Queue(maxsize=1)
        event = {"type": "rpc", "data": {"id": rpc_id, "timer": {"current": 300, "total": 300},
                                         "request": base64.b64encode(raw_request).decode()}}
        self._seat(who)["events"].put(event)
        if self.replay_first_rpc and rpc_id == 1:
            self._seat(who)["events"].put(event)          # what a reconnect replays
        return box.get(timeout=timeout)

    # -- the game ---------------------------------------------------------- #
    def _run(self) -> None:
        import gitcg

        gitcg.thread_initialize()              # the engine keeps a per-thread context
        try:
            from gitcg import Game
            from gitcg.proto.rpc_pb2 import Response

            from envs.match import _build_create_param
            from reps.schema import DeckSpec

            room = self

            class Wire:                     # duck-typed gitcg.Player: the three hooks the binding calls
                def __init__(self, who: int) -> None:
                    self.who = who

                def on_notify(self, notification) -> None:
                    room._seat(self.who)["events"].put(
                        {"type": "notification", "data": base64.b64encode(notification.SerializeToString()).decode()})

                def _on_rpc(self, request):
                    return Response.FromString(room.ask(self.who, request.SerializeToString()))

                def on_io_error(self, error_msg: str) -> None:
                    room.error = error_msg

            decks = [DeckSpec(name=f"seat{w}", characters=tuple(self._seat(w)["deck"]["characters"]),
                              cards=tuple(self._seat(w)["deck"]["cards"])) for w in (0, 1)]
            game = Game(create_param=_build_create_param(decks[0], decks[1], seed=self.seed))
            for who in (0, 1):
                game.set_player(who, Wire(who))
                self._seat(who)["events"].put({
                    "type": "initialized", "who": who, "config": {"randomSeed": self.seed, "actionTime": 300},
                    "profile": {"id": "test/latest"},
                    "oppPlayerInfo": {"name": self._seat(1 - who)["name"], "isGuest": True}})
            if self.inject_select_option:
                self.select_option_answer = self.ask(0, select_option_request("先手还是后手？", [("a", "先"), ("b", "后")]))
            game.start()
            while game.is_running():
                game.step()
            self.winner = game.winner()
        except Exception as exc:  # surfaced by the test through ``room.error``
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            for seat in self.seats.values():
                seat["events"].put(None)
            # No ``gitcg.thread_cleanup()`` here: the Game object is still alive in this
            # frame, and freeing it after the context is gone crashes the process.


def _handler(room: _FakeRoom):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _json(self, status: int, payload) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            size = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(size)) if size else {}

        def do_POST(self):  # noqa: N802
            body = self._body()
            room.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            parts = self.path.strip("/").split("/")
            if parts == ["api", "rooms"]:
                return self._json(201, room.add_seat(body))
            if parts == ["api", "rooms", str(ROOM), "players"]:
                if len(room.seats) >= 2:
                    return self._json(409, {"message": "room is full"})
                return self._json(201, room.add_seat(body))
            if len(parts) == 6 and parts[-1] == "actionResponse":
                seat = room.seats.get(parts[4])
                if seat is None or self.headers.get("Authorization") != f"Bearer {seat['token']}":
                    return self._json(401, {"message": "unauthorized"})
                rpc_id = int(body["id"])
                room.posts[rpc_id] = room.posts.get(rpc_id, 0) + 1
                box = room.pending.pop(rpc_id, None)
                if box is None:
                    return self._json(400, {"message": "no such pending rpc"})
                box.put(base64.b64decode(body["response"]))
                return self._json(200, {"message": "ok"})
            return self._json(404, {"message": "not found"})

        def do_GET(self):  # noqa: N802
            parts = self.path.strip("/").split("/")
            if parts == ["api", "version"]:
                return self._json(200, {"coreVersion": "test", "currentGameVersion": "v0", "supportedGameVersions": ["v0"]})
            if parts == ["api", "rooms"]:
                return self._json(200, [])
            if parts == ["api", "rooms", str(ROOM), "gameLog"]:
                return self._json(200, {"winner": room.winner})
            if len(parts) == 6 and parts[-1] == "notification":
                seat = room.seats.get(parts[4])
                if seat is None or self.headers.get("Authorization") != f"Bearer {seat['token']}":
                    return self._json(401, {"message": "unauthorized"})
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                room.connect(parts[4])

                def send(event: dict) -> None:
                    self.wfile.write(f"event: message\ndata: {json.dumps(event)}\n\n".encode())
                    self.wfile.flush()

                try:
                    send({"type": "waiting"})
                    while True:
                        try:
                            event = seat["events"].get(timeout=0.05)
                        except queue.Empty:
                            send({"type": "ping"})
                            continue
                        if event is None:
                            break
                        if event.get("type") == "raw":
                            self.wfile.write(event["bytes"])
                            self.wfile.flush()
                            continue
                        send(event)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                self.close_connection = True
                return None
            return self._json(404, {"message": "not found"})

    return Handler


@pytest.fixture
def fake_room():
    servers = []

    def make(**kwargs):
        room = _FakeRoom(**kwargs)
        server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(room))
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return room, f"http://127.0.0.1:{server.server_address[1]}"

    yield make
    for server in servers:
        server.shutdown()
        server.server_close()


DECK = {"characters": [1, 2, 3], "cards": list(range(1, 31))}


# --------------------------------------------------------------------------- #
# fast: helpers and client logic
# --------------------------------------------------------------------------- #
def test_select_option_is_decoded_and_answered_without_the_wheel_knowing_it():
    from gitcg.proto.rpc_pb2 import Request

    raw = select_option_request("选择一项", [("k1", "甲"), ("k2", "乙")])
    assert parse_select_option(raw) == {"prompt": "选择一项", "options": [{"key": "k1", "text": "甲"},
                                                                       {"key": "k2", "text": "乙"}]}
    # The installed protobuf classes parse it as "no known request" -- the reason for the hand decoder.
    # (If a newer wheel knows field 6 this assertion is what will say so.)
    assert Request.FromString(raw).WhichOneof("request") in (None, "select_option")
    assert parse_select_option(b"") is None
    assert parse_select_option(b"\xff\xff") is None                       # truncated varint: not a crash
    known = Request()
    known.choose_active.candidate_ids.extend([1, 2])
    assert parse_select_option(known.SerializeToString()) is None
    assert encode_select_option_response(0) == b"\x32\x00"                 # field 6, empty message
    assert encode_select_option_response(3) == b"\x32\x02\x08\x03"
    assert encode_select_option_response(300) == b"\x32\x03\x08\xac\x02"


def test_loopback_detection_and_bot_label():
    from scripts.platform_play import _display_name

    assert is_loopback("http://127.0.0.1:3411") and is_loopback("http://localhost:1/api")
    assert not is_loopback("https://play.piovium.org")
    assert _display_name("http://127.0.0.1:3411", "agent") == "agent"
    assert _display_name("https://play.piovium.org", "agent") == BOT_PREFIX + "agent"
    assert _display_name("https://play.piovium.org", BOT_PREFIX + "agent") == BOT_PREFIX + "agent"


def test_room_requests_have_the_documented_shape(fake_room):
    room, url = fake_room()
    client = RoomClient(url)
    assert client.base_url.endswith("/api")
    assert client.version()["coreVersion"] == "test" and client.rooms() == []
    host = client.create_room(name="a", characters=DECK["characters"], cards=DECK["cards"], seed=11,
                              profile_id="official/v7.2.0", host_first=True, action_time=45)
    guest = client.join_room(host.room_id, name="b", characters=DECK["characters"], cards=DECK["cards"])
    assert (host.room_id, host.player_id, host.token) == (ROOM, "guest-a", "token-0")
    assert guest.player_id == "guest-b"
    create, join = room.requests[0]["body"], room.requests[1]["body"]
    assert create["deck"] == DECK and create["randomSeed"] == 11 and create["profileId"] == "official/v7.2.0"
    assert create["hostFirst"] is True and create["actionTime"] == 45
    assert create["private"] is True and create["watchable"] is False and create["allowGuest"] is True
    assert set(join) == {"name", "deck"}
    assert room.requests[0]["auth"] is None                        # guests have no token before the reply
    with pytest.raises(PlatformError) as excinfo:
        client.join_room(host.room_id, name="c", characters=DECK["characters"], cards=DECK["cards"])
    assert excinfo.value.status == 409
    with pytest.raises(PlatformError) as excinfo:
        client.respond(Seat(ROOM, "guest-a", "wrong-token"), 1, b"")
    assert excinfo.value.status == 401
    with pytest.raises(PlatformError) as excinfo:
        RoomClient("http://127.0.0.1:9", timeout=2).version()      # nothing listens there
    assert excinfo.value.status is None


def test_event_stream_reader_survives_pings_comments_and_garbage(fake_room):
    room, url = fake_room()
    client = RoomClient(url)
    seat = client.create_room(name="a", characters=DECK["characters"], cards=DECK["cards"])
    events = room.seats[seat.player_id]["events"]
    events.put({"type": "raw", "bytes": b": keep-alive comment\n\n"})
    events.put({"type": "raw", "bytes": b"data: {not json}\n\n"})
    events.put({"type": "raw", "bytes": b'data: {"type": "oppRpc",\ndata: "oppPlayerStatus": 1}\n\n'})   # multi-line data
    events.put({"type": "error", "message": "boom"})
    events.put(None)
    seen = [e for e in client.events(seat) if e.get("type") != "ping"]
    assert [e["type"] for e in seen] == ["waiting", "error", "oppRpc", "error"]
    assert "unparseable" in seen[1]["message"] and seen[2]["oppPlayerStatus"] == 1 and seen[3]["message"] == "boom"


def test_waiting_for_an_opponent_is_bounded(fake_room, tmp_path):
    room, url = fake_room()
    client = RoomClient(url)
    seat = client.create_room(name="a", characters=DECK["characters"], cards=DECK["cards"])
    built = []
    started = time.perf_counter()
    result = play_seat(client, seat, lambda who: built.append(who), wait_seconds=0.3,
                       transcript=tmp_path / "t.jsonl")
    assert time.perf_counter() - started < 5
    assert result.who is None and not result.finished and result.score is None and built == []
    assert any("no opponent joined" in e for e in result.errors)
    assert [json.loads(line)["type"] for line in (tmp_path / "t.jsonl").read_text().splitlines()][0] == "waiting"


# --------------------------------------------------------------------------- #
# slow: a whole game through the wire
# --------------------------------------------------------------------------- #
def _seat_thread(client, seat, spec, deck_name, results, key, transcript):
    from common.seeding import derive_seed
    from envs.match import PolicyPlayer
    from envs.policy import build_policy

    def make_player(who: int):
        role = f"p{who}"
        return PolicyPlayer(who, build_policy(spec, seed=derive_seed(3, role, deck_name), role=role))

    results[key] = play_seat(client, seat, make_player, transcript=transcript)


@pytest.mark.slow
def test_a_whole_game_over_the_wire_matches_the_engine(fake_room, tmp_path):
    from envs.decks import deck_spec

    room, url = fake_room(with_engine=True, seed=5, inject_select_option=True, replay_first_rpc=True)
    client = RoomClient(url)
    decks = [deck_spec("natlan_battleship"), deck_spec("unyielding_geo")]
    host = client.create_room(name="a", characters=list(decks[0].characters), cards=list(decks[0].cards), seed=5)
    guest = client.join_room(host.room_id, name="b", characters=list(decks[1].characters), cards=list(decks[1].cards))
    results: dict[str, object] = {}
    threads = [
        threading.Thread(target=_seat_thread, args=(client, host, "heuristic", decks[0].name, results, "host",
                                                    tmp_path / "host.jsonl")),
        threading.Thread(target=_seat_thread, args=(client, guest, "legal_random", decks[1].name, results, "guest",
                                                    tmp_path / "guest.jsonl")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=300)
    assert room.error is None, room.error
    a, b = results["host"], results["guest"]
    assert a.finished and b.finished and a.errors == [] and b.errors == []
    assert {a.who, b.who} == {0, 1}
    assert a.winner == b.winner == room.winner                    # both streams agree with the engine
    assert a.score is not None and (a.score + b.score == 1.0 or a.score == b.score == 0.5)
    assert a.engine_fallbacks == 0 and b.engine_fallbacks == 0 and a.decisions > 5 and b.decisions > 5
    # the replayed rpc was answered once; every rpc got exactly one accepted post
    assert room.posts and set(room.posts.values()) == {1}
    assert len(a.rpc_seconds) + len(b.rpc_seconds) == len(room.posts)
    # select_option: decoded by hand, answered with the server's default (option 0)
    assert a.select_option_defaults == 1 and room.select_option_answer == encode_select_option_response(0)
    assert a.min_timer_margin is not None and a.min_timer_margin > 200
    assert a.opponent == {"name": "b", "is_guest": True} and a.room_config["randomSeed"] == 5
    # the transcript is enough to audit the seat: every answered rpc has its response and timing
    out = [json.loads(line) for line in (tmp_path / "host.jsonl").read_text().splitlines()]
    assert sum(1 for row in out if row["dir"] == "out") == len(a.rpc_seconds)
    assert all(row.get("type") != "ping" for row in out)


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("GITCG_PLATFORM_TEST_SERVER"),
                    reason="GITCG_PLATFORM_TEST_SERVER not set (a locally run @gi-tcg/server)")
def test_selfplay_against_a_real_local_server(tmp_path, monkeypatch):
    from scripts.platform_play import main

    server = os.environ["GITCG_PLATFORM_TEST_SERVER"]
    assert is_loopback(server), "this test only talks to a server on this machine"
    monkeypatch.setenv("GITCG_DATA_DIR", str(tmp_path))
    assert main(["selfplay", "--server", server, "--deck0", "natlan_battleship", "--deck1", "unyielding_geo",
                 "--policy0", "heuristic", "--policy1", "expert:<deck>", "--seed", "7", "--tag", "pytest"]) == 0
