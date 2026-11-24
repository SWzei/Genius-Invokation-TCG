# Benchmark `d37_cross` — suite `mirror_dev200` (7783c19b2a879a6f)

- cells: 400 (mirror-dev 400); seed base 7100001
- generated: 2026-11-23T14:17:38; stopped: None; model calls 3979, cost 1.378539

## Win rate (Wilson 95%)

| subject | valid / games | overall | model |
|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 20 / 20 | 0.500 [0.30, 0.70] (n=20) | 0.500 [0.30, 0.70] (n=20) |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | 20 / 20 | 0.450 [0.26, 0.66] (n=20) | 0.450 [0.26, 0.66] (n=20) |

## By rules version

| subject | v6.2.0 | v6.3.0 |
|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 0.500 [0.24, 0.76] (n=10) | 0.500 [0.24, 0.76] (n=10) |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | 0.400 [0.17, 0.69] (n=10) | 0.500 [0.24, 0.76] (n=10) |

## Paired difference vs `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` (same cells)

| subject | pairs | delta | 95% CI | better / worse / same | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | 20 | -0.050 | [-0.27, +0.17] | 2 / 3 / 15 | 1.000 |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 981 | 1.0 | 1.0 | 0 | 1.384 | 1.335 / 1.803 / 2.635 | 2497.4 | 49.0 | 122497 | 0.019169 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | 945 | 1.0 | 1.0 | 0 | 1.43 | 1.428 / 1.786 / 4.814 | 3561.6 | 47.2 | 168284 | 0.019609 |

Errors (why a model answer was not used): `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` {}; `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` {}

## Run health

- `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` engine fallbacks 0, invalid 0, degraded 0
- `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
