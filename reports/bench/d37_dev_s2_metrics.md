# D37 dev 第二阶段

生成于 2026-11-23T13:51:18。

| 轮次 | 受试者 | 对手 | 有效对 | 指标 | 对胜率 | 好 / 平 / 差 | 单侧 p | 对分均值 [95% CI] |
|---|---|---|---|---|---|---|---|---|
| d37_dev_s1 | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 20 | W 胜负 | 0.450 | 1 / 16 / 3 | 0.9375 | -0.100 [-0.296, +0.096] |
| d37_dev_s1 | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 20 | H 生命差 | 0.550 | 11 / 0 / 9 | 0.4119 | -0.054 [-0.271, +0.163] |
| d37_dev_s1 | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 20 | K 击倒差 | 0.575 | 10 / 3 / 7 | 0.3145 | +0.033 [-0.281, +0.347] |
| d37_dev_s1 | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 20 | D 伤害占比 | 0.425 | 8 / 1 / 11 | 0.8204 | -0.049 [-0.110, +0.011] |
| d37_dev_s2 | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 20 | W 胜负 | 0.425 | 2 / 13 / 5 | 0.9375 | -0.150 [-0.407, +0.107] |
| d37_dev_s2 | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 20 | H 生命差 | 0.400 | 8 / 0 / 12 | 0.8684 | -0.203 [-0.429, +0.024] |
| d37_dev_s2 | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 20 | K 击倒差 | 0.400 | 4 / 8 / 8 | 0.9270 | -0.250 [-0.640, +0.141] |
| d37_dev_s2 | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 20 | D 伤害占比 | 0.350 | 7 / 0 / 13 | 0.9423 | -0.072 [-0.156, +0.013] |

口径：一对 = 同一种子、同样两副牌、同样座位，双方各坐一次座位 0。指标取自对局结束时的公开状态与公开伤害事件（`bench.metrics`）。W 的对分 = 两局胜负之和 − 1；H / K / D 的对分 = 两局之和。对胜率 =（好 + 平/2）/ 对数；单侧符号检验（H1：受试者更好），平局不计。任一局出错、截断或模型应答率 < 90% 的对整对剔除。模拟器内结果，不进强度验收。
