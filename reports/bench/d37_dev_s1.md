# Benchmark `d37_dev_s1` — suite `mirror_dev200` (7783c19b2a879a6f)

- cells: 400 (mirror-dev 400); seed base 7100001
- generated: 2026-11-23T13:39:37; stopped: None; model calls 3828, cost 1.559112

## Win rate (Wilson 95%)

| subject | valid / games | overall | model |
|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | 40 / 40 | 0.450 [0.31, 0.60] (n=40) | 0.450 [0.31, 0.60] (n=40) |

## By rules version

| subject | v6.2.0 | v6.3.0 |
|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | 0.450 [0.26, 0.66] (n=20) | 0.450 [0.26, 0.66] (n=20) |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | 1919 | 1.0 | 1.0 | 0 | 1.37 | 1.337 / 1.713 / 3.315 | 3520.6 | 48.0 | 168899 | 0.019894 |

Errors (why a model answer was not used): `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` {}

## Run health

- `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
