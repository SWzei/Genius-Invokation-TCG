# 斩杀转化 · train（v1 全部 52 题，1 轮）

场景集 `v1`，划分 `all`（52 道斩杀题），指标 `converted`，轮次 kbt_v1_r1；生成于 2026-11-21T21:35:36。

| 受试者 | 题数 | 观测数 | 均值 [95% CI，按观测] | 各轮 | 每题调用 | 每次输入 token | 费用（美元，估算） |
|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 52 | 52 | 0.923 [0.82, 0.97] | kbt_v1_r1: 48/52 | 1.38 | 1293.5 | 0.00493 |
| `llm:deepseek-flash#kb=kbt-s0` | 52 | 52 | 0.942 [0.84, 0.98] | kbt_v1_r1: 49/52 | 1.29 | 2473.5 | 0.00505 |
| `llm:deepseek-flash#kb=kbt-s1` | 52 | 52 | 0.904 [0.79, 0.96] | kbt_v1_r1: 47/52 | 1.23 | 2528.0 | 0.01583 |
| `llm:deepseek-flash#kb=kbt-s2` | 52 | 52 | 0.904 [0.79, 0.96] | kbt_v1_r1: 47/52 | 1.25 | 2188.1 | 0.00743 |
| `llm:deepseek-flash#kb=kbt-s3` | 52 | 52 | 0.923 [0.82, 0.97] | kbt_v1_r1: 48/52 | 1.15 | 2591.3 | 0.00855 |
| `llm:deepseek-flash#kb=kbt-s4` | 52 | 52 | 0.942 [0.84, 0.98] | kbt_v1_r1: 49/52 | 1.12 | 2873.6 | 0.0179 |

## 逐题配对（每题取各轮均值；符号检验只计均值不同的题）

| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s0` | `llm:deepseek-flash` | 52 | +0.019 [-0.018, +0.057] | 1 / 0 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s1` | `llm:deepseek-flash` | 52 | -0.019 [-0.085, +0.046] | 1 / 2 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s1` | `llm:deepseek-flash#kb=kbt-s0` | 52 | -0.038 [-0.091, +0.014] | 0 / 2 | 0.500 |
| `llm:deepseek-flash#kb=kbt-s2` | `llm:deepseek-flash` | 52 | -0.019 [-0.085, +0.046] | 1 / 2 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s2` | `llm:deepseek-flash#kb=kbt-s0` | 52 | -0.038 [-0.091, +0.014] | 0 / 2 | 0.500 |
| `llm:deepseek-flash#kb=kbt-s2` | `llm:deepseek-flash#kb=kbt-s1` | 52 | +0.000 [+0.000, +0.000] | 0 / 0 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s3` | `llm:deepseek-flash` | 52 | +0.000 [-0.054, +0.054] | 1 / 1 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s3` | `llm:deepseek-flash#kb=kbt-s0` | 52 | -0.019 [-0.057, +0.018] | 0 / 1 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s3` | `llm:deepseek-flash#kb=kbt-s1` | 52 | +0.019 [-0.046, +0.085] | 2 / 1 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s3` | `llm:deepseek-flash#kb=kbt-s2` | 52 | +0.019 [-0.046, +0.085] | 2 / 1 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s4` | `llm:deepseek-flash` | 52 | +0.019 [-0.018, +0.057] | 1 / 0 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s4` | `llm:deepseek-flash#kb=kbt-s0` | 52 | +0.000 [+0.000, +0.000] | 0 / 0 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s4` | `llm:deepseek-flash#kb=kbt-s1` | 52 | +0.038 [-0.014, +0.091] | 2 / 0 | 0.500 |
| `llm:deepseek-flash#kb=kbt-s4` | `llm:deepseek-flash#kb=kbt-s2` | 52 | +0.038 [-0.014, +0.091] | 2 / 0 | 0.500 |
| `llm:deepseek-flash#kb=kbt-s4` | `llm:deepseek-flash#kb=kbt-s3` | 52 | +0.019 [-0.018, +0.057] | 1 / 0 | 1.000 |
