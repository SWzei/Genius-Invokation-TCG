# v1.0-s1 (strategy layer, round 1) — 2026-11-22

Session: https://claude.ai/code/session_01JL7PTAyxV3AauNkijoxPrA (D34). Parent: v1.0 (the rules layer
v1.1 / v1.2 did not pass its gate). Rule sections are unchanged.

## Evidence (train games only)

`mirror_train` pairs 0–19 (`d34_ab_v10_train`, v1.0 `kbt3-trig` vs no KB, both `reply=reason_first`),
digested by `python -m bench.mirror_digest`. Two independent reviews, each of one half (10 pairs), by
the teacher's subagents; only changes supported by **both** halves are kept, plus one text error.

| pattern (both halves) | change |
|---|---|
| ends the round with 3–6 usable dice while the opponent still acts ("保留骰子", "普攻收益低") | new **S02-P7** |
| full-energy active character; burst dice spent on draw / supports / food; burst delayed or lost | new **S01-P9** |
| S09-P4 (support/summon zone ≥ 3) shown dozens of times per game, cited as a reason to end, pushing other units out of the 2 slots | **S09-P4** fires only on a full zone (4) with a card play available; text says a full zone is no reason to stop attacking |
| S01-P2 "转化为价值" too vague; "ending keeps the initiative" after the opponent already ended | **S01-P2** recommendation and limits made concrete |
| text error: S07-P4 fires at hand ≥ 9 but advised "不断过牌"; the model drew 3–4 cards at 9–10 in hand | **S07-P4** recommendation fixed |

Not adopted (one half only, or not strategy): low-HP active character switching; S12-P4 rewrite; the
state text does not show character elements (observation issue, noted for later).

## Detectors

`reps/knowledge.py` `_VERSION_DETECTORS["1.0-s1"]` (v1.0 keeps its table): S01-P9, S02-P7, S09-P4.
Firing rates on the `v1` train set (`configs/knowledge/unit_frequency_train_s1.json`): S02-P7 0.17
(narrowed from ≥ 3 dice, 0.48, to 3–5 dice), S01-P9 0.17, S09-P4 0.06 (was 0.15), all below the 0.5 cut.

## Gate

`reports/review/2026-11_kb_d34_prereg.md` §5: v1.0-s1 vs v1.0 on `mirror_dev` pairs 0–79.
