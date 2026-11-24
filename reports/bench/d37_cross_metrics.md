# D37 跨模型：DeepSeek（base / v11）对 GLM-5.3-Flash（第 140–149 对）

生成于 2026-11-23T14:17:38。

| 轮次 | 受试者 | 对手 | 有效对 | 指标 | 对胜率 | 好 / 平 / 差 | 单侧 p | 对分均值 [95% CI] |
|---|---|---|---|---|---|---|---|---|
| d37_cross | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | `llm:glm-53-flash#reply=reason_first,elements=1` | 10 | W 胜负 | 0.500 | 1 / 8 / 1 | 0.7500 | +0.000 [-0.292, +0.292] |
| d37_cross | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | `llm:glm-53-flash#reply=reason_first,elements=1` | 10 | H 生命差 | 0.600 | 6 / 0 / 4 | 0.3770 | +0.051 [-0.207, +0.309] |
| d37_cross | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | `llm:glm-53-flash#reply=reason_first,elements=1` | 10 | K 击倒差 | 0.650 | 5 / 3 / 2 | 0.2266 | +0.033 [-0.396, +0.463] |
| d37_cross | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | `llm:glm-53-flash#reply=reason_first,elements=1` | 10 | D 伤害占比 | 0.650 | 6 / 1 / 3 | 0.2539 | +0.028 [-0.066, +0.123] |
| d37_cross | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:glm-53-flash#reply=reason_first,elements=1` | 10 | W 胜负 | 0.450 | 0 / 9 / 1 | 1.0000 | -0.100 [-0.296, +0.096] |
| d37_cross | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:glm-53-flash#reply=reason_first,elements=1` | 10 | H 生命差 | 0.200 | 2 / 0 / 8 | 0.9893 | -0.184 [-0.306, -0.061] |
| d37_cross | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:glm-53-flash#reply=reason_first,elements=1` | 10 | K 击倒差 | 0.300 | 1 / 4 / 5 | 0.9844 | -0.300 [-0.599, -0.001] |
| d37_cross | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:glm-53-flash#reply=reason_first,elements=1` | 10 | D 伤害占比 | 0.200 | 2 / 0 / 8 | 0.9893 | -0.055 [-0.103, -0.008] |

口径：一对 = 同一种子、同样两副牌、同样座位，双方各坐一次座位 0。指标取自对局结束时的公开状态与公开伤害事件（`bench.metrics`）。W 的对分 = 两局胜负之和 − 1；H / K / D 的对分 = 两局之和。对胜率 =（好 + 平/2）/ 对数；单侧符号检验（H1：受试者更好），平局不计。任一局出错、截断或模型应答率 < 90% 的对整对剔除。模拟器内结果，不进强度验收。
