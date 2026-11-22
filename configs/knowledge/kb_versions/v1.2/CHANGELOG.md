# v1.2 (rules layer) — 2026-11-22

Session: https://claude.ai/code/session_01JL7PTAyxV3AauNkijoxPrA (D34). Parent: v1.1. No rule fact changed.

## Why

The engine check of v1.1 (`reports/bench/kb_engine_check_v11.md`, 24 `v2` train games) found the
R03 §2 card's "+1 energy, capped" statement true for every ordinary character (66/66, all capped
cases included) and false only for characters that use a special resource instead of energy
(Mavuika 1315, Skirk 1116 / 6605: 15 observations). R04 §2.1 already lists them as exceptions; the
card did not say so (the table cell under it does: "另有规定除外").

v1.1 failed the situational-question dev gate (−0.016, 0 better / 4 worse; train +0.002); the
diagnosis was done on the train split only and found no card defect behind it.

## What

R03 §2 card: "…不超过充能上限（已满时不变，`R04` §2；玛薇卡、丝柯克等以特殊资源代替充能的角色除外，`R04` §2.1）".

## Checks

`validate_kb` 0 issues; engine check as v1.1 (the added clause names the observed exceptions).
