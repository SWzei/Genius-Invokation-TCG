# Benchmark `lite_refs` — suite `lite` (2b88ef20714c8993)

- cells: 56 (ladder-pool 32, heldout-native 16, heldout-latest 8); seed base 7100001
- generated: 2026-11-14T14:06:08; stopped: None; model calls 0, cost 0.0

## Win rate (Wilson 95%)

| subject | valid / games | overall | L0-random | L1-heuristic | L2-expert |
|---|---|---|---|---|---|
| `heuristic` | 56 / 56 | 0.482 [0.36, 0.61] (n=56) | 0.812 [0.57, 0.93] (n=16) | 0.500 [0.31, 0.69] (n=24) | 0.125 [0.04, 0.36] (n=16) |
| `legal_random` | 56 / 56 | 0.268 [0.17, 0.40] (n=56) | 0.562 [0.33, 0.77] (n=16) | 0.208 [0.09, 0.40] (n=24) | 0.062 [0.01, 0.28] (n=16) |
| `expert:<deck>` | 32 / 32 | 0.625 [0.45, 0.77] (n=32) | 0.938 [0.60, 0.99] (n=8) | 0.812 [0.47, 0.96] (n=8) | 0.375 [0.18, 0.61] (n=16) |

## By group

| subject | heldout-latest | heldout-native | ladder-pool |
|---|---|---|---|
| `heuristic` | 0.500 [0.22, 0.78] (n=8) | 0.625 [0.39, 0.82] (n=16) | 0.406 [0.26, 0.58] (n=32) |
| `legal_random` | 0.250 [0.07, 0.59] (n=8) | 0.438 [0.23, 0.67] (n=16) | 0.188 [0.09, 0.35] (n=32) |
| `expert:<deck>` | — | — | 0.625 [0.45, 0.77] (n=32) |

## By deck kind

| subject | human | pool |
|---|---|---|
| `heuristic` | 0.583 [0.39, 0.76] (n=24) | 0.406 [0.26, 0.58] (n=32) |
| `legal_random` | 0.375 [0.21, 0.57] (n=24) | 0.188 [0.09, 0.35] (n=32) |
| `expert:<deck>` | — | 0.625 [0.45, 0.77] (n=32) |

## By rules version

| subject | default | v6.3.0 |
|---|---|---|
| `heuristic` | 0.425 [0.29, 0.58] (n=40) | 0.625 [0.39, 0.82] (n=16) |
| `legal_random` | 0.200 [0.10, 0.35] (n=40) | 0.438 [0.23, 0.67] (n=16) |
| `expert:<deck>` | 0.625 [0.45, 0.77] (n=32) | — |

## Paired difference vs `heuristic` (same cells)

| subject | pairs | delta | 95% CI | better / worse / same | sign test p |
|---|---|---|---|---|---|
| `legal_random` | 56 | -0.214 | [-0.33, -0.10] | 4 / 22 / 30 | 0.001 |
| `expert:<deck>` | 32 | +0.219 | [+0.07, +0.37] | 10 / 2 / 20 | 0.039 |

## Run health

- `heuristic` engine fallbacks 0, invalid 0, degraded 0
- `legal_random` engine fallbacks 0, invalid 0, degraded 0
- `expert:<deck>` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
