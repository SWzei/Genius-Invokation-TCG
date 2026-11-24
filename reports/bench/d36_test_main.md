# Benchmark `d36_test_main` — suite `mirror_test150` (239c723ee5dd3858)

- cells: 300 (mirror-test 300); seed base 7100001
- generated: 2026-11-23T06:15:22; stopped: None; model calls 32822, cost 10.630641

## Win rate (Wilson 95%)

| subject | valid / games | overall | model |
|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 300 / 300 | 0.535 [0.48, 0.59] (n=300) | 0.535 [0.48, 0.59] (n=300) |

## By rules version

| subject | v6.2.0 | v6.3.0 |
|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 0.540 [0.46, 0.62] (n=150) | 0.530 [0.45, 0.61] (n=150) |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 16600 | 0.9999 | 1.0 | 0 | 1.495 | 1.453 / 1.869 / 4.608 | 2617.6 | 55.3 | 144843 | 0.022566 |

Errors (why a model answer was not used): `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` {}

## Run health

- `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
