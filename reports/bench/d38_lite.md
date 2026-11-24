# Benchmark `d38_lite` — suite `mirror_dev200` (7783c19b2a879a6f)

- cells: 400 (mirror-dev 400); seed base 7100001
- generated: 2026-11-23T21:39:05; stopped: fatal API error: llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1,facts=1: quota: [{'error': {'code': 429, 'message': 'You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://aistudio.google.com/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded fo; llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1: quota: [{'error': {'code': 429, 'message': 'You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://aistudio.google.com/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota exceeded fo; model calls 1180, cost 0.00418

## Win rate (Wilson 95%)

| subject | valid / games | overall |  |
|---|---|---|
| `llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1` | 0 / 5 | — |  |
| `llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` | 0 / 4 | — |  |

## Paired difference vs `llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1` (same cells)

| subject | pairs | delta | 95% CI | better / worse / same | sign test p |
|---|---|---|---|---|---|
| `llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` | 0 | — | — | — | — |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1` | 338 | 0.0207 | 0.0207 | 331 | 0.025 | 0.0 / 0.0 / 1.163 | 43.6 | 67.6 | 2947 | 0.000313 |
| `llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` | 260 | 0.0231 | 0.0231 | 254 | 0.025 | 0.0 / 0.0 / 1.089 | 47.9 | 65.0 | 3113 | 0.00033 |

Errors (why a model answer was not used): `llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1` {'api:quota': 331}; `llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` {'api:quota': 254}

## Run health

- `llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1` engine fallbacks 0, invalid 0, degraded 5
- `llm:gemini-35-flash-lite#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` engine fallbacks 0, invalid 0, degraded 4

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
