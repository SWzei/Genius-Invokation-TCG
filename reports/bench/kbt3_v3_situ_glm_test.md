# 情境规则题

题库 `situ_v3`，划分 `test`（403 题：reaction 42、turn 42、end 42、summon 42、first_next 42、energy 42、hand_limit 42、dice_cap 42、tuning 42、charged 25），轮次 kbt3_v3_situ_glm_reason_r1；生成于 2026-11-22T11:19:23。

| 知识配置 | 观测数 | 正确率 [95% CI] | 按题型（正确 / 观测） | 注入知识含该题所需规则节（按题型计次） |
|---|---|---|---|---|
| `none` | 401 | 0.429 [0.38, 0.48] | charged 8/25；dice_cap 22/42；end 14/42；energy 12/41；first_next 17/42；hand_limit 24/41；reaction 21/42；summon 11/42；tuning 26/42；turn 17/42 | charged 0/25；dice_cap 0/42；end 0/42；energy 0/41；first_next 0/42；hand_limit 0/41；reaction 0/42；summon 0/42；tuning 0/42；turn 0/42 |
| `kbt3-trig` | 391 | 0.642 [0.59, 0.69] | charged 22/25；dice_cap 20/41；end 40/42；energy 20/38；first_next 12/40；hand_limit 22/41；reaction 28/41；summon 14/41；tuning 36/41；turn 37/41 | charged 20/25；dice_cap 0/41；end 6/42；energy 25/38；first_next 35/40；hand_limit 0/41；reaction 18/41；summon 0/41；tuning 0/41；turn 6/41 |

## 逐题配对（每题取各轮均值）

| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |
|---|---|---|---|---|---|
| `kbt3-trig` | `none` | 390 | +0.218 [+0.162, +0.274] | 114 / 29 | 0.000 |

口径：答案由程序按知识库规则表与可见状态算出；知识按决策局面选取（不看题目）。
