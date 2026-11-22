# 情境规则题 · test · 先写依据

题库 `situ_d32`，划分 `test`（260 题：charged 52、reaction 52、turn 52、end 52、summon 52），轮次 kbt_situ_test_reason_r1, kbt_situ_test_reason_r2；生成于 2026-11-21T21:35:35。

| 知识配置 | 观测数 | 正确率 [95% CI] | 按题型（正确 / 观测） | 注入知识含该题所需规则节（按题型计次） |
|---|---|---|---|---|
| `none` | 520 | 0.812 [0.78, 0.84] | charged 43/104；end 104/104；reaction 88/104；summon 92/104；turn 95/104 | charged 0/104；end 0/104；reaction 0/104；summon 0/104；turn 0/104 |
| `kbt-s0` | 520 | 0.840 [0.81, 0.87] | charged 78/104；end 104/104；reaction 84/104；summon 95/104；turn 76/104 | charged 58/104；end 0/104；reaction 0/104；summon 0/104；turn 0/104 |
| `kbt-s4` | 520 | 0.923 [0.90, 0.94] | charged 78/104；end 104/104；reaction 99/104；summon 97/104；turn 102/104 | charged 52/104；end 32/104；reaction 64/104；summon 2/104；turn 32/104 |

## 逐题配对（每题取各轮均值）

| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |
|---|---|---|---|---|---|
| `kbt-s0` | `none` | 260 | +0.029 [-0.014, +0.072] | 25 / 20 | 0.551 |
| `kbt-s4` | `none` | 260 | +0.112 [+0.074, +0.149] | 39 / 2 | 0.000 |
| `kbt-s4` | `kbt-s0` | 260 | +0.083 [+0.049, +0.116] | 23 / 1 | 0.000 |

口径：答案由程序按知识库规则表与可见状态算出；知识按决策局面选取（不看题目）。
