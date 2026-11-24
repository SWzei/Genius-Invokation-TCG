# D37 归因：base + facts=1 对 base（第 100–119 对）

生成于 2026-11-23T14:06:17。

| 轮次 | 受试者 | 对手 | 有效对 | 指标 | 对胜率 | 好 / 平 / 差 | 单侧 p | 对分均值 [95% CI] |
|---|---|---|---|---|---|---|---|---|
| d37_attr_facts | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 20 | W 胜负 | 0.500 | 2 / 16 / 2 | 0.6875 | +0.000 [-0.201, +0.201] |
| d37_attr_facts | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 20 | H 生命差 | 0.425 | 8 / 1 / 11 | 0.8204 | -0.042 [-0.220, +0.136] |
| d37_attr_facts | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 20 | K 击倒差 | 0.550 | 7 / 8 / 5 | 0.3872 | +0.083 [-0.241, +0.408] |
| d37_attr_facts | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 20 | D 伤害占比 | 0.400 | 8 / 0 / 12 | 0.8684 | -0.033 [-0.099, +0.033] |

口径：一对 = 同一种子、同样两副牌、同样座位，双方各坐一次座位 0。指标取自对局结束时的公开状态与公开伤害事件（`bench.metrics`）。W 的对分 = 两局胜负之和 − 1；H / K / D 的对分 = 两局之和。对胜率 =（好 + 平/2）/ 对数；单侧符号检验（H1：受试者更好），平局不计。任一局出错、截断或模型应答率 < 90% 的对整对剔除。模拟器内结果，不进强度验收。
