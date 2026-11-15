"""Play on a genius-invokation battle platform (``@gi-tcg/server``) as a remote seat.

The upstream project runs a public platform (https://play.piovium.org) on the same
rules core this repo binds through ``gitcg``. Its HTTP API lets a seat

* create or join a room -- as a guest, with an inline deck, no account needed;
* read ``GET /api/rooms/<room>/players/<player>/notification`` -- a server-sent
  event stream of ``waiting`` / ``initialized`` / ``notification`` / ``rpc`` /
  ``oppRpc`` / ``error`` / ``ping``; ``notification.data`` and ``rpc.data.request``
  are base64 protobuf (``Notification`` / ``Request`` of ``proto/``);
* answer with ``POST .../actionResponse`` ``{"id": n, "response": <base64 Response>}``.

Those are the same messages the in-process engine hands to a ``gitcg.Player``, so
:class:`envs.match.PolicyPlayer` -- and therefore every policy spec of
``envs.policy.build_policy`` -- plays a remote room unchanged. The seat only ever
receives what the server sends this player: there is no full state on this path.

What this module does *not* do: it never creates an account, and it only talks to
the server you name. Running a bot against people on a public service needs their
consent and the maintainers'; see ``docs/howto/platform.md``.

Protocol notes (verified against upstream ``ce9e06c``, 2026-11-12):

* the stream replays ``initialized`` and the pending ``rpc`` on every (re)connect,
  so a dropped connection is resumed by reconnecting and de-duplicating rpc ids;
* a seat that does not answer within the room's timers is played by the server
  (declare end / first candidate), and a guest is forfeited after three such
  timeouts in a row -- slow policies need a room created with generous timers;
* upstream ``main`` added a sixth request kind, ``select_option`` (free-form
  option prompt), after the ``gitcg 0.21.0`` wheel was cut. The installed protobuf
  classes do not know it; it is decoded by hand here and answered with option 0
  (the server's own timeout default), and counted in the result.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

_LOOPBACK = ("127.0.0.1", "localhost", "::1", "[::1]")
BOT_PREFIX = "[BOT] "
_SELECT_OPTION_FIELD = 6          # Request.select_option / Response.select_option


class PlatformError(RuntimeError):
    """An HTTP-level failure talking to the platform (``status`` may be ``None``)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def is_loopback(base_url: str) -> bool:
    host = urllib.parse.urlsplit(base_url).hostname or ""
    return host in _LOOPBACK or host.startswith("127.")


# --------------------------------------------------------------------------- #
# minimal protobuf helpers (only for the request kind the wheel does not know)
# --------------------------------------------------------------------------- #
def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7


