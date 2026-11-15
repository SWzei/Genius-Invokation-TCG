"""Benchmark suites: a versioned list of *cells* every subject plays.

A suite file (TOML, ``configs/bench/``) has ``[suite]`` defaults and ``[[groups]]``.
A group crosses subject decks x opponents x seeds x sides under one rules version::

    [[groups]]
    name = "ladder"                       # report axis
    decks = ["natlan_battleship"]         # decks the subject pilots (script-pool names) ...
    human = { split = "test", version = "v6.3.0", count = 2 }   # ... and/or tournament decks
    version = ""                          # rules version ("" = the engine's default / latest)
    seeds = 1

      [[groups.opponents]]
      level = "L2"                        # ladder rung, free text
      policy = "expert:<deck>"            # '<deck>' = the opponent's own deck
      deck = "superconduct_aggro"         # pool name | "mirror" | "human" (another deck of the group)

A *cell* is ``(group, subject deck, opponent, seed, side)``. Every subject plays the
same cells on the same seeds, so any two subjects are paired game for game. Seeds
come from a block reserved for this benchmark (``BENCH_SEED_BASE``): collection and
training in this repo use small seeds (``docs/PLAYBOOK.md``), so no cell reuses a
game a learned policy may have been fitted on. Seed 0 is never used.

Human decks are the ``test`` split of the tournament deck data
(``envs.tournament_decks``): deck lists people actually registered, never used as a
collection deck pool. They have no scripted expert -- which is the point: they are
the held-out-deck axis. Pick is deterministic (sorted by share code, first ``count``
that the engine accepts under ``version``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import tomllib
except ModuleNotFoundError:  # Python <=3.10 (e.g. the cluster): tomli backport
    import tomli as tomllib  # type: ignore

from reps.schema import DeckSpec

BENCH_SEED_BASE = 7_100_001
SUITE_DIR = Path(__file__).resolve().parents[1] / "configs" / "bench"


@dataclass(frozen=True)
class Cell:
    group: str
    deck: str                 # subject deck id (pool name or "human:<code>")
    opponent: str             # opponent display name, unique within the group
    opponent_level: str
    opponent_policy: str      # spec with '<deck>' already expanded
    opponent_deck: str
    version: str
    seed: int
    side: int
    deck_kind: str = "pool"   # pool | human
    rep: int = 0              # replicate index (0 .. seeds-1); ``--replicates`` filters on it

    @property
    def key(self) -> str:
        return "|".join((self.group, self.deck, self.opponent, self.version or "default",
                         str(self.seed), str(self.side)))

    def as_dict(self) -> dict[str, Any]:
        return {"group": self.group, "deck": self.deck, "opponent": self.opponent,
                "opponent_level": self.opponent_level, "opponent_policy": self.opponent_policy,
                "opponent_deck": self.opponent_deck, "version": self.version, "seed": self.seed,
                "side": self.side, "deck_kind": self.deck_kind, "rep": self.rep}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Cell":
        return cls(**{k: raw[k] for k in ("group", "deck", "opponent", "opponent_level", "opponent_policy",
                                          "opponent_deck", "version", "seed", "side", "deck_kind")},
                   rep=int(raw.get("rep", 0)))


@dataclass
class Suite:
    name: str
    description: str
    cells: list[Cell]
    decks: dict[str, dict[str, Any]] = field(default_factory=dict)   # deck id -> {characters, cards, ...}
    source: str = ""

    @property
    def fingerprint(self) -> str:
        blob = json.dumps({"cells": [c.as_dict() for c in self.cells], "decks": self.decks},
                          sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        groups: dict[str, int] = {}
        for cell in self.cells:
            groups[cell.group] = groups.get(cell.group, 0) + 1
        return {"name": self.name, "description": self.description, "fingerprint": self.fingerprint,
                "cells": len(self.cells), "cells_by_group": groups, "source": self.source,
                "seed_base": BENCH_SEED_BASE,
                "human_decks": {k: {kk: vv for kk, vv in v.items() if kk not in ("characters", "cards")}
                                for k, v in self.decks.items() if k.startswith("human:")}}


def engine_accepts(deck: DeckSpec, version: str) -> bool:
    """Whether the installed engine can start a game with ``deck`` under ``version``."""
    from gitcg import Game

    from envs.match import _build_create_param

    try:
        Game(create_param=_build_create_param(deck, deck, seed=1, version=version or None))
        return True
    except Exception:
        return False


def resolve_deck(deck_id: str, decks: Mapping[str, Mapping[str, Any]] | None = None) -> DeckSpec:
    """A deck id of a cell -> ``DeckSpec`` (pool decks by name; others from the suite table)."""
    if decks and deck_id in decks:
        entry = decks[deck_id]
        return DeckSpec(name=deck_id.replace(":", "_"), characters=tuple(entry["characters"]),
                        cards=tuple(entry["cards"]))
    from envs.decks import deck_spec

    return deck_spec(deck_id)


def _human_decks(selector: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    from envs.tournament_decks import iter_tournament_decks, unique_decks

    version = str(selector.get("version", ""))
    split = str(selector.get("split", "test"))
    count = int(selector.get("count", 1))
    pool = [d for d in unique_decks(iter_tournament_decks(splits=[split]))
            if not version or d.engine_version == version]
    pool.sort(key=lambda d: d.deck_code)
    picked: list[tuple[str, dict[str, Any]]] = []
    lineups: set[tuple[int, ...]] = set()
    for deck in pool:
        if len(picked) >= count:
            break
        lineup = tuple(sorted(deck.characters))
        if lineup in lineups or not engine_accepts(deck.spec(), version):
            continue                       # distinct lineups only; skip what the engine cannot load
        lineups.add(lineup)
        picked.append((f"human:{deck.deck_code[:12]}", {
            "characters": list(deck.characters), "cards": list(deck.cards),
            "deck_code": deck.deck_code, "native_version": deck.engine_version, "split": split,
            "tournament": deck.provenance.extra.get("tournament"),
            "game_id": deck.provenance.extra.get("gameId")}))
    if len(picked) < count:
        raise ValueError(f"suite: only {len(picked)} of {count} human decks available for {dict(selector)}")
    return picked


def build_suite(raw: Mapping[str, Any], *, source: str = "") -> Suite:
    head = raw.get("suite") or {}
    seed_offset = int(head.get("seed_offset", 0))
    default_seeds = int(head.get("seeds", 1))
    default_sides = [int(s) for s in head.get("sides", (0, 1))]
    cells: list[Cell] = []
    decks: dict[str, dict[str, Any]] = {}
    for g_index, group in enumerate(raw.get("groups") or ()):
        name = str(group["name"])
        version = str(group.get("version", head.get("version", "")) or "")
        subject_decks: list[tuple[str, str]] = [(str(d), "pool") for d in group.get("decks", ())]
        human_ids: list[str] = []
        if group.get("human"):
            for deck_id, entry in _human_decks({**group["human"], "version": group["human"].get("version", version)}):
                decks[deck_id] = entry
                human_ids.append(deck_id)
                subject_decks.append((deck_id, "human"))
        if not subject_decks:
            raise ValueError(f"suite group {name!r}: no decks")
        seeds = int(group.get("seeds", default_seeds))
        sides = [int(s) for s in group.get("sides", default_sides)]
        for d_index, (deck_id, kind) in enumerate(subject_decks):
            for opp in group.get("opponents") or ():
                opp_deck = str(opp.get("deck", "mirror"))
                if opp_deck == "mirror":
                    opp_deck = deck_id
                elif opp_deck == "human":
                    if len(human_ids) < 2 or kind != "human":
                        raise ValueError(f"suite group {name!r}: opponent deck 'human' needs >= 2 human decks")
                    opp_deck = human_ids[(human_ids.index(deck_id) + 1) % len(human_ids)]
                policy = str(opp["policy"]).replace("<deck>", opp_deck)
                label = str(opp.get("name") or f"{opp.get('level', 'L?')}:{opp['policy']}@{opp.get('deck', 'mirror')}")
                for s in range(seeds):
                    # one seed per (group, deck, replicate): opponents of a deck share it
                    seed = BENCH_SEED_BASE + seed_offset + 10_000 * g_index + 100 * d_index + s
                    for side in sides:
                        cells.append(Cell(name, deck_id, label, str(opp.get("level", "")), policy, opp_deck,
                                          version, seed, side, kind, s))
    keys = [c.key for c in cells]
    if len(set(keys)) != len(keys):
        raise ValueError("suite: duplicate cells (opponent names must be unique within a group)")
    return Suite(str(head.get("name", "suite")), str(head.get("description", "")), cells, decks, source)


def lock_path(toml_path: Path) -> Path:
    return toml_path.with_suffix(".lock.json")


def suite_to_lock(suite: Suite) -> dict[str, Any]:
    return {"format": "bench.suite.lock/1", "name": suite.name, "description": suite.description,
            "source": suite.source, "fingerprint": suite.fingerprint,
            "cells": [c.as_dict() for c in suite.cells], "decks": suite.decks}


def suite_from_lock(raw: Mapping[str, Any], *, source: str = "") -> Suite:
    suite = Suite(str(raw["name"]), str(raw.get("description", "")),
                  [Cell.from_dict(c) for c in raw["cells"]], dict(raw.get("decks") or {}), source)
    if raw.get("fingerprint") and raw["fingerprint"] != suite.fingerprint:
        raise ValueError(f"suite lock {source!r}: fingerprint {suite.fingerprint} does not match the recorded "
                         f"{raw['fingerprint']} (file edited by hand?)")
    return suite


def load_suite(name_or_path: str, *, use_lock: bool = True) -> Suite:
    """Load a suite. A ``<name>.lock.json`` next to the TOML (written by ``python -m
    bench.suite freeze``) pins the resolved cells and human deck lists, so the suite
    is identical on every machine and needs no tournament data to load."""
    path = Path(name_or_path)
    if not path.exists():
        path = SUITE_DIR / f"{name_or_path}.toml"
    if path.suffix == ".json":
        return suite_from_lock(json.loads(path.read_text(encoding="utf-8")), source=path.name)
    lock = lock_path(path)
    if use_lock and lock.exists():
        return suite_from_lock(json.loads(lock.read_text(encoding="utf-8")), source=lock.name)
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    return build_suite(raw, source=str(path.name))


def subject_applies(spec: str, cell: Cell) -> bool:
    """A deck-scripted subject (``expert:<deck>``) has no script for a human deck."""
    return not (cell.deck_kind == "human" and spec.startswith("expert:"))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Show or freeze benchmark suites.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("show", "freeze"):
        cmd = sub.add_parser(name)
        cmd.add_argument("suites", nargs="+")
    args = parser.parse_args(argv)
    for name in args.suites:
        path = Path(name) if Path(name).exists() else SUITE_DIR / f"{name}.toml"
        if args.command == "freeze":
            # Rebuild from the TOML (needs the tournament deck data for human decks) and pin it.
            suite = load_suite(str(path), use_lock=False)
            lock_path(path).write_text(json.dumps(suite_to_lock(suite), ensure_ascii=False, indent=1) + "\n",
                                       encoding="utf-8")
        else:
            suite = load_suite(str(path))
        print(json.dumps(suite.as_dict(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
