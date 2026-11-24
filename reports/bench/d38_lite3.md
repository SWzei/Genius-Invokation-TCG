# Benchmark `d38_lite3` — suite `mirror_dev200` (7783c19b2a879a6f)

- cells: 400 (mirror-dev 400); seed base 7100001
- generated: 2026-11-23T22:21:40; stopped: fatal API error: llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1: quota: [429] You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://aistudio.google.com/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. 
* Quota exceeded for metric: generativelanguage.goo; model calls 535, cost 0.076327

## Win rate (Wilson 95%)

| subject | valid / games | overall | model |
|---|---|---|---|
| `llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1` | 3 / 4 | 0.333 [0.06, 0.79] (n=3) | 0.333 [0.06, 0.79] (n=3) |

## By rules version

| subject | v6.2.0 | v6.3.0 |
|---|---|---|
| `llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1` | 0.500 [0.09, 0.91] (n=2) | 0.000 [0.00, 0.79] (n=1) |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1` | 279 | 0.6882 | 0.6882 | 87 | 3.145 | 1.119 / 7.79 / 83.957 | 1747.5 | 69.8 | 121890 | 0.012969 |

Errors (why a model answer was not used): `llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1` {'api:quota': 87}

## Run health

- `llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1` engine fallbacks 0, invalid 0, degraded 1

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
