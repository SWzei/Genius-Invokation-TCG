# Benchmark `kbt_lite_r1` — suite `lite` (2b88ef20714c8993)

- cells: 56 (ladder-pool 32, heldout-native 16, heldout-latest 8); seed base 7100001
- generated: 2026-11-21T21:02:33; stopped: None; model calls 9110, cost 2.812834

## Win rate (Wilson 95%)

| subject | valid / games | overall | L0-random | L1-heuristic | L2-expert |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 56 / 56 | 0.830 [0.71, 0.91] (n=56) | 1.000 [0.81, 1.00] (n=16) | 0.854 [0.67, 0.95] (n=24) | 0.625 [0.39, 0.82] (n=16) |
| `llm:deepseek-flash` | 56 / 56 | 0.768 [0.64, 0.86] (n=56) | 1.000 [0.81, 1.00] (n=16) | 0.833 [0.64, 0.93] (n=24) | 0.438 [0.23, 0.67] (n=16) |
| `llm:deepseek-flash#kb=kbt-s0` | 56 / 56 | 0.786 [0.66, 0.87] (n=56) | 0.969 [0.76, 1.00] (n=16) | 0.812 [0.62, 0.92] (n=24) | 0.562 [0.33, 0.77] (n=16) |

## By group

| subject | heldout-latest | heldout-native | ladder-pool |
|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 0.688 [0.36, 0.90] (n=8) | 1.000 [0.81, 1.00] (n=16) | 0.781 [0.61, 0.89] (n=32) |
| `llm:deepseek-flash` | 0.750 [0.41, 0.93] (n=8) | 0.875 [0.64, 0.96] (n=16) | 0.719 [0.55, 0.84] (n=32) |
| `llm:deepseek-flash#kb=kbt-s0` | 0.812 [0.47, 0.96] (n=8) | 0.781 [0.54, 0.92] (n=16) | 0.781 [0.61, 0.89] (n=32) |

## By deck kind

| subject | human | pool |
|---|---|---|
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 0.896 [0.72, 0.97] (n=24) | 0.781 [0.61, 0.89] (n=32) |
| `llm:deepseek-flash` | 0.833 [0.64, 0.93] (n=24) | 0.719 [0.55, 0.84] (n=32) |
| `llm:deepseek-flash#kb=kbt-s0` | 0.792 [0.60, 0.91] (n=24) | 0.781 [0.61, 0.89] (n=32) |

## By rules version

| subject | default | v6.3.0 |
|---|---|---|
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 0.762 [0.61, 0.87] (n=40) | 1.000 [0.81, 1.00] (n=16) |
| `llm:deepseek-flash` | 0.725 [0.57, 0.84] (n=40) | 0.875 [0.64, 0.96] (n=16) |
| `llm:deepseek-flash#kb=kbt-s0` | 0.787 [0.64, 0.89] (n=40) | 0.781 [0.54, 0.92] (n=16) |

## Paired difference vs `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` (same cells)

| subject | pairs | delta | 95% CI | better / worse / same | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash` | 56 | -0.062 | [-0.15, +0.02] | 2 / 5 / 49 | 0.453 |
| `llm:deepseek-flash#kb=kbt-s0` | 56 | -0.045 | [-0.13, +0.04] | 2 / 5 / 49 | 0.453 |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 3090 | 0.9997 | 1.0 | 0 | 1.479 | 1.437 / 1.855 / 2.895 | 2659.0 | 55.2 | 146721 | 0.022545 |
| `llm:deepseek-flash` | 2983 | 0.994 | 1.0 | 0 | 1.226 | 1.174 / 1.577 / 4.776 | 1401.4 | 53.6 | 74649 | 0.00909 |
| `llm:deepseek-flash#kb=kbt-s0` | 3015 | 0.999 | 1.0 | 0 | 1.258 | 1.213 / 1.593 / 3.031 | 2576.9 | 53.9 | 138741 | 0.018594 |

Errors (why a model answer was not used): `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` {}; `llm:deepseek-flash` {}; `llm:deepseek-flash#kb=kbt-s0` {}

## Run health

- `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` engine fallbacks 0, invalid 0, degraded 0
- `llm:deepseek-flash` engine fallbacks 0, invalid 0, degraded 0
- `llm:deepseek-flash#kb=kbt-s0` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
