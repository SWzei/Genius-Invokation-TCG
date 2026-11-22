# 情境规则题 · train · 先写依据（1 轮）

题库 `situ_v1`，划分 `train`（200 题：charged 40、reaction 40、turn 40、end 40、summon 40），轮次 kbt_situ_train_reason_r1；生成于 2026-11-21T21:35:35。

| 知识配置 | 观测数 | 正确率 [95% CI] | 按题型（正确 / 观测） | 注入知识含该题所需规则节（按题型计次） |
|---|---|---|---|---|
| `none` | 200 | 0.835 [0.78, 0.88] | charged 16/40；end 40/40；reaction 38/40；summon 35/40；turn 38/40 | charged 0/40；end 0/40；reaction 0/40；summon 0/40；turn 0/40 |
| `kbt-s0` | 200 | 0.910 [0.86, 0.94] | charged 33/40；end 40/40；reaction 39/40；summon 35/40；turn 35/40 | charged 28/40；end 1/40；reaction 0/40；summon 0/40；turn 1/40 |
| `kbt-s4` | 200 | 0.940 [0.90, 0.96] | charged 32/40；end 40/40；reaction 39/40；summon 37/40；turn 40/40 | charged 26/40；end 9/40；reaction 18/40；summon 0/40；turn 9/40 |

## 逐题配对（每题取各轮均值）

| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |
|---|---|---|---|---|---|
| `kbt-s0` | `none` | 200 | +0.075 [+0.029, +0.121] | 19 / 4 | 0.003 |
| `kbt-s4` | `none` | 200 | +0.105 [+0.060, +0.150] | 22 / 1 | 0.000 |
| `kbt-s4` | `kbt-s0` | 200 | +0.030 [-0.001, +0.061] | 8 / 2 | 0.109 |

口径：答案由程序按知识库规则表与可见状态算出；知识按决策局面选取（不看题目）。
