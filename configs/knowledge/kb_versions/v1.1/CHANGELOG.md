# v1.1 (rules layer) — 2026-11-22

Session: https://claude.ai/code/session_01JL7PTAyxV3AauNkijoxPrA (D34). Parent: v1.0. No rule fact changed.

## Why

- D33 (`reports/review/2026-11_kb_d33.md` §3.1): R03 §2 says "+1 充能" after a normal attack or
  elemental skill without the cap stated in R04 §2; with energy already full the model answered
  "3/2" (76/84 → 37/84 correct).
- Access-layer truncation: rules are injected squashed to 420 characters. Of the sections injected on
  the 120 positions of `situ_v3`, R03 §2 (72 times, 450 chars), R04 §3 (62, 534), R06 §2 (52, 751),
  R06 §3.1 (52, 855) and R10 §2 (28, 588) are longer. R06 §2 kept only the first three rows of the
  transfer table; R06 §3.1 lost crystallize, burning, bloom and quicken; R03 §2 lost "declare end →
  first next round".

## What

| section | change |
|---|---|
| R03 §2 | rule card (≤ 270 chars) before the table; table cell "+1 充能" now says "不超过充能上限 … `R04` §2" |
| R04 §3 | rule card: charged (even dice before acting), plunging (next skill after any switch) |
| R06 §2 | rule card: all reaction pairs, aura removed after a reaction, no aura for anemo/geo, same element refreshes, cryo+dendro coexist (cryo reacts first) |
| R06 §3.1 | rule card: damage bonus and side effect of every reaction |
| R10 §2 | rule card: what both / one / neither side can see |

Every card restates facts of its own section; the tables stay unchanged below the card.

## Checks

- `validate_kb`: 0 issues (built by `python -m reps.kb_versions build v1.1`).
- Engine: `reports/bench/kb_engine_check_v11.md` (energy, first player next round, tuning,
  charged, caps, visibility); reaction card compared cell by cell with the engine-derived table of R06 §2
  (`tests/test_kb_versions.py`).
