# Benchmark `d38_glm4` — suite `mirror_dev200` (7783c19b2a879a6f)

- cells: 400 (mirror-dev 400); seed base 7100001
- generated: 2026-11-23T23:36:50; stopped: None; model calls 23871, cost 0.0

## Win rate (Wilson 95%)

| subject | valid / games | overall | model |
|---|---|---|---|
| `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1` | 100 / 100 | 0.500 [0.40, 0.60] (n=100) | 0.500 [0.40, 0.60] (n=100) |
| `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` | 100 / 100 | 0.550 [0.45, 0.64] (n=100) | 0.550 [0.45, 0.64] (n=100) |

## By rules version

| subject | v6.2.0 | v6.3.0 |
|---|---|---|
| `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1` | 0.460 [0.33, 0.60] (n=50) | 0.540 [0.40, 0.67] (n=50) |
| `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` | 0.520 [0.39, 0.65] (n=50) | 0.580 [0.44, 0.71] (n=50) |

## Paired difference vs `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1` (same cells)

| subject | pairs | delta | 95% CI | better / worse / same | sign test p |
|---|---|---|---|---|---|
| `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` | 100 | +0.050 | [-0.05, +0.15] | 16 / 11 / 73 | 0.442 |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1` | 5958 | 0.9978 | 0.998 | 12 | 2.06 | 1.869 / 2.967 / 13.249 | 2476.9 | 59.7 | 147571 | 0.0 |
| `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` | 5763 | 0.9976 | 0.9981 | 11 | 1.975 | 1.847 / 2.778 / 7.935 | 2499.1 | 57.8 | 144025 | 0.0 |

Errors (why a model answer was not used): `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1` {'choice_out_of_range': 12}; `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` {'no_choice': 2, 'choice_out_of_range': 9}

## Run health

- `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1` engine fallbacks 0, invalid 0, degraded 0
- `llm:glm-4-flash-250414#kb=kbt3-trig,reply=reason_first,elements=1,facts=1` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
