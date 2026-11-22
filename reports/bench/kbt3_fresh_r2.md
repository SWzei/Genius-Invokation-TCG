# Benchmark `kbt3_fresh_r2` — suite `lite_fresh` (0a81f37d495a1501)

- cells: 56 (ladder-pool 32, heldout-native 16, heldout-latest 8); seed base 7100001
- generated: 2026-11-22T05:10:00; stopped: None; model calls 6227, cost 1.816194

## Win rate (Wilson 95%)

| subject | valid / games | overall | L0-random | L1-heuristic | L2-expert |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 56 / 56 | 0.768 [0.64, 0.86] (n=56) | 0.938 [0.72, 0.99] (n=16) | 0.792 [0.60, 0.91] (n=24) | 0.562 [0.33, 0.77] (n=16) |
| `llm:deepseek-flash` | 56 / 56 | 0.705 [0.58, 0.81] (n=56) | 0.906 [0.68, 0.98] (n=16) | 0.792 [0.60, 0.91] (n=24) | 0.375 [0.18, 0.61] (n=16) |

## By group

| subject | heldout-latest | heldout-native | ladder-pool |
|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 0.875 [0.53, 0.98] (n=8) | 0.750 [0.51, 0.90] (n=16) | 0.750 [0.58, 0.87] (n=32) |
| `llm:deepseek-flash` | 0.500 [0.22, 0.78] (n=8) | 0.906 [0.68, 0.98] (n=16) | 0.656 [0.48, 0.80] (n=32) |

## By deck kind

| subject | human | pool |
|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 0.792 [0.60, 0.91] (n=24) | 0.750 [0.58, 0.87] (n=32) |
| `llm:deepseek-flash` | 0.771 [0.57, 0.89] (n=24) | 0.656 [0.48, 0.80] (n=32) |

## By rules version

| subject | default | v6.3.0 |
|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 0.775 [0.62, 0.88] (n=40) | 0.750 [0.51, 0.90] (n=16) |
| `llm:deepseek-flash` | 0.625 [0.47, 0.76] (n=40) | 0.906 [0.68, 0.98] (n=16) |

## Paired difference vs `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` (same cells)

| subject | pairs | delta | 95% CI | better / worse / same | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash` | 56 | -0.062 | [-0.17, +0.05] | 5 / 9 / 42 | 0.424 |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 3114 | 1.0 | 1.0 | 0 | 1.093 | 1.071 / 1.246 / 4.103 | 2634.8 | 55.6 | 146513 | 0.021469 |
| `llm:deepseek-flash` | 3095 | 0.9942 | 1.0 | 0 | 0.917 | 0.888 / 1.049 / 3.298 | 1415.6 | 55.6 | 78240 | 0.010963 |

Errors (why a model answer was not used): `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` {}; `llm:deepseek-flash` {}

## Run health

- `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` engine fallbacks 0, invalid 0, degraded 0
- `llm:deepseek-flash` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
