# Benchmark `kbt3_fresh_r1` — suite `lite_fresh` (0a81f37d495a1501)

- cells: 56 (ladder-pool 32, heldout-native 16, heldout-latest 8); seed base 7100001
- generated: 2026-11-22T04:25:57; stopped: None; model calls 6164, cost 1.915672

## Win rate (Wilson 95%)

| subject | valid / games | overall | L0-random | L1-heuristic | L2-expert |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 56 / 56 | 0.768 [0.64, 0.86] (n=56) | 0.969 [0.76, 1.00] (n=16) | 0.812 [0.62, 0.92] (n=24) | 0.500 [0.28, 0.72] (n=16) |
| `llm:deepseek-flash` | 56 / 56 | 0.786 [0.66, 0.87] (n=56) | 0.938 [0.72, 0.99] (n=16) | 0.875 [0.69, 0.96] (n=24) | 0.500 [0.28, 0.72] (n=16) |

## By group

| subject | heldout-latest | heldout-native | ladder-pool |
|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 0.812 [0.47, 0.96] (n=8) | 0.875 [0.64, 0.96] (n=16) | 0.703 [0.53, 0.83] (n=32) |
| `llm:deepseek-flash` | 0.750 [0.41, 0.93] (n=8) | 0.906 [0.68, 0.98] (n=16) | 0.734 [0.56, 0.86] (n=32) |

## By deck kind

| subject | human | pool |
|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 0.854 [0.67, 0.95] (n=24) | 0.703 [0.53, 0.83] (n=32) |
| `llm:deepseek-flash` | 0.854 [0.67, 0.95] (n=24) | 0.734 [0.56, 0.86] (n=32) |

## By rules version

| subject | default | v6.3.0 |
|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 0.725 [0.57, 0.84] (n=40) | 0.875 [0.64, 0.96] (n=16) |
| `llm:deepseek-flash` | 0.738 [0.58, 0.85] (n=40) | 0.906 [0.68, 0.98] (n=16) |

## Paired difference vs `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` (same cells)

| subject | pairs | delta | 95% CI | better / worse / same | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash` | 56 | +0.018 | [-0.09, +0.13] | 7 / 6 / 43 | 1.000 |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 3085 | 1.0 | 1.0 | 0 | 1.16 | 1.076 / 1.27 / 2.366 | 2622.7 | 55.1 | 144484 | 0.022421 |
| `llm:deepseek-flash` | 3059 | 0.9935 | 1.0 | 0 | 0.97 | 0.899 / 1.056 / 2.459 | 1421.0 | 55.0 | 77622 | 0.011787 |

Errors (why a model answer was not used): `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` {}; `llm:deepseek-flash` {}

## Run health

- `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` engine fallbacks 0, invalid 0, degraded 0
- `llm:deepseek-flash` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
