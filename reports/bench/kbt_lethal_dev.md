# 斩杀转化 · dev

场景集 `v2`，划分 `dev`（64 道斩杀题），指标 `converted`，轮次 kbt_dev_r1, kbt_dev_r2；生成于 2026-11-21T21:35:37。

| 受试者 | 题数 | 观测数 | 均值 [95% CI，按观测] | 各轮 | 每题调用 | 每次输入 token | 费用（美元，估算） |
|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 64 | 128 | 0.922 [0.86, 0.96] | kbt_dev_r1: 59/64；kbt_dev_r2: 59/64 | 1.47 | 1399.9 | 0.02606 |
| `llm:deepseek-flash#kb=kbt-s0` | 64 | 128 | 0.906 [0.84, 0.95] | kbt_dev_r1: 58/64；kbt_dev_r2: 58/64 | 1.36 | 2643.8 | 0.02971 |
| `llm:deepseek-flash#kb=kbt-s4` | 64 | 128 | 0.898 [0.83, 0.94] | kbt_dev_r1: 57/64；kbt_dev_r2: 58/64 | 1.09 | 3055.0 | 0.02752 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 64 | 128 | 0.977 [0.93, 0.99] | kbt_dev_r1: 63/64；kbt_dev_r2: 62/64 | 1.14 | 3073.3 | 0.01487 |
| `llm:deepseek-flash#reply=reason_first` | 64 | 128 | 0.898 [0.83, 0.94] | kbt_dev_r1: 57/64；kbt_dev_r2: 58/64 | 1.32 | 1475.9 | 0.01318 |

## 逐题配对（每题取各轮均值；符号检验只计均值不同的题）

| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s0` | `llm:deepseek-flash` | 64 | -0.016 [-0.046, +0.015] | 0 / 1 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s4` | `llm:deepseek-flash` | 64 | -0.023 [-0.079, +0.032] | 1 / 3 | 0.625 |
| `llm:deepseek-flash#kb=kbt-s4` | `llm:deepseek-flash#kb=kbt-s0` | 64 | -0.008 [-0.071, +0.056] | 2 / 3 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | `llm:deepseek-flash` | 64 | +0.055 [+0.001, +0.109] | 4 / 0 | 0.125 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | `llm:deepseek-flash#kb=kbt-s0` | 64 | +0.070 [+0.009, +0.132] | 5 / 0 | 0.062 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | `llm:deepseek-flash#kb=kbt-s4` | 64 | +0.078 [+0.016, +0.141] | 6 / 0 | 0.031 |
| `llm:deepseek-flash#reply=reason_first` | `llm:deepseek-flash` | 64 | -0.023 [-0.079, +0.032] | 1 / 3 | 0.625 |
| `llm:deepseek-flash#reply=reason_first` | `llm:deepseek-flash#kb=kbt-s0` | 64 | -0.008 [-0.071, +0.056] | 2 / 3 | 1.000 |
| `llm:deepseek-flash#reply=reason_first` | `llm:deepseek-flash#kb=kbt-s4` | 64 | +0.000 [-0.066, +0.066] | 3 / 3 | 1.000 |
| `llm:deepseek-flash#reply=reason_first` | `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 64 | -0.078 [-0.141, -0.016] | 0 / 6 | 0.031 |

## 同一配置的轮间一致性

| 受试者 | 有两轮的题 | 两轮结果不同 |
|---|---|---|
| `llm:deepseek-flash` | 64 | 0 |
| `llm:deepseek-flash#kb=kbt-s0` | 64 | 0 |
| `llm:deepseek-flash#kb=kbt-s4` | 64 | 1 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 64 | 1 |
| `llm:deepseek-flash#reply=reason_first` | 64 | 1 |
