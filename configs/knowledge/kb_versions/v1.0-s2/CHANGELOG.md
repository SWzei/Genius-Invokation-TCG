# v1.0-s2 (strategy layer, D36 round 1) — 2026-11-23

Session: https://claude.ai/code/session_01JL7PTAyxV3AauNkijoxPrA (D36). Parent: v1.0. Rule sections unchanged.

## Evidence (train only)

- D36 train (`mirror_train` pairs 20–49, `elements=1` both sides, v1.0 vs no KB, 0.467):
  knowledge side ends the round with >= 3 dice and a usable skill 1.58 / 100 actions vs 0.82 (games
  where it happens: knowledge score 0.24 vs 0.63); skips an available burst 1.67 vs 0.48.
- D34 train, both sides pooled: winners use more skills per round (normal 0.93 vs 0.79, skill 0.52 vs
  0.45, burst 0.29 vs 0.22) and leave fewer dice at round end (1.22 vs 1.49).
- D35 targeted check on train positions: knowledge versions play cards on ~0.40 of action answers vs
  0.32–0.34 without knowledge, and normal-attack less (0.29 vs 0.33–0.35); s1's S02-P7 cut "end with
  dice" from 1.72 to 0.43 / 100 (null gap 0.43); s1's S01-P9 raised skipped bursts (2.16 vs 1.51).

## What

| change | content |
|---|---|
| new S02-P8 | attack first: by default use a skill each action turn; play a card first only for more damage this turn, to save a character, or when it must be played |
| kept from s1 | S02-P7 (no early end with usable dice), S09-P4 (full zone only), S07-P4 (no drawing at >= 9 cards), S01-P2 (dice vanish; no initiative after the opponent ended) |
| dropped | S01-P9 (backfired in the targeted check) |

Detectors: `reps/knowledge.py` `_VERSION_DETECTORS["1.0-s2"]`. Access (profile `kbt6-r1`): trigger set
`d32` (the `d33` "opponent still acting -> R01 §4.2" trigger fired on 81% of action decisions) and
`strategy_priority = ["S02-P8", "S02-P7"]`.
