# 情境规则题 · dev · 先写依据（D33 候选）

题库 `situ_d32`，划分 `dev`（245 题：charged 49、reaction 49、turn 49、end 49、summon 49），轮次 kbt_situ_dev_reason_r1, kbt_situ_dev_reason_r2；生成于 2026-11-22T02:12:13。

| 知识配置 | 观测数 | 正确率 [95% CI] | 按题型（正确 / 观测） | 注入知识含该题所需规则节（按题型计次） |
|---|---|---|---|---|
| `none` | 490 | 0.829 [0.79, 0.86] | charged 47/98；end 98/98；reaction 92/98；summon 80/98；turn 89/98 | charged 0/98；end 0/98；reaction 0/98；summon 0/98；turn 0/98 |
| `kbt-s0` | 490 | 0.882 [0.85, 0.91] | charged 80/98；end 98/98；reaction 91/98；summon 90/98；turn 73/98 | charged 54/98；end 2/98；reaction 0/98；summon 0/98；turn 2/98 |
| `kbt-s4` | 490 | 0.924 [0.90, 0.94] | charged 74/98；end 98/98；reaction 93/98；summon 92/98；turn 96/98 | charged 46/98；end 28/98；reaction 48/98；summon 2/98；turn 28/98 |
| `kbt3-lean` | 490 | 0.918 [0.89, 0.94] | charged 74/98；end 98/98；reaction 90/98；summon 90/98；turn 98/98 | charged 46/98；end 28/98；reaction 48/98；summon 2/98；turn 28/98 |
| `kbt3-trig` | 490 | 0.933 [0.91, 0.95] | charged 74/98；end 98/98；reaction 96/98；summon 91/98；turn 98/98 | charged 46/98；end 28/98；reaction 48/98；summon 2/98；turn 28/98 |

## 逐题配对（每题取各轮均值）

| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |
|---|---|---|---|---|---|
| `kbt-s0` | `none` | 245 | +0.053 [+0.010, +0.097] | 27 / 15 | 0.088 |
| `kbt-s4` | `none` | 245 | +0.096 [+0.057, +0.135] | 32 / 4 | 0.000 |
| `kbt-s4` | `kbt-s0` | 245 | +0.043 [+0.008, +0.078] | 17 / 6 | 0.035 |
| `kbt3-lean` | `none` | 245 | +0.090 [+0.051, +0.129] | 31 / 5 | 0.000 |
| `kbt3-lean` | `kbt-s0` | 245 | +0.037 [+0.001, +0.072] | 17 / 9 | 0.169 |
| `kbt3-lean` | `kbt-s4` | 245 | -0.006 [-0.019, +0.007] | 1 / 4 | 0.375 |
| `kbt3-trig` | `none` | 245 | +0.104 [+0.067, +0.141] | 32 / 2 | 0.000 |
| `kbt3-trig` | `kbt-s0` | 245 | +0.051 [+0.018, +0.084] | 18 / 3 | 0.002 |
| `kbt3-trig` | `kbt-s4` | 245 | +0.008 [-0.004, +0.021] | 3 / 1 | 0.625 |
| `kbt3-trig` | `kbt3-lean` | 245 | +0.014 [-0.000, +0.029] | 6 / 1 | 0.125 |

口径：答案由程序按知识库规则表与可见状态算出；知识按决策局面选取（不看题目）。
