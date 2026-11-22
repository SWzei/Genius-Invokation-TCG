# 情境规则题

题库 `situ_v3`，划分 `all`，子集 `designed`（553 题：charged 73、reaction 120、turn 120、end 120、summon 120），轮次 kbt3_v3_situ_reason_r1, kbt3_v3_situ_reason_r2；生成于 2026-11-22T04:41:31。

| 知识配置 | 观测数 | 正确率 [95% CI] | 按题型（正确 / 观测） | 注入知识含该题所需规则节（按题型计次） |
|---|---|---|---|---|
| `none` | 1106 | 0.865 [0.84, 0.88] | charged 64/146；end 240/240；reaction 219/240；summon 203/240；turn 231/240 | charged 0/146；end 0/240；reaction 0/240；summon 0/240；turn 0/240 |
| `kbt3-trig` | 1106 | 0.950 [0.94, 0.96] | charged 138/146；end 240/240；reaction 217/240；summon 219/240；turn 237/240 | charged 122/146；end 48/240；reaction 104/240；summon 2/240；turn 48/240 |

## 逐题配对（每题取各轮均值）

| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |
|---|---|---|---|---|---|
| `kbt3-trig` | `none` | 553 | +0.085 [+0.060, +0.110] | 60 / 9 | 0.000 |

口径：答案由程序按知识库规则表与可见状态算出；知识按决策局面选取（不看题目）。
