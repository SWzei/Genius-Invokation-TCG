# Benchmark `kbt_lite_r2` — suite `lite` (2b88ef20714c8993)

- cells: 56 (ladder-pool 32, heldout-native 16, heldout-latest 8); seed base 7100001
- generated: 2026-11-21T21:24:50; stopped: None; model calls 2909, cost 1.117447

## Win rate (Wilson 95%)

| subject | valid / games | overall | L0-random | L1-heuristic | L2-expert |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 56 / 56 | 0.812 [0.69, 0.89] (n=56) | 0.969 [0.76, 1.00] (n=16) | 0.917 [0.74, 0.98] (n=24) | 0.500 [0.28, 0.72] (n=16) |

## By group

| subject | heldout-latest | heldout-native | ladder-pool |
|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 0.875 [0.53, 0.98] (n=8) | 0.938 [0.72, 0.99] (n=16) | 0.734 [0.56, 0.86] (n=32) |

## By deck kind

| subject | human | pool |
|---|---|---|
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 0.917 [0.74, 0.98] (n=24) | 0.734 [0.56, 0.86] (n=32) |

## By rules version

| subject | default | v6.3.0 |
|---|---|---|
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 0.762 [0.61, 0.87] (n=40) | 0.938 [0.72, 0.99] (n=16) |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 2908 | 0.9997 | 1.0 | 0 | 1.546 | 1.497 / 1.894 / 5.699 | 2656.3 | 51.9 | 137936 | 0.019954 |

Errors (why a model answer was not used): `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` {}

## Run health

- `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
