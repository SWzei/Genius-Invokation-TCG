# 镜像对战：多维指标

生成于 2026-11-24T05:04:40。

| 轮次 | 受试者 | 对手 | 有效对 | 指标 | 对胜率 | 好 / 平 / 差 | 单侧 p | 对分均值 [95% CI] |
|---|---|---|---|---|---|---|---|---|
| d38_decision | `llm:gemini-decision-1#kb=kbt3-trig,elements=1` | `llm:gemini-decision-1#elements=1` | 50 | W 胜负 | 0.530 | 8 / 37 / 5 | 0.2905 | +0.050 [-0.088, +0.188] |
| d38_decision | `llm:gemini-decision-1#kb=kbt3-trig,elements=1` | `llm:gemini-decision-1#elements=1` | 50 | H 生命差 | 0.460 | 23 / 0 / 27 | 0.7601 | +0.018 [-0.094, +0.130] |
| d38_decision | `llm:gemini-decision-1#kb=kbt3-trig,elements=1` | `llm:gemini-decision-1#elements=1` | 50 | K 击倒差 | 0.480 | 16 / 16 / 18 | 0.6962 | +0.020 [-0.142, +0.182] |
| d38_decision | `llm:gemini-decision-1#kb=kbt3-trig,elements=1` | `llm:gemini-decision-1#elements=1` | 50 | D 伤害占比 | 0.600 | 30 / 0 / 20 | 0.1013 | +0.015 [-0.017, +0.048] |

口径：一对 = 同一种子、同样两副牌、同样座位，双方各坐一次座位 0。指标取自对局结束时的公开状态与公开伤害事件（`bench.metrics`）。W 的对分 = 两局胜负之和 − 1；H / K / D 的对分 = 两局之和。对胜率 =（好 + 平/2）/ 对数；单侧符号检验（H1：受试者更好），平局不计。任一局出错、截断或模型应答率 < 90% 的对整对剔除。模拟器内结果，不进强度验收。
