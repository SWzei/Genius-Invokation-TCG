# 情境题 situ_v2d33 · dev（D36 R3 守门，双方 elements=1）

题库 `situ_v2d33`，划分 `dev`（469 题：charged 29、reaction 49、turn 49、end 49、summon 49、first_next 49、energy 49、hand_limit 49、dice_cap 49、tuning 48），轮次 kbt5_situ_dev_el_r1；生成于 2026-11-23T04:05:01。

| 知识配置 | 观测数 | 正确率 [95% CI] | 按题型（正确 / 观测） | 注入知识含该题所需规则节（按题型计次） |
|---|---|---|---|---|
| `kbt3-trig` | 469 | 0.861 [0.83, 0.89] | charged 27/29；dice_cap 30/49；end 49/49；energy 41/49；first_next 49/49；hand_limit 19/49；reaction 47/49；summon 45/49；tuning 48/48；turn 49/49 | charged 23/29；dice_cap 0/49；end 14/49；energy 30/49；first_next 36/49；hand_limit 0/49；reaction 24/49；summon 1/49；tuning 0/48；turn 14/49 |
| `kbt6-r3` | 469 | 0.872 [0.84, 0.90] | charged 27/29；dice_cap 33/49；end 49/49；energy 43/49；first_next 49/49；hand_limit 19/49；reaction 47/49；summon 45/49；tuning 48/48；turn 49/49 | charged 23/29；dice_cap 0/49；end 14/49；energy 30/49；first_next 36/49；hand_limit 0/49；reaction 24/49；summon 1/49；tuning 0/48；turn 14/49 |

## 逐题配对（每题取各轮均值）

| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |
|---|---|---|---|---|---|
| `kbt6-r3` | `kbt3-trig` | 469 | +0.011 [-0.003, +0.025] | 8 / 3 | 0.227 |

口径：答案由程序按知识库规则表与可见状态算出；知识按决策局面选取（不看题目）。
