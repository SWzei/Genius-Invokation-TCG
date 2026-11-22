# 情境规则题

题库 `situ_v3`，划分 `all`，子集 `heldout`（598 题：first_next 120、energy 120、hand_limit 120、dice_cap 120、tuning 118），轮次 kbt3_v3_situ_reason_r1, kbt3_v3_situ_reason_r2；生成于 2026-11-22T04:41:31。

| 知识配置 | 观测数 | 正确率 [95% CI] | 按题型（正确 / 观测） | 注入知识含该题所需规则节（按题型计次） |
|---|---|---|---|---|
| `none` | 1196 | 0.635 [0.61, 0.66] | dice_cap 146/240；energy 203/240；first_next 37/240；hand_limit 138/240；tuning 236/236 | dice_cap 0/240；energy 0/240；first_next 0/240；hand_limit 0/240；tuning 0/236 |
| `kbt3-trig` | 1196 | 0.768 [0.74, 0.79] | dice_cap 139/240；energy 182/240；first_next 230/240；hand_limit 132/240；tuning 236/236 | dice_cap 0/240；energy 144/240；first_next 204/240；hand_limit 0/240；tuning 0/236 |

## 逐题配对（每题取各轮均值）

| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |
|---|---|---|---|---|---|
| `kbt3-trig` | `none` | 598 | +0.133 [+0.097, +0.169] | 136 / 48 | 0.000 |

口径：答案由程序按知识库规则表与可见状态算出；知识按决策局面选取（不看题目）。
