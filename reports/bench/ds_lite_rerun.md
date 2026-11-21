# Benchmark `ds_lite_rerun` — suite `lite` (2b88ef20714c8993)

- cells: 56 (ladder-pool 32, heldout-native 16, heldout-latest 8); seed base 7100001
- generated: 2026-11-21T00:32:00; stopped: None; model calls 3001, cost 0.562906

## Win rate (Wilson 95%)

| subject | valid / games | overall | L0-random | L1-heuristic | L2-expert |
|---|---|---|---|---|---|
| `llm:deepseek-flash` | 56 / 56 | 0.786 [0.66, 0.87] (n=56) | 1.000 [0.81, 1.00] (n=16) | 0.917 [0.74, 0.98] (n=24) | 0.375 [0.18, 0.61] (n=16) |

## By group

| subject | heldout-latest | heldout-native | ladder-pool |
|---|---|---|---|
| `llm:deepseek-flash` | 1.000 [0.68, 1.00] (n=8) | 0.875 [0.64, 0.96] (n=16) | 0.688 [0.51, 0.82] (n=32) |

## By deck kind

| subject | human | pool |
|---|---|---|
| `llm:deepseek-flash` | 0.917 [0.74, 0.98] (n=24) | 0.688 [0.51, 0.82] (n=32) |

## By rules version

| subject | default | v6.3.0 |
|---|---|---|
| `llm:deepseek-flash` | 0.750 [0.60, 0.86] (n=40) | 0.875 [0.64, 0.96] (n=16) |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 2979 | 0.9926 | 1.0 | 0 | 1.195 | 1.138 / 1.521 / 9.379 | 1405.0 | 53.6 | 74740 | 0.010052 |

Errors (why a model answer was not used): `llm:deepseek-flash` {}

## Run health

- `llm:deepseek-flash` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
