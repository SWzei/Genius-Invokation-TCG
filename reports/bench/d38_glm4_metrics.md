# D38：GLM-4-Flash 多维指标

生成于 2026-11-23T23:36:55。

| 轮次 | 受试者 | 对手 | 有效对 | 指标 | 对胜率 | 好 / 平 / 差 | 单侧 p | 对分均值 [95% CI] |
|---|---|---|---|---|---|---|---|---|
| d38_glm4 | `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1` | `llm:glm-4-flash-250414#reply=reason_first,elements=1` | 50 | W 胜负 | 0.500 | 5 / 40 / 5 | 0.6230 | +0.000 [-0.125, +0.125] |
| d38_glm4 | `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1` | `llm:glm-4-flash-250414#reply=reason_first,elements=1` | 50 | H 生命差 | 0.400 | 20 / 0 / 30 | 0.9405 | +0.004 [-0.081, +0.088] |
| d38_glm4 | `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1` | `llm:glm-4-flash-250414#reply=reason_first,elements=1` | 50 | K 击倒差 | 0.460 | 13 / 20 / 17 | 0.8192 | -0.047 [-0.200, +0.106] |
| d38_glm4 | `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1` | `llm:glm-4-flash-250414#reply=reason_first,elements=1` | 50 | D 伤害占比 | 0.460 | 23 / 0 / 27 | 0.7601 | +0.002 [-0.023, +0.027] |
| d38_glm4 | `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` | `llm:glm-4-flash-250414#reply=reason_first,elements=1` | 50 | W 胜负 | 0.550 | 12 / 31 / 7 | 0.1796 | +0.100 [-0.070, +0.270] |
| d38_glm4 | `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` | `llm:glm-4-flash-250414#reply=reason_first,elements=1` | 50 | H 生命差 | 0.590 | 29 / 1 / 20 | 0.1264 | +0.101 [+0.003, +0.199] |
| d38_glm4 | `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` | `llm:glm-4-flash-250414#reply=reason_first,elements=1` | 50 | K 击倒差 | 0.610 | 23 / 15 / 12 | 0.0448 | +0.153 [-0.025, +0.332] |
| d38_glm4 | `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` | `llm:glm-4-flash-250414#reply=reason_first,elements=1` | 50 | D 伤害占比 | 0.600 | 30 / 0 / 20 | 0.1013 | +0.039 [+0.010, +0.069] |

口径：一对 = 同一种子、同样两副牌、同样座位，双方各坐一次座位 0。指标取自对局结束时的公开状态与公开伤害事件（`bench.metrics`）。W 的对分 = 两局胜负之和 − 1；H / K / D 的对分 = 两局之和。对胜率 =（好 + 平/2）/ 对数；单侧符号检验（H1：受试者更好），平局不计。任一局出错、截断或模型应答率 < 90% 的对整对剔除。模拟器内结果，不进强度验收。
