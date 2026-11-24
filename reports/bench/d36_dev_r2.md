# Benchmark `d36_dev_r2` — suite `mirror_dev` (6ae1f20b9de20953)

- cells: 200 (mirror-dev 200); seed base 7100001
- generated: 2026-11-23T03:46:28; stopped: None; model calls 7792, cost 2.518509

## Win rate (Wilson 95%)

| subject | valid / games | overall | model |
|---|---|---|---|
| `llm:deepseek-flash#kb=kbt6-r2,reply=reason_first,elements=1` | 80 / 80 | 0.450 [0.35, 0.56] (n=80) | 0.450 [0.35, 0.56] (n=80) |

## By rules version

| subject | v6.2.0 | v6.3.0 |
|---|---|---|
| `llm:deepseek-flash#kb=kbt6-r2,reply=reason_first,elements=1` | 0.525 [0.38, 0.67] (n=40) | 0.375 [0.24, 0.53] (n=40) |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt6-r2,reply=reason_first,elements=1` | 3881 | 0.9997 | 1.0 | 0 | 1.424 | 1.378 / 1.76 / 3.622 | 2658.1 | 48.5 | 128951 | 0.020138 |

Errors (why a model answer was not used): `llm:deepseek-flash#kb=kbt6-r2,reply=reason_first,elements=1` {}

## Run health

- `llm:deepseek-flash#kb=kbt6-r2,reply=reason_first,elements=1` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
