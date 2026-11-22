"""Text retrieval over the knowledge base, and decision-level situation tests.

Character-bigram BM25 works on Chinese without word segmentation (the KB's original
``search`` split on whitespace and found nothing for a Chinese question). Used by:

* ``KnowledgeBase.search`` as the fallback when whitespace terms match nothing;
* ``KnowledgeSelector`` with ``rule_selection = "retrieve"`` -- rule sections ranked
  against the visible decision (options + public state) instead of a fixed
  option-kind map;
* ``bench.kb_qa`` (the ``bm25`` condition).

Everything here reads text the acting player can see; nothing touches the full state.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable, Sequence

_CJK_OR_WORD = re.compile(r"[一-鿿]|[A-Za-z0-9]+")


def bigrams(text: str) -> list[str]:
    """Character bigrams over CJK runs plus ASCII words; punctuation and markup dropped."""
    tokens = _CJK_OR_WORD.findall(text or "")
    grams: list[str] = []
    for a, b in zip(tokens, tokens[1:]):
        if len(a) == 1 and len(b) == 1 and "一" <= a <= "鿿" and "一" <= b <= "鿿":
            grams.append(a + b)
    grams.extend(t.lower() for t in tokens if len(t) > 1)
    return grams


class BM25:
    """Okapi BM25 over ``(key, text)`` documents, character bigrams."""

    def __init__(self, docs: Iterable[tuple[Any, str]], k1: float = 1.5, b: float = 0.75) -> None:
        pairs = list(docs)
        self.keys = [k for k, _t in pairs]
        self.docs = [Counter(bigrams(t)) for _k, t in pairs]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = sum(self.lengths) / max(1, len(self.lengths))
        df: Counter = Counter()
        for doc in self.docs:
            df.update(doc.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.k1, self.b = k1, b

    def scores(self, query: str) -> list[tuple[float, Any]]:
        terms = Counter(bigrams(query))
        out = []
        for i, doc in enumerate(self.docs):
            score = 0.0
            for term, qtf in terms.items():
                tf = doc.get(term, 0)
                if tf:
                    norm = tf + self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avg)
                    score += self.idf[term] * tf * (self.k1 + 1) / norm * (1 + math.log(qtf))
            if score > 0:
                out.append((score, self.keys[i]))
        out.sort(key=lambda row: -row[0])
        return out

    def rank(self, query: str, k: int = 3) -> list[Any]:
        return [key for _s, key in self.scores(query)[: int(k)]]


def section_index(sections: Sequence[Any], *, exclude_docs: Sequence[str] = ()) -> BM25:
    """BM25 over rule sections (heading weighted twice), skipping whole documents."""
    keep = [s for s in sections if not any(str(s.ref).startswith(d) for d in exclude_docs)]
    return BM25((s.ref, f"{s.heading} {s.heading} {s.text}") for s in keep)


# --------------------------------------------------------------------------- #
# decisions
# --------------------------------------------------------------------------- #
def decision_query(context: Any, describer: Any) -> str:
    """Visible text describing one decision: the legal options and the public state."""
    parts: list[str] = []
    try:
        parts.append(describer.options_text(context))
    except Exception:
        pass
    try:
        parts.append(describer.state_text(context, detail=False))
    except Exception:
        pass
    return "\n".join(parts)


def _players(context: Any) -> tuple[Any, Any]:
    view = context.player_view
    return view.players[context.acting_player], view.players[1 - context.acting_player]


def lethal_window(context: Any, hp_threshold: int = 5) -> bool:
    """The opponent has one character left standing, at ``hp_threshold`` HP or less --
    a state where a kill ends the game. Visible information only."""
    if context.player_view is None:
        return False
    _me, opp = _players(context)
    alive = [c for c in opp.characters if not c.defeated]
    return len(alive) == 1 and int(alive[0].health) <= int(hp_threshold)


SITUATIONS = {"lethal_window": lethal_window}


def _active(side: Any) -> Any:
    return next((c for c in side.characters if getattr(c, "is_active", False) and not c.defeated), None)


def _uses_skill(context: Any) -> bool:
    return any(getattr(getattr(spec, "kind", None), "value", "") == "action_use_skill"
               for spec in getattr(context, "legal_low_level_specs", ()) or ())


# (name, test on the visible decision, governing rule sections) -- in priority order.
# Built from the D32 training-split error analysis: the sections a position needs were
# rarely selected by option kind or by text retrieval, and the generic "a combat action
# passes the turn" (R03 §1) misled the model once the opponent had declared end.
RULE_TRIGGERS: tuple[tuple[str, Any, tuple[str, ...]], ...] = (
    ("opponent_declared_end", lambda me, opp, ctx: bool(opp.declared_end), ("R03 §3", "R01 §4.3")),
    ("opponent_attached", lambda me, opp, ctx: _active(opp) is not None and int(_active(opp).aura) != 0,
     ("R06 §2", "R06 §3.1")),
    ("summon_zone_filling", lambda me, opp, ctx: len(me.summons) >= 3, ("R07 §1",)),
    ("skill_available", lambda me, opp, ctx: _uses_skill(ctx), ("R04 §3",)),
)


def _can_declare_end(context: Any) -> bool:
    return any(getattr(getattr(spec, "kind", None), "value", "") == "action_declare_end"
               for spec in getattr(context, "legal_low_level_specs", ()) or ())


# D33 candidate: the opposite case of "opponent_declared_end". While the opponent is still
# acting, declaring end hands them the rest of the round (R01 §4.2). From D32: a model
# declared end "to win in the end phase" while the opponent could still act.
TRIGGER_SETS: dict[str, tuple[tuple[str, Any, tuple[str, ...]], ...]] = {
    "d32": RULE_TRIGGERS,
    "d33": RULE_TRIGGERS + (
        ("opponent_still_acting", lambda me, opp, ctx: not opp.declared_end and _can_declare_end(ctx), ("R01 §4.2",)),
    ),
}


def triggered_rules(context: Any, trigger_set: str = "d32") -> list[str]:
    """Rule sections whose situation holds at this decision (visible information only)."""
    if getattr(context, "player_view", None) is None:
        return []
    me, opp = _players(context)
    refs: list[str] = []
    for _name, test, sections in TRIGGER_SETS[trigger_set]:
        try:
            hit = test(me, opp, context)
        except (AttributeError, TypeError, ValueError):
            hit = False
        if hit:
            refs += [r for r in sections if r not in refs]
    return refs
