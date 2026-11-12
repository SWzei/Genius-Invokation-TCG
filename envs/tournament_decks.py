"""Human tournament data -> engine-playable decks (GITCG_Data release adapter).

``GITCG_Data/release/v1.0/games/games_master.jsonl`` records 5k+ tournament games
at *outcome* level: both lineups, both 30-card lists, who started, who won, the
game version. It has **no action or state trajectories**, so it cannot supply
action labels or decision supervision. What it can supply, and what this module
exposes, is the human deck distribution: every valid deck as a ``DeckSpec`` the
engine can play, with provenance (game id, tournament, game version, the engine
version tag recorded by the dataset, quality tier, split).

Use: opponent / contestant deck pools for broad-coverage collection and
evaluation (``run_match`` accepts any ``DeckSpec``). There is no scripted expert
for these decks; pair them with ``heuristic`` / ``legal_random`` / ``neural:``
policies.

Version caveat: a deck is a list of card ids. Played under the engine's default
(latest) data it uses today's card texts, not those of its tournament version.
``TournamentDeck.engine_version`` carries the dataset's version tag so a caller
can pass it as ``run_match(..., version=...)`` when the installed engine supports
that version; this module does not assert that it does.

Locating the data: pass the release directory, or set ``GITCG_DATA_RELEASE``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence

from reps.schema import DeckSpec
from reps.strategy import Provenance

DATA_ENV = "GITCG_DATA_RELEASE"
DATA_SOURCE = "GITCG_Data/games_master"


@dataclass(frozen=True)
class TournamentDeck:
    """One side of one recorded tournament game."""

    deck_code: str
    characters: tuple[int, ...]
    cards: tuple[int, ...]
    game_version: str            # e.g. "6.1"
    engine_version: str          # dataset tag, e.g. "v6.1.0"
    won: bool | None             # None = no decisive result recorded
    started: bool | None
    provenance: Provenance

    def spec(self, name: str | None = None) -> DeckSpec:
        return DeckSpec(name=name or f"human_{self.deck_code[:10]}",
                        characters=self.characters, cards=self.cards)


def _games_path(release: str | Path | None) -> Path:
    root = Path(release or os.environ.get(DATA_ENV, ""))
    path = root / "games" / "games_master.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"games_master.jsonl not found under {str(root)!r} "
            f"(pass the release directory or set {DATA_ENV})"
        )
    return path


def iter_tournament_decks(
    release: str | Path | None = None,
    *,
    versions: Sequence[str] | None = None,
    tiers: Sequence[str] | None = None,
    splits: Sequence[str] | None = None,
) -> Iterator[TournamentDeck]:
    """Yield every *valid* deck appearance (two per game), optionally filtered."""
    release_version = Path(release or os.environ.get(DATA_ENV, "")).name
    with _games_path(release).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            game: dict[str, Any] = json.loads(line)
            if versions is not None and game.get("gameVersion") not in versions:
                continue
            if tiers is not None and game.get("qualityTier") not in tiers:
                continue
            if splits is not None and game.get("split") not in splits:
                continue
            for side in ("A", "B"):
                seat = game.get(side) or {}
                cards, lineup = seat.get("cards") or (), seat.get("lineup") or ()
                if not seat.get("deckValid") or len(cards) != 30 or len(lineup) != 3:
                    continue
                winner, starter = game.get("winner"), game.get("starter")
                yield TournamentDeck(
                    deck_code=str(seat.get("deckCode", "")),
                    characters=tuple(int(v) for v in lineup),
                    cards=tuple(int(v) for v in cards),
                    game_version=str(game.get("gameVersion", "")),
                    engine_version=str(game.get("engineVersion", "")),
                    won=(winner == side) if winner in ("A", "B") else None,
                    started=(starter == side) if starter in ("A", "B") else None,
                    provenance=Provenance(
                        source=DATA_SOURCE, version=release_version,
                        generator="envs.tournament_decks",
                        extra={"gameId": game.get("gameId"), "side": side,
                               "tournament": (game.get("tournament") or {}).get("name"),
                               "qualityTier": game.get("qualityTier"), "split": game.get("split"),
                               "evidence": "human_deck_choice_and_outcome_only"},
                    ),
                )


def unique_decks(decks: Sequence[TournamentDeck] | Iterator[TournamentDeck]) -> list[TournamentDeck]:
    """First appearance of each distinct share code, in file order."""
    seen: set[str] = set()
    out: list[TournamentDeck] = []
    for deck in decks:
        if deck.deck_code and deck.deck_code not in seen:
            seen.add(deck.deck_code)
            out.append(deck)
    return out
