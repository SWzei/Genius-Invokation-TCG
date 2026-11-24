# v1.0-s3 (strategy layer, D36 round 3) — 2026-11-23

Session: https://claude.ai/code/session_01JL7PTAyxV3AauNkijoxPrA (D36). Parent: v1.0 (not s2). Rule sections unchanged.

## Evidence (train only)

- Natural divergence points of D36 train pairs (`mirror_train` pairs 20–49): both games of a pair share seed and
  seat decks, so they stay identical until the two policies first choose differently. In 28 of 30 pairs that
  first difference is the opening mulligan, so the mulligan decides which game is played.
- At the mulligan the knowledge side sees v1.0's S05-P1 ("keep early-playable cards, swap late cards") and
  swaps the team's signature cards (talents / character-only equipment) 16/41 times vs 7/41 without knowledge
  (D34 + D36 train, both sides), with reasons such as "高费装备偏后期"; it swaps its arcane card 11/100 vs 7/100.
- Win rate after swapping a signature card 8/20 vs 21/46 when kept (both sides pooled; weak, correlation only).

## What

| change | content |
|---|---|
| S05-P1 conclusion | keep the team's signature cards and the arcane card first, then early resource cards; swap unrelated, duplicate or costly generic cards |
| S05-P1 limits | a duplicate signature card may be swapped |
| S05-P1 evidence | the D34 / D36 train counts above |
| summary table row | same as the conclusion |

No new detector (S05-P1 keeps its v1.0 condition: the mulligan). Access (profile `kbt6-r3`) = `kbt3-trig` plus
`kb_version = "v1.0-s3"`.
