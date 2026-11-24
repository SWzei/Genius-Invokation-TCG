# Benchmark `d36_test_obs` — suite `mirror_test150` (239c723ee5dd3858)

- cells: 300 (mirror-test 300); seed base 7100001
- generated: 2026-11-23T06:01:06; stopped: None; model calls 17001, cost 4.001442

## Win rate (Wilson 95%)

| subject | valid / games | overall | model |
|---|---|---|---|
| `llm:deepseek-flash#reply=reason_first,elements=1` | 160 / 160 | 0.584 [0.51, 0.66] (n=160) | 0.584 [0.51, 0.66] (n=160) |

## By rules version

| subject | v6.2.0 | v6.3.0 |
|---|---|---|
| `llm:deepseek-flash#reply=reason_first,elements=1` | 0.600 [0.49, 0.70] (n=80) | 0.569 [0.46, 0.67] (n=80) |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash#reply=reason_first,elements=1` | 8581 | 1.0 | 1.0 | 0 | 1.471 | 1.425 / 1.857 / 4.991 | 1478.3 | 53.6 | 79280 | 0.012547 |

Errors (why a model answer was not used): `llm:deepseek-flash#reply=reason_first,elements=1` {}

## Run health

- `llm:deepseek-flash#reply=reason_first,elements=1` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
