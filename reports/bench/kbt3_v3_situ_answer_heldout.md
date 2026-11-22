# 情境规则题

题库 `situ_v3`，划分 `all`，子集 `heldout`（598 题：first_next 120、energy 120、hand_limit 120、dice_cap 120、tuning 118），轮次 kbt3_v3_situ_answer_r1, kbt3_v3_situ_answer_r2；生成于 2026-11-22T04:41:31。

| 知识配置 | 观测数 | 正确率 [95% CI] | 按题型（正确 / 观测） | 注入知识含该题所需规则节（按题型计次） |
|---|---|---|---|---|
| `none` | 1196 | 0.543 [0.52, 0.57] | dice_cap 116/240；energy 174/240；first_next 17/240；hand_limit 128/240；tuning 215/236 | dice_cap 0/240；energy 0/240；first_next 0/240；hand_limit 0/240；tuning 0/236 |
| `kbt3-trig` | 1196 | 0.619 [0.59, 0.65] | dice_cap 116/240；energy 177/240；first_next 85/240；hand_limit 128/240；tuning 234/236 | dice_cap 0/240；energy 144/240；first_next 204/240；hand_limit 0/240；tuning 0/236 |

## 逐题配对（每题取各轮均值）

| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |
|---|---|---|---|---|---|
| `kbt3-trig` | `none` | 598 | +0.075 [+0.049, +0.101] | 74 / 22 | 0.000 |

口径：答案由程序按知识库规则表与可见状态算出；知识按决策局面选取（不看题目）。
