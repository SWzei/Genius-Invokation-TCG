# Benchmark `d36_dev_r3` — suite `mirror_dev` (6ae1f20b9de20953)

- cells: 200 (mirror-dev 200); seed base 7100001
- generated: 2026-11-23T04:43:49; stopped: None; model calls 7939, cost 2.486874

## Win rate (Wilson 95%)

| subject | valid / games | overall | model |
|---|---|---|---|
| `llm:deepseek-flash#kb=kbt6-r3,reply=reason_first,elements=1` | 80 / 80 | 0.537 [0.43, 0.64] (n=80) | 0.537 [0.43, 0.64] (n=80) |

## By rules version

| subject | v6.2.0 | v6.3.0 |
|---|---|---|
| `llm:deepseek-flash#kb=kbt6-r3,reply=reason_first,elements=1` | 0.575 [0.42, 0.71] (n=40) | 0.500 [0.35, 0.65] (n=40) |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt6-r3,reply=reason_first,elements=1` | 3999 | 0.9997 | 0.9997 | 1 | 1.458 | 1.414 / 1.829 / 3.107 | 2596.1 | 50.0 | 129772 | 0.01978 |

Errors (why a model answer was not used): `llm:deepseek-flash#kb=kbt6-r3,reply=reason_first,elements=1` {'choice_out_of_range': 1}

## Run health

- `llm:deepseek-flash#kb=kbt6-r3,reply=reason_first,elements=1` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
