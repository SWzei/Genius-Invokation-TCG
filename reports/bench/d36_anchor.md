# Benchmark `d36_anchor` — suite `anchor` (77f4eabf75b1b957)

- cells: 32 (anchor-expert 32); seed base 7100001
- generated: 2026-11-23T06:10:10; stopped: None; model calls 1702, cost 0.696291

## Win rate (Wilson 95%)

| subject | valid / games | overall | L2-expert |
|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 32 / 32 | 0.438 [0.28, 0.61] (n=32) | 0.438 [0.28, 0.61] (n=32) |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 1702 | 1.0 | 1.0 | 0 | 1.464 | 1.421 / 1.815 / 5.054 | 2619.0 | 53.2 | 139300 | 0.021759 |

Errors (why a model answer was not used): `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` {}

## Run health

- `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
