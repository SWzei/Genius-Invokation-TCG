"""Seat a policy in a room of a genius-invokation battle platform (``@gi-tcg/server``).

    python -m scripts.platform_play info  --server http://127.0.0.1:3411
    python -m scripts.platform_play host  --server <url> --deck natlan_battleship --policy heuristic
    python -m scripts.platform_play join  --server <url> --room 12345 --deck unyielding_geo --policy expert:unyielding_geo
    python -m scripts.platform_play selfplay --server <url> --deck0 A --deck1 B --policy0 P --policy1 Q --seed 7

``host`` creates a private guest room, prints its id (give it to the opponent -- a
person opens ``<server>/rooms/<id>`` in a browser, or another ``join``), waits, plays,
and saves ``result.json`` + ``transcript.jsonl`` (+ ``game_log.json``) under
``<data>/platform/<tag>/``. ``selfplay`` runs a ``host`` and a ``join`` in two
processes: the end-to-end check of the protocol against a server you run yourself.

No account is created and nothing is sent to any server but the one named. On a
non-local server the player name is prefixed with "[BOT] " and the room is private
unless you say otherwise: do not seat a bot against people who have not agreed to it.
An LLM policy needs its API key in the environment as usual (``docs/howto/lab.md``).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from common.paths import REPO_ROOT, data_dir, ensure_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--server", required=True, help="platform base url, e.g. http://127.0.0.1:3411")

    def seat(p: argparse.ArgumentParser, suffix: str = "") -> None:
        p.add_argument(f"--deck{suffix}", required=True, help="script-pool deck name")
        p.add_argument(f"--policy{suffix}", required=True, help="policy spec; '<deck>' expands to the deck")

    def room(p: argparse.ArgumentParser) -> None:
        p.add_argument("--profile", default=None, help="platform rules profile, e.g. official/v7.2.0")
        p.add_argument("--seed", type=int, default=None, help="room random seed (reproducible deals)")
        p.add_argument("--host-first", choices=["yes", "no", "random"], default="random")
        p.add_argument("--action-time", type=int, default=300, help="seconds per action (server: 25..300)")
        p.add_argument("--public", action="store_true", help="list the room (default: private)")
        p.add_argument("--watchable", action="store_true")

    def output(p: argparse.ArgumentParser) -> None:
        p.add_argument("--name", default="gitcg-agent")
        p.add_argument("--tag", default="adhoc")
        p.add_argument("--policy-seed", type=int, default=1)

    p_info = sub.add_parser("info", help="server version, rules profiles, open rooms (read-only)")
    common(p_info)

    p_host = sub.add_parser("host", help="create a room and play it")
    common(p_host); seat(p_host); room(p_host); output(p_host)
    p_host.add_argument("--wait", type=float, default=600.0, help="seconds to wait for an opponent")
    p_host.add_argument("--room-file", default=None, help="write the room id here once created")

    p_join = sub.add_parser("join", help="join an existing room and play it")
    common(p_join); seat(p_join); output(p_join)
    p_join.add_argument("--room", type=int, required=True)

    p_self = sub.add_parser("selfplay", help="host + join in two processes (protocol end-to-end check)")
    common(p_self); seat(p_self, "0"); seat(p_self, "1"); room(p_self)
    p_self.add_argument("--tag", default="selfplay")
    p_self.add_argument("--policy-seed", type=int, default=1)
    p_self.add_argument("--timeout", type=float, default=3600.0)
    return parser


def _display_name(server: str, name: str) -> str:
    from envs.platform_room import BOT_PREFIX, is_loopback

    return name if is_loopback(server) or name.startswith(BOT_PREFIX.strip()) else BOT_PREFIX + name


def _play(client: Any, seat: Any, deck: str, policy_spec: str, policy_seed: int, tag: str,
          extra: dict[str, Any]) -> dict[str, Any]:
    from common.lock import load_engine_lock
    from common.seeding import derive_seed
    from envs.match import PolicyPlayer
    from envs.platform_room import play_seat
    from envs.policy import build_policy

    out_dir = ensure_dir(data_dir() / "platform" / tag / f"room{seat.room_id}-{seat.player_id[-8:]}")
    spec = policy_spec.replace("<deck>", deck)
    holder: dict[str, Any] = {}

    def make_player(who: int) -> Any:
        role = "p0" if who == 0 else "p1"
        policy = build_policy(spec, seed=derive_seed(policy_seed, role, deck), role=role)
        holder["policy"] = policy
        return PolicyPlayer(who, policy)

    result = play_seat(client, seat, make_player, transcript=out_dir / "transcript.jsonl",
                       wait_seconds=extra.pop("wait_seconds", None))
    if result.who is None and extra.get("role") == "host":
        try:
            client.delete_room(seat)          # nobody came: do not leave an empty room behind
        except Exception:
            pass
    policy = holder.get("policy")
    summary = policy.summary() if callable(getattr(policy, "summary", None)) else {}
    payload = {"server": client.base_url, "deck": deck, "policy": spec, "policy_seed": policy_seed,
               **extra, **result.as_dict(), "llm": summary, "engine_lock": load_engine_lock()}
    if result.finished:
        try:
            (out_dir / "game_log.json").write_text(json.dumps(client.game_log(seat)), encoding="utf-8")
            payload["game_log"] = "game_log.json"
        except Exception as exc:      # the log is a convenience; the transcript is the record
            payload["game_log_error"] = str(exc)[:200]
    (out_dir / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["out_dir"] = str(out_dir)
    return payload


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from envs.decks import deck_spec
    from envs.platform_room import PlatformError, RoomClient

    client = RoomClient(args.server)
    try:
        if args.command == "info":
            version = client.version()
            profiles = client.profiles()
            rooms = client.rooms()
            print(json.dumps({
                "server": client.base_url, "core_version": version.get("coreVersion"),
                "current_game_version": version.get("currentGameVersion"),
                "supported_game_versions": version.get("supportedGameVersions"),
                "revision": (version.get("revision") or {}).get("hash"),
                "revision_date": (version.get("revision") or {}).get("date"),
                "default_profile": profiles.get("defaultProfileId"),
                "profiles": [p.get("id") for p in profiles.get("profiles", [])],
                "open_rooms": len(rooms),
            }, ensure_ascii=False, indent=1))
            return 0

        if args.command == "selfplay":
            room_file = ensure_dir(data_dir() / "platform" / args.tag) / f"room-{int(time.time() * 1000)}.id"
            base = [sys.executable, "-m", "scripts.platform_play"]
            host_cmd = base + ["host", "--server", args.server, "--deck", args.deck0, "--policy", args.policy0,
                               "--tag", args.tag, "--name", "seat-a", "--host-first", args.host_first,
                               "--action-time", str(args.action_time), "--policy-seed", str(args.policy_seed),
                               "--room-file", str(room_file)]
            if args.profile:
                host_cmd += ["--profile", args.profile]
            if args.seed is not None:
                host_cmd += ["--seed", str(args.seed)]
            host = subprocess.Popen(host_cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, text=True)
            deadline = time.time() + 60
            while not room_file.exists() and host.poll() is None and time.time() < deadline:
                time.sleep(0.2)
            if not room_file.exists():
                host.kill()
                raise SystemExit("selfplay: the host did not create a room")
            room_id = room_file.read_text().strip()
            join = subprocess.Popen(base + ["join", "--server", args.server, "--room", room_id,
                                            "--deck", args.deck1, "--policy", args.policy1, "--tag", args.tag,
                                            "--name", "seat-b", "--policy-seed", str(args.policy_seed)],
                                    cwd=REPO_ROOT, stdout=subprocess.PIPE, text=True)
            outputs = []
            for proc in (host, join):
                try:
                    out, _ = proc.communicate(timeout=args.timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    out, _ = proc.communicate()
                outputs.append(out)
            room_file.unlink(missing_ok=True)
            seats = []
            for out in outputs:
                try:
                    seats.append(json.loads(out[out.index("{"):]))
                except ValueError:
                    seats.append({"error": out[-400:]})
            ok = len(seats) == 2 and all(s.get("finished") for s in seats) \
                and seats[0].get("winner") == seats[1].get("winner")
            print(json.dumps({"ok": bool(ok), "room": int(room_id), "seats": seats}, ensure_ascii=False, indent=1))
            return 0 if ok else 1

        deck = deck_spec(args.deck)
        name = _display_name(args.server, args.name)
        if args.command == "host":
            seat = client.create_room(
                name=name, characters=list(deck.characters), cards=list(deck.cards),
                profile_id=args.profile, seed=args.seed,
                host_first={"yes": True, "no": False, "random": None}[args.host_first],
                action_time=args.action_time, reroll_time=args.action_time,
                round_time=args.action_time, init_time=args.action_time,
                private=not args.public, watchable=args.watchable)
            print(f"[platform] room {seat.room_id} created on {client.base_url} "
                  f"(private={not args.public}); waiting for an opponent", file=sys.stderr, flush=True)
            if args.room_file:
                Path(args.room_file).write_text(str(seat.room_id))
            extra = {"role": "host", "seed": args.seed, "requested_profile": args.profile,
                     "wait_seconds": args.wait}
        else:
            seat = client.join_room(args.room, name=name, characters=list(deck.characters), cards=list(deck.cards))
            extra = {"role": "guest"}
        payload = _play(client, seat, args.deck, args.policy, args.policy_seed, args.tag, extra)
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 0 if payload.get("finished") else 1
    except PlatformError as exc:
        print(f"[platform] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