def _fields(data: bytes) -> Iterator[tuple[int, int, Any]]:
    """Yield ``(field number, wire type, value)`` of one protobuf message."""
    pos = 0
    while pos < len(data):
        key, pos = _read_varint(data, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _read_varint(data, pos)
        elif wire == 2:
            size, pos = _read_varint(data, pos)
            value, pos = data[pos:pos + size], pos + size
        elif wire == 1:
            value, pos = data[pos:pos + 8], pos + 8
        elif wire == 5:
            value, pos = data[pos:pos + 4], pos + 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        yield number, wire, value


def _write_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def parse_select_option(raw_request: bytes) -> dict[str, Any] | None:
    """``{"prompt", "options": [{"key", "text"}]}`` when ``raw_request`` is a
    ``select_option`` request, else ``None``."""
    try:
        top = list(_fields(raw_request))
    except (IndexError, ValueError):
        return None
    for number, wire, value in top:
        if number == _SELECT_OPTION_FIELD and wire == 2:
            prompt, options = "", []
            for sub_number, sub_wire, sub_value in _fields(value):
                if sub_number == 1 and sub_wire == 2:
                    prompt = sub_value.decode("utf-8", "replace")
                elif sub_number == 2 and sub_wire == 2:
                    option = {"key": "", "text": ""}
                    for o_number, o_wire, o_value in _fields(sub_value):
                        if o_wire == 2 and o_number in (1, 2):
                            option["key" if o_number == 1 else "text"] = o_value.decode("utf-8", "replace")
                    options.append(option)
            return {"prompt": prompt, "options": options}
    return None


def encode_select_option_response(selected_index: int) -> bytes:
    inner = b"" if int(selected_index) == 0 else b"\x08" + _write_varint(int(selected_index))
    return bytes([(_SELECT_OPTION_FIELD << 3) | 2]) + _write_varint(len(inner)) + inner


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
@dataclass
class Seat:
    """One seat's credentials in a room."""

    room_id: int
    player_id: str
    token: str
    room: dict[str, Any] = field(default_factory=dict)


class RoomClient:
    """Thin client for the room API. Standard library only."""

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/api"):
            self.base_url += "/api"
        self.timeout = float(timeout)
        handlers: list[Any] = []
        if is_loopback(self.base_url):
            handlers.append(urllib.request.ProxyHandler({}))    # never proxy loopback
        self._opener = urllib.request.build_opener(*handlers)

    # -- plumbing -------------------------------------------------------------- #
    def _open(self, method: str, path: str, *, token: str | None = None,
              body: Mapping[str, Any] | None = None, stream: bool = False):
        headers = {"Accept": "text/event-stream" if stream else "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            return self._opener.open(request, timeout=None if stream else self.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise PlatformError(f"{method} {path} -> HTTP {exc.code}: {detail}", exc.code) from None
        except (urllib.error.URLError, OSError) as exc:
            raise PlatformError(f"{method} {path} failed: {getattr(exc, 'reason', exc)}") from None

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        with self._open(method, path, **kwargs) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else None

    # -- read-only ------------------------------------------------------------- #
    def version(self) -> dict[str, Any]:
        return self._json("GET", "/version")

    def profiles(self) -> dict[str, Any]:
        return self._json("GET", "/profiles")

    def rooms(self) -> list[dict[str, Any]]:
        return self._json("GET", "/rooms")

    def room(self, room_id: int, *, token: str | None = None) -> dict[str, Any]:
        return self._json("GET", f"/rooms/{int(room_id)}", token=token)

    def game_log(self, seat: Seat) -> Any:
        """The finished game's state log (only for a seat of the room, or a watchable room)."""
        return self._json("GET", f"/rooms/{seat.room_id}/gameLog", token=seat.token)

    # -- seats ----------------------------------------------------------------- #
    def create_room(self, *, name: str, characters: list[int], cards: list[int],
                    profile_id: str | None = None, seed: int | None = None,
                    host_first: bool | None = None, action_time: int = 300, reroll_time: int = 300,
                    round_time: int = 300, init_time: int = 300, private: bool = True,
                    watchable: bool = False) -> Seat:
        """Create a room as a guest. Timers default to the maximum the server accepts
        (a policy that calls a model needs them); ``private`` rooms are not listed."""
        body: dict[str, Any] = {
            "name": name, "deck": {"characters": list(characters), "cards": list(cards)},
            "actionTime": int(action_time), "rerollTime": int(reroll_time),
            "roundTotalActionTime": int(round_time), "initTotalActionTime": int(init_time),
            "private": bool(private), "watchable": bool(watchable), "allowGuest": True,
        }
        if profile_id:
            body["profileId"] = profile_id
        if seed is not None:
            body["randomSeed"] = int(seed)
        if host_first is not None:
            body["hostFirst"] = bool(host_first)
        reply = self._json("POST", "/rooms", body=body)
        room = reply.get("room") or {}
        return Seat(int(room["id"]), str(reply["playerId"]), str(reply["accessToken"]), room)

    def join_room(self, room_id: int, *, name: str, characters: list[int], cards: list[int]) -> Seat:
        reply = self._json("POST", f"/rooms/{int(room_id)}/players",
                           body={"name": name, "deck": {"characters": list(characters), "cards": list(cards)}})
        return Seat(int(room_id), str(reply["playerId"]), str(reply["accessToken"]))

    def give_up(self, seat: Seat) -> None:
        self._json("POST", f"/rooms/{seat.room_id}/players/{seat.player_id}/giveUp", token=seat.token)

    def delete_room(self, seat: Seat) -> None:
        self._json("DELETE", f"/rooms/{seat.room_id}", token=seat.token)

    def respond(self, seat: Seat, rpc_id: int, response: bytes) -> None:
        self._json("POST", f"/rooms/{seat.room_id}/players/{seat.player_id}/actionResponse",
                   token=seat.token,
                   body={"id": int(rpc_id), "response": base64.b64encode(response).decode("ascii")})

    def events(self, seat: Seat) -> Iterator[dict[str, Any]]:
        """Server-sent events of ``seat`` until the server closes the stream."""
        with self._open("GET", f"/rooms/{seat.room_id}/players/{seat.player_id}/notification",
                        token=seat.token, stream=True) as response:
            data_lines: list[str] = []
            for raw in response:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                elif not line and data_lines:
                    payload, data_lines = "\n".join(data_lines), []
                    try:
                        yield json.loads(payload)
                    except ValueError:
                        yield {"type": "error", "message": f"unparseable event: {payload[:120]}"}


# --------------------------------------------------------------------------- #
# playing a seat
# --------------------------------------------------------------------------- #
@dataclass
class RemoteGameResult:
    room_id: int
    player_id: str
    who: int | None = None
    winner: int | None = None             # 0 / 1; None = draw or unknown
    finished: bool = False                # the game reached GAME_END on our stream
    score: float | None = None            # 1 win / 0 loss / 0.5 draw, from this seat
    rounds: int = 0
    decisions: int = 0
    engine_fallbacks: int = 0             # PolicyPlayer fell back (policy raised / illegal code)
    select_option_defaults: int = 0       # select_option requests answered with option 0
    rpc_seconds: list[float] = field(default_factory=list)   # request seen -> response accepted
    min_timer_margin: float | None = None  # smallest (server timer - our answer time), seconds
    reconnects: int = 0
    errors: list[str] = field(default_factory=list)
    profile: dict[str, Any] = field(default_factory=dict)
    room_config: dict[str, Any] = field(default_factory=dict)
    opponent: dict[str, Any] = field(default_factory=dict)
    wall_seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        seconds = sorted(self.rpc_seconds)
        return {
            "room_id": self.room_id, "player_id": self.player_id, "who": self.who,
            "winner": self.winner, "finished": self.finished, "score": self.score,
            "rounds": self.rounds, "decisions": self.decisions,
            "engine_fallbacks": self.engine_fallbacks,
            "select_option_defaults": self.select_option_defaults,
            "rpc_count": len(seconds),
            "rpc_seconds_median": round(seconds[len(seconds) // 2], 3) if seconds else None,
            "rpc_seconds_max": round(seconds[-1], 3) if seconds else None,
            "min_timer_margin": self.min_timer_margin, "reconnects": self.reconnects,
            "errors": self.errors[:20], "profile": self.profile, "room_config": self.room_config,
            "opponent": self.opponent, "wall_seconds": round(self.wall_seconds, 2),
        }


def play_seat(
    client: RoomClient,
    seat: Seat,
    make_player: Callable[[int], Any],
    *,
    transcript: str | Path | None = None,
    max_reconnects: int = 5,
    wait_seconds: float | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> RemoteGameResult:
    """Play ``seat`` to the end of the game.

    ``make_player(who)`` builds the ``gitcg.Player`` once the server says which
    side this seat got (typically ``PolicyPlayer(who, policy)``). ``transcript``
    appends every event received and every response sent (JSON lines, base64
    payloads as received) -- enough to re-run the policy offline on exactly what
    it saw. ``wait_seconds`` bounds the wait for an opponent (checked on every
    event; the server pings every 10 s). One game per process: the action codebook
    is process-global.
    """
    from gitcg.proto.notification_pb2 import Notification
    from gitcg.proto.rpc_pb2 import Request

    from reps.action_hierarchy import reset_default_hierarchical_action_codebook

    reset_default_hierarchical_action_codebook()
    result = RemoteGameResult(seat.room_id, seat.player_id)
    started = time.perf_counter()
    player: Any = None
    answered: set[int] = set()
    waited_out = False
    log = Path(transcript).open("a", encoding="utf-8") if transcript else None

    def record(kind: str, payload: Mapping[str, Any]) -> None:
        if log is not None:
            log.write(json.dumps({"t": round(time.time(), 3), "dir": kind, **payload}, ensure_ascii=False) + "\n")
            log.flush()

    try:
        while True:
            try:
                for event in client.events(seat):
                    kind = event.get("type")
                    if kind != "ping":
                        record("in", event)
                    if on_event is not None:
                        on_event(event)
                    if player is None and wait_seconds is not None \
                            and time.perf_counter() - started > wait_seconds and kind != "initialized":
                        result.errors.append(f"no opponent joined within {wait_seconds:.0f}s")
                        waited_out = True
                        break
                    if kind == "initialized":
                        result.who = int(event["who"])
                        result.profile = dict(event.get("profile") or {})
                        result.room_config = {k: v for k, v in (event.get("config") or {}).items()
                                              if k != "profile"}
                        opp = event.get("oppPlayerInfo") or {}
                        result.opponent = {"name": opp.get("name"), "is_guest": opp.get("isGuest")}
                        if player is None:
                            player = make_player(result.who)
                    elif kind == "notification":
                        notification = Notification.FromString(base64.b64decode(event["data"]))
                        if player is not None:
                            player.on_notify(notification)
                        state = notification.state
                        result.rounds = max(result.rounds, int(state.round_number))
                        if int(state.phase) == 5:            # PHASE_TYPE_GAME_END
                            result.finished = True
                            result.winner = int(state.winner) if state.HasField("winner") else None
                    elif kind == "rpc":
                        data = event.get("data")
                        if not data or int(data["id"]) in answered or player is None:
                            continue
                        rpc_id = int(data["id"])
                        seen = time.perf_counter()
                        raw = base64.b64decode(data["request"])
                        request = Request.FromString(raw)
                        if request.WhichOneof("request") is None:
                            option = parse_select_option(raw)
                            if option is None:
                                result.errors.append(f"rpc {rpc_id}: unknown request kind")
                                continue
                            result.select_option_defaults += 1
                            response = encode_select_option_response(0)
                        else:
                            response = player._on_rpc(request).SerializeToString()
                        try:
                            client.respond(seat, rpc_id, response)
                        except PlatformError as exc:
                            # 4xx: the server already resolved this rpc (timeout) or rejected the reply.
                            result.errors.append(f"rpc {rpc_id}: {exc}")
                            if exc.status is None:
                                raise
                        answered.add(rpc_id)
                        spent = time.perf_counter() - seen
                        result.rpc_seconds.append(spent)
                        timer = data.get("timer") or {}
                        if timer.get("current") is not None:
                            margin = float(timer["current"]) - spent
                            result.min_timer_margin = margin if result.min_timer_margin is None \
                                else min(result.min_timer_margin, margin)
                        record("out", {"id": rpc_id, "response": base64.b64encode(response).decode("ascii"),
                                       "seconds": round(spent, 3)})
                    elif kind == "error":
                        result.errors.append(str(event.get("message"))[:300])
                break                                    # the server closed the stream (or we gave up waiting)
            except PlatformError as exc:
                if exc.status is not None or result.finished or result.reconnects >= max_reconnects:
                    if not result.finished:
                        result.errors.append(str(exc)[:300])
                    break
                result.reconnects += 1
                time.sleep(min(10.0, 1.5 * result.reconnects))
            except (ConnectionError, TimeoutError, OSError) as exc:
                if result.finished or result.reconnects >= max_reconnects:
                    if not result.finished:
                        result.errors.append(f"stream: {exc}"[:300])
                    break
                result.reconnects += 1
                time.sleep(min(10.0, 1.5 * result.reconnects))
    finally:
        if log is not None:
            log.close()
    if player is not None:
        result.decisions = int(getattr(player, "decisions", 0))
        result.engine_fallbacks = int(getattr(player, "fallbacks", 0))
        result.errors.extend(f"io: {e}"[:300] for e in getattr(player, "io_errors", []))
    if result.finished and result.who is not None:
        result.score = 0.5 if result.winner is None else (1.0 if result.winner == result.who else 0.0)
    result.wall_seconds = time.perf_counter() - started
    return result
