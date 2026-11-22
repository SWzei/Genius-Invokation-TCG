# 斩杀转化 · test

场景集 `v2`，划分 `test`（70 道斩杀题），指标 `converted`，轮次 kbt_test_r1, kbt_test_r2；生成于 2026-11-21T21:35:38。

| 受试者 | 题数 | 观测数 | 均值 [95% CI，按观测] | 各轮 | 每题调用 | 每次输入 token | 费用（美元，估算） |
|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 70 | 140 | 0.943 [0.89, 0.97] | kbt_test_r1: 67/70；kbt_test_r2: 65/70 | 1.36 | 1326.4 | 0.02461 |
| `llm:deepseek-flash#kb=kbt-s0` | 70 | 140 | 0.879 [0.81, 0.92] | kbt_test_r1: 63/70；kbt_test_r2: 60/70 | 1.29 | 2625.9 | 0.03106 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 70 | 140 | 0.936 [0.88, 0.97] | kbt_test_r1: 65/70；kbt_test_r2: 66/70 | 1.18 | 2893.4 | 0.03439 |

## 逐题配对（每题取各轮均值；符号检验只计均值不同的题）

| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s0` | `llm:deepseek-flash` | 70 | -0.064 [-0.113, -0.016] | 0 / 7 | 0.016 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | `llm:deepseek-flash` | 70 | -0.007 [-0.065, +0.051] | 4 / 4 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | `llm:deepseek-flash#kb=kbt-s0` | 70 | +0.057 [-0.019, +0.133] | 8 / 4 | 0.388 |

## 同一配置的轮间一致性

| 受试者 | 有两轮的题 | 两轮结果不同 |
|---|---|---|
| `llm:deepseek-flash` | 70 | 2 |
| `llm:deepseek-flash#kb=kbt-s0` | 70 | 3 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 70 | 3 |
