# Benchmark `lite_all` — suite `lite` (2b88ef20714c8993)

- cells: 56 (ladder-pool 32, heldout-native 16, heldout-latest 8); seed base 7100001
- generated: 2026-11-15T13:36:28; stopped: None; model calls 0, cost 0

## Win rate (Wilson 95%)

| subject | valid / games | overall | L0-random | L1-heuristic | L2-expert |
|---|---|---|---|---|---|
| `llm:glm-53-plan` | 28 / 28 | 0.929 [0.77, 0.98] (n=28) | 1.000 [0.68, 1.00] (n=8) | 1.000 [0.76, 1.00] (n=12) | 0.750 [0.41, 0.93] (n=8) |
| `llm:glm-53-plan#kb=rules` | 28 / 28 | 0.857 [0.69, 0.94] (n=28) | 1.000 [0.68, 1.00] (n=8) | 1.000 [0.76, 1.00] (n=12) | 0.500 [0.22, 0.78] (n=8) |
| `llm:glm-53-plan#kb=rules-strategy` | 28 / 28 | 0.786 [0.60, 0.90] (n=28) | 1.000 [0.68, 1.00] (n=8) | 0.833 [0.55, 0.95] (n=12) | 0.500 [0.22, 0.78] (n=8) |
| `heuristic` | 28 / 28 | 0.518 [0.34, 0.69] (n=28) | 0.812 [0.47, 0.96] (n=8) | 0.500 [0.25, 0.75] (n=12) | 0.250 [0.07, 0.59] (n=8) |
| `expert:<deck>` | 16 / 16 | 0.656 [0.41, 0.84] (n=16) | 1.000 [0.51, 1.00] (n=4) | 0.875 [0.40, 0.99] (n=4) | 0.375 [0.14, 0.69] (n=8) |
| `legal_random` | 28 / 28 | 0.250 [0.13, 0.43] (n=28) | 0.562 [0.26, 0.83] (n=8) | 0.208 [0.07, 0.49] (n=12) | 0.000 [0.00, 0.32] (n=8) |

## By group

| subject | heldout-latest | heldout-native | ladder-pool |
|---|---|---|---|
| `llm:glm-53-plan` | 1.000 [0.51, 1.00] (n=4) | 1.000 [0.68, 1.00] (n=8) | 0.875 [0.64, 0.96] (n=16) |
| `llm:glm-53-plan#kb=rules` | 1.000 [0.51, 1.00] (n=4) | 1.000 [0.68, 1.00] (n=8) | 0.750 [0.51, 0.90] (n=16) |
| `llm:glm-53-plan#kb=rules-strategy` | 1.000 [0.51, 1.00] (n=4) | 0.750 [0.41, 0.93] (n=8) | 0.750 [0.51, 0.90] (n=16) |
| `heuristic` | 0.500 [0.15, 0.85] (n=4) | 0.625 [0.31, 0.86] (n=8) | 0.469 [0.26, 0.69] (n=16) |
| `expert:<deck>` | — | — | 0.656 [0.41, 0.84] (n=16) |
| `legal_random` | 0.250 [0.05, 0.70] (n=4) | 0.438 [0.17, 0.74] (n=8) | 0.156 [0.05, 0.40] (n=16) |

## By deck kind

| subject | human | pool |
|---|---|---|
| `llm:glm-53-plan` | 1.000 [0.76, 1.00] (n=12) | 0.875 [0.64, 0.96] (n=16) |
| `llm:glm-53-plan#kb=rules` | 1.000 [0.76, 1.00] (n=12) | 0.750 [0.51, 0.90] (n=16) |
| `llm:glm-53-plan#kb=rules-strategy` | 0.833 [0.55, 0.95] (n=12) | 0.750 [0.51, 0.90] (n=16) |
| `heuristic` | 0.583 [0.32, 0.81] (n=12) | 0.469 [0.26, 0.69] (n=16) |
| `expert:<deck>` | — | 0.656 [0.41, 0.84] (n=16) |
| `legal_random` | 0.375 [0.17, 0.65] (n=12) | 0.156 [0.05, 0.40] (n=16) |

## By rules version

| subject | default | v6.3.0 |
|---|---|---|
| `llm:glm-53-plan` | 0.900 [0.70, 0.97] (n=20) | 1.000 [0.68, 1.00] (n=8) |
| `llm:glm-53-plan#kb=rules` | 0.800 [0.58, 0.92] (n=20) | 1.000 [0.68, 1.00] (n=8) |
| `llm:glm-53-plan#kb=rules-strategy` | 0.800 [0.58, 0.92] (n=20) | 0.750 [0.41, 0.93] (n=8) |
| `heuristic` | 0.475 [0.28, 0.68] (n=20) | 0.625 [0.31, 0.86] (n=8) |
| `expert:<deck>` | 0.656 [0.41, 0.84] (n=16) | — |
| `legal_random` | 0.175 [0.07, 0.39] (n=20) | 0.438 [0.17, 0.74] (n=8) |

## Paired difference vs `llm:glm-53-plan` (same cells)

| subject | pairs | delta | 95% CI | better / worse / same | sign test p |
|---|---|---|---|---|---|
| `llm:glm-53-plan#kb=rules` | 28 | -0.071 | [-0.17, +0.03] | 0 / 2 / 26 | 0.500 |
| `llm:glm-53-plan#kb=rules-strategy` | 28 | -0.143 | [-0.27, -0.01] | 0 / 4 / 24 | 0.125 |
| `heuristic` | 28 | -0.411 | [-0.59, -0.24] | 0 / 13 / 15 | 0.000 |
| `expert:<deck>` | 16 | -0.219 | [-0.42, -0.02] | 0 / 4 / 12 | 0.125 |
| `legal_random` | 28 | -0.679 | [-0.81, -0.54] | 0 / 24 / 4 | 0.000 |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:glm-53-plan` | 1406 | 0.9964 | 1.0 | 0 | 4.215 | 3.588 / 6.558 / 45.081 | 1540.4 | 50.4 | 77352 | 0.120254 |
| `llm:glm-53-plan#kb=rules` | 1482 | 0.9987 | 1.0 | 0 | 5.384 | 4.4 / 8.568 / 45.468 | 2381.4 | 53.0 | 126046 | 0.193317 |
| `llm:glm-53-plan#kb=rules-strategy` | 1460 | 0.9938 | 1.0 | 0 | 4.871 | 3.907 / 7.967 / 46.218 | 2763.1 | 52.5 | 144075 | 0.219064 |

Errors (why a model answer was not used): `llm:glm-53-plan` {}; `llm:glm-53-plan#kb=rules` {}; `llm:glm-53-plan#kb=rules-strategy` {}

## Run health

- `llm:glm-53-plan` engine fallbacks 0, invalid 0, degraded 0
- `llm:glm-53-plan#kb=rules` engine fallbacks 0, invalid 0, degraded 0
- `llm:glm-53-plan#kb=rules-strategy` engine fallbacks 0, invalid 0, degraded 0
- `heuristic` engine fallbacks 0, invalid 0, degraded 0
- `expert:<deck>` engine fallbacks 0, invalid 0, degraded 0
- `legal_random` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
