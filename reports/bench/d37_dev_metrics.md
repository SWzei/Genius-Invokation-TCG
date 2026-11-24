# D37 dev：v11 对 base（第 100–139 对，40 对）

生成于 2026-11-23T13:51:28。

| 轮次 | 受试者 | 对手 | 有效对 | 指标 | 对胜率 | 好 / 平 / 差 | 单侧 p | 对分均值 [95% CI] |
|---|---|---|---|---|---|---|---|---|
| d37_dev_s1+d37_dev_s2 | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 40 | W 胜负 | 0.438 | 3 / 29 / 8 | 0.9673 | -0.125 [-0.285, +0.035] |
| d37_dev_s1+d37_dev_s2 | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 40 | H 生命差 | 0.475 | 19 / 0 / 21 | 0.6821 | -0.128 [-0.285, +0.028] |
| d37_dev_s1+d37_dev_s2 | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 40 | K 击倒差 | 0.487 | 14 / 11 / 15 | 0.6445 | -0.108 [-0.360, +0.143] |
| d37_dev_s1+d37_dev_s2 | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 40 | D 伤害占比 | 0.388 | 15 / 1 / 24 | 0.9459 | -0.060 [-0.112, -0.009] |

口径：一对 = 同一种子、同样两副牌、同样座位，双方各坐一次座位 0。指标取自对局结束时的公开状态与公开伤害事件（`bench.metrics`）。W 的对分 = 两局胜负之和 − 1；H / K / D 的对分 = 两局之和。对胜率 =（好 + 平/2）/ 对数；单侧符号检验（H1：受试者更好），平局不计。任一局出错、截断或模型应答率 < 90% 的对整对剔除。模拟器内结果，不进强度验收。
