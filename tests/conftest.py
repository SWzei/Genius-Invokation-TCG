"""Shared pytest fixtures / path setup for genshin-GITCG.

The repo is used as a flat collection of top-level packages (``envs``, ``reps``,
``agents`` ...). ``pyproject.toml`` already adds the repo root to ``sys.path``;
this file keeps that working when pytest is invoked from elsewhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def npc_overlay_available() -> bool:
    """True when the engine overlay with the PvE NPC characters (3102, ...) is installed.

    The stock ``gitcg`` wheel aborts on unknown character ids, so slow NPC tests that
    play an NPC deck must skip without it (D35: three slow tests failed in the cloud)."""
    from functools import lru_cache

    @lru_cache(maxsize=1)
    def _probe() -> bool:
        try:
            from gitcg import Game

            from envs.decks import DeckSpec, expert_deck_specs
            from envs.match import _build_create_param

            base = expert_deck_specs()[0]
            base_spec = DeckSpec(name=base.name, characters=base.characters, cards=base.cards)
            npc = DeckSpec(name="npc_probe", characters=(3102, 3102, 3102), cards=base.cards)
            Game(create_param=_build_create_param(base_spec, npc, seed=3))
            return True
        except Exception:  # noqa: BLE001 - the stock engine aborts on NPC ids
            return False

    return _probe()
