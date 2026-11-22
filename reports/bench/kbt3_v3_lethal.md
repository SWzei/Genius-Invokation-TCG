# 知识接入阶段比较

场景集 `v3`，划分 `all`（141 道斩杀题），指标 `converted`，轮次 kbt3_v3_lethal_r1, kbt3_v3_lethal_r2；生成于 2026-11-22T06:43:57。

| 受试者 | 题数 | 观测数 | 均值 [95% CI，按观测] | 各轮 | 每题调用 | 每次输入 token | 费用（美元，估算） |
|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 141 | 282 | 0.947 [0.91, 0.97] | kbt3_v3_lethal_r1: 134/141；kbt3_v3_lethal_r2: 133/141 | 1.24 | 1523.8 | 0.05232 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 141 | 282 | 0.954 [0.92, 0.97] | kbt3_v3_lethal_r1: 135/141；kbt3_v3_lethal_r2: 134/141 | 1.18 | 3028.3 | 0.0735 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 141 | 282 | 0.943 [0.91, 0.96] | kbt3_v3_lethal_r1: 133/141；kbt3_v3_lethal_r2: 133/141 | 1.16 | 2989.3 | 0.04854 |

## 逐题配对（每题取各轮均值；符号检验只计均值不同的题）

| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | `llm:deepseek-flash` | 141 | +0.007 [-0.034, +0.048] | 6 / 7 | 1.000 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | `llm:deepseek-flash` | 141 | -0.004 [-0.048, +0.041] | 7 / 10 | 0.629 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 141 | -0.011 [-0.034, +0.012] | 4 / 7 | 0.549 |

## 同一配置的轮间一致性

| 受试者 | 有两轮的题 | 两轮结果不同 |
|---|---|---|
| `llm:deepseek-flash` | 141 | 1 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 141 | 5 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 141 | 8 |
