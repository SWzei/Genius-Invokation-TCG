# 情境规则题 · train · 先写依据（D34 v1.1 诊断）

题库 `situ_d32`，划分 `train`（495 题：charged 99、reaction 99、turn 99、end 99、summon 99），轮次 kbt4_situ_train_reason_r1；生成于 2026-11-22T13:16:46。

| 知识配置 | 观测数 | 正确率 [95% CI] | 按题型（正确 / 观测） | 注入知识含该题所需规则节（按题型计次） |
|---|---|---|---|---|
| `kbt3-trig` | 495 | 0.923 [0.90, 0.94] | charged 73/99；end 99/99；reaction 95/99；summon 92/99；turn 98/99 | charged 50/99；end 27/99；reaction 50/99；summon 0/99；turn 27/99 |
| `kbt4-v11` | 495 | 0.925 [0.90, 0.94] | charged 73/99；end 99/99；reaction 96/99；summon 91/99；turn 99/99 | charged 50/99；end 25/99；reaction 50/99；summon 0/99；turn 25/99 |

## 逐题配对（每题取各轮均值）

| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |
|---|---|---|---|---|---|
| `kbt4-v11` | `kbt3-trig` | 495 | +0.002 [-0.010, +0.014] | 5 / 4 | 1.000 |

口径：答案由程序按知识库规则表与可见状态算出；知识按决策局面选取（不看题目）。
