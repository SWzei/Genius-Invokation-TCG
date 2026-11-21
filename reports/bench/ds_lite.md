# Benchmark `ds_lite` — suite `lite` (2b88ef20714c8993)

- cells: 56 (ladder-pool 32, heldout-native 16, heldout-latest 8); seed base 7100001
- generated: 2026-11-21T00:13:35; stopped: None; model calls 12109, cost 3.921061

## Win rate (Wilson 95%)

| subject | valid / games | overall | L0-random | L1-heuristic | L2-expert |
|---|---|---|---|---|---|
| `llm:deepseek-flash` | 56 / 56 | 0.688 [0.56, 0.79] (n=56) | 0.969 [0.76, 1.00] (n=16) | 0.708 [0.51, 0.85] (n=24) | 0.375 [0.18, 0.61] (n=16) |
| `llm:deepseek-flash#kb=rules` | 56 / 56 | 0.732 [0.60, 0.83] (n=56) | 1.000 [0.81, 1.00] (n=16) | 0.708 [0.51, 0.85] (n=24) | 0.500 [0.28, 0.72] (n=16) |
| `llm:deepseek-flash#kb=rules-strategy` | 56 / 56 | 0.768 [0.64, 0.86] (n=56) | 0.938 [0.72, 0.99] (n=16) | 0.875 [0.69, 0.96] (n=24) | 0.438 [0.23, 0.67] (n=16) |
| `llm:deepseek-flash#kb=rules-strategy-full` | 56 / 56 | 0.786 [0.66, 0.87] (n=56) | 1.000 [0.81, 1.00] (n=16) | 0.875 [0.69, 0.96] (n=24) | 0.438 [0.23, 0.67] (n=16) |

## By group

| subject | heldout-latest | heldout-native | ladder-pool |
|---|---|---|---|
| `llm:deepseek-flash` | 0.812 [0.47, 0.96] (n=8) | 0.781 [0.54, 0.92] (n=16) | 0.609 [0.44, 0.76] (n=32) |
| `llm:deepseek-flash#kb=rules` | 0.750 [0.41, 0.93] (n=8) | 0.812 [0.57, 0.93] (n=16) | 0.688 [0.51, 0.82] (n=32) |
| `llm:deepseek-flash#kb=rules-strategy` | 1.000 [0.68, 1.00] (n=8) | 0.812 [0.57, 0.93] (n=16) | 0.688 [0.51, 0.82] (n=32) |
| `llm:deepseek-flash#kb=rules-strategy-full` | 0.875 [0.53, 0.98] (n=8) | 0.875 [0.64, 0.96] (n=16) | 0.719 [0.55, 0.84] (n=32) |

## By deck kind

| subject | human | pool |
|---|---|---|
| `llm:deepseek-flash` | 0.792 [0.60, 0.91] (n=24) | 0.609 [0.44, 0.76] (n=32) |
| `llm:deepseek-flash#kb=rules` | 0.792 [0.60, 0.91] (n=24) | 0.688 [0.51, 0.82] (n=32) |
| `llm:deepseek-flash#kb=rules-strategy` | 0.875 [0.69, 0.96] (n=24) | 0.688 [0.51, 0.82] (n=32) |
| `llm:deepseek-flash#kb=rules-strategy-full` | 0.875 [0.69, 0.96] (n=24) | 0.719 [0.55, 0.84] (n=32) |

## By rules version

| subject | default | v6.3.0 |
|---|---|---|
| `llm:deepseek-flash` | 0.650 [0.50, 0.78] (n=40) | 0.781 [0.54, 0.92] (n=16) |
| `llm:deepseek-flash#kb=rules` | 0.700 [0.55, 0.82] (n=40) | 0.812 [0.57, 0.93] (n=16) |
| `llm:deepseek-flash#kb=rules-strategy` | 0.750 [0.60, 0.86] (n=40) | 0.812 [0.57, 0.93] (n=16) |
| `llm:deepseek-flash#kb=rules-strategy-full` | 0.750 [0.60, 0.86] (n=40) | 0.875 [0.64, 0.96] (n=16) |

## Paired difference vs `llm:deepseek-flash` (same cells)

| subject | pairs | delta | 95% CI | better / worse / same | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=rules` | 56 | +0.045 | [-0.03, +0.12] | 5 / 2 / 49 | 0.453 |
| `llm:deepseek-flash#kb=rules-strategy` | 56 | +0.080 | [-0.01, +0.17] | 8 / 3 / 45 | 0.227 |
| `llm:deepseek-flash#kb=rules-strategy-full` | 56 | +0.098 | [-0.00, +0.20] | 9 / 2 / 45 | 0.065 |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 3056 | 0.9954 | 1.0 | 0 | 1.155 | 1.102 / 1.469 / 6.45 | 1384.3 | 54.8 | 75543 | 0.01166 |
| `llm:deepseek-flash#kb=rules` | 3047 | 0.9984 | 1.0 | 0 | 1.172 | 1.116 / 1.492 / 3.297 | 2108.8 | 54.5 | 114744 | 0.017226 |
| `llm:deepseek-flash#kb=rules-strategy` | 3006 | 0.9987 | 1.0 | 0 | 1.187 | 1.127 / 1.511 / 9.137 | 2555.3 | 53.8 | 137166 | 0.020342 |
| `llm:deepseek-flash#kb=rules-strategy-full` | 2977 | 1.0 | 1.0 | 0 | 1.192 | 1.12 / 1.514 / 8.134 | 2726.3 | 53.2 | 144932 | 0.02079 |

Errors (why a model answer was not used): `llm:deepseek-flash` {}; `llm:deepseek-flash#kb=rules` {}; `llm:deepseek-flash#kb=rules-strategy` {}; `llm:deepseek-flash#kb=rules-strategy-full` {}

## Run health

- `llm:deepseek-flash` engine fallbacks 2, invalid 0, degraded 0
- `llm:deepseek-flash#kb=rules` engine fallbacks 0, invalid 0, degraded 0
- `llm:deepseek-flash#kb=rules-strategy` engine fallbacks 0, invalid 0, degraded 0
- `llm:deepseek-flash#kb=rules-strategy-full` engine fallbacks 1, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
