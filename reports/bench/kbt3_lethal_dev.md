# 知识接入阶段比较

场景集 `v2`，划分 `dev`（64 道斩杀题），指标 `converted`，轮次 kbt_dev_r1, kbt_dev_r2；生成于 2026-11-22T03:39:24。

| 受试者 | 题数 | 观测数 | 均值 [95% CI，按观测] | 各轮 | 每题调用 | 每次输入 token | 费用（美元，估算） |
|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 64 | 128 | 0.922 [0.86, 0.96] | kbt_dev_r1: 59/64；kbt_dev_r2: 59/64 | 1.47 | 1399.9 | 0.02606 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 64 | 128 | 0.977 [0.93, 0.99] | kbt_dev_r1: 63/64；kbt_dev_r2: 62/64 | 1.14 | 3073.3 | 0.01487 |
| `llm:deepseek-flash#kb=kbt3-lean,reply=reason_first` | 64 | 128 | 0.938 [0.88, 0.97] | kbt_dev_r1: 59/64；kbt_dev_r2: 61/64 | 1.37 | 2500.6 | 0.01997 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 64 | 128 | 0.977 [0.93, 0.99] | kbt_dev_r1: 64/64；kbt_dev_r2: 61/64 | 1.2 | 3021.6 | 0.02554 |
| `llm:deepseek-flash#kb=kbt-s4,reply=checklist` | 64 | 128 | 0.961 [0.91, 0.98] | kbt_dev_r1: 61/64；kbt_dev_r2: 62/64 | 1.02 | 3102.6 | 0.01089 |

## 逐题配对（每题取各轮均值；符号检验只计均值不同的题）

| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | `llm:deepseek-flash` | 64 | +0.055 [+0.001, +0.109] | 4 / 0 | 0.125 |
| `llm:deepseek-flash#kb=kbt3-lean,reply=reason_first` | `llm:deepseek-flash` | 64 | +0.016 [-0.046, +0.077] | 4 / 3 | 1.000 |
| `llm:deepseek-flash#kb=kbt3-lean,reply=reason_first` | `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 64 | -0.039 [-0.084, +0.006] | 1 / 5 | 0.219 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | `llm:deepseek-flash` | 64 | +0.055 [-0.011, +0.121] | 5 / 2 | 0.453 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 64 | +0.000 [-0.031, +0.031] | 2 / 2 | 1.000 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | `llm:deepseek-flash#kb=kbt3-lean,reply=reason_first` | 64 | +0.039 [-0.006, +0.084] | 5 / 1 | 0.219 |
| `llm:deepseek-flash#kb=kbt-s4,reply=checklist` | `llm:deepseek-flash` | 64 | +0.039 [-0.011, +0.089] | 4 / 1 | 0.375 |
| `llm:deepseek-flash#kb=kbt-s4,reply=checklist` | `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 64 | -0.016 [-0.037, +0.006] | 0 / 2 | 0.500 |
| `llm:deepseek-flash#kb=kbt-s4,reply=checklist` | `llm:deepseek-flash#kb=kbt3-lean,reply=reason_first` | 64 | +0.023 [-0.011, +0.058] | 4 / 1 | 0.375 |
| `llm:deepseek-flash#kb=kbt-s4,reply=checklist` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 64 | -0.016 [-0.053, +0.022] | 2 / 4 | 0.688 |

## 同一配置的轮间一致性

| 受试者 | 有两轮的题 | 两轮结果不同 |
|---|---|---|
| `llm:deepseek-flash` | 64 | 0 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 64 | 1 |
| `llm:deepseek-flash#kb=kbt3-lean,reply=reason_first` | 64 | 4 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 64 | 3 |
| `llm:deepseek-flash#kb=kbt-s4,reply=checklist` | 64 | 3 |
