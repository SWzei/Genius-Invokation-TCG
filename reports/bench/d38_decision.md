# Benchmark `d38_decision` — suite `mirror_dev200` (7783c19b2a879a6f)

- cells: 400 (mirror-dev 400); seed base 7100001
- generated: 2026-11-24T05:04:32; stopped: None; model calls 9047, cost 2.227401

## Win rate (Wilson 95%)

| subject | valid / games | overall | model |
|---|---|---|---|
| `llm:gemini-decision-1#kb=kbt3-trig,elements=1` | 100 / 100 | 0.525 [0.43, 0.62] (n=100) | 0.525 [0.43, 0.62] (n=100) |

## By rules version

| subject | v6.2.0 | v6.3.0 |
|---|---|---|
| `llm:gemini-decision-1#kb=kbt3-trig,elements=1` | 0.600 [0.46, 0.72] (n=50) | 0.450 [0.32, 0.59] (n=50) |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:gemini-decision-1#kb=kbt3-trig,elements=1` | 4544 | 1.0 | 1.0 | 0 | 6.348 | 0.386 / 53.761 / 61.573 | 3065.2 | 45.4 | 139283 | 0.013928 |

Errors (why a model answer was not used): `llm:gemini-decision-1#kb=kbt3-trig,elements=1` {}

## Run health

- `llm:gemini-decision-1#kb=kbt3-trig,elements=1` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
