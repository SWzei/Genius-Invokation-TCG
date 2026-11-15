# Benchmark `home_refs` — suite `home` (f35aac2ff5744995)

- cells: 16 (ladder-home 16); seed base 7100001
- generated: 2026-11-14T23:36:55; stopped: None; model calls 0, cost 0.0

## Win rate (Wilson 95%)

| subject | valid / games | overall | L0-random | L1-heuristic | L2-expert |
|---|---|---|---|---|---|
| `neural:data/ckpt/bc_dgn_b0.pt#t=0` | 16 / 16 | 0.812 [0.57, 0.93] (n=16) | 1.000 [0.51, 1.00] (n=4) | 0.750 [0.30, 0.95] (n=4) | 0.750 [0.41, 0.93] (n=8) |
| `expert:<deck>` | 16 / 16 | 0.750 [0.51, 0.90] (n=16) | 1.000 [0.51, 1.00] (n=4) | 0.500 [0.15, 0.85] (n=4) | 0.750 [0.41, 0.93] (n=8) |
| `heuristic` | 16 / 16 | 0.625 [0.39, 0.82] (n=16) | 1.000 [0.51, 1.00] (n=4) | 0.500 [0.15, 0.85] (n=4) | 0.500 [0.22, 0.78] (n=8) |
| `legal_random` | 16 / 16 | 0.125 [0.04, 0.36] (n=16) | 0.500 [0.15, 0.85] (n=4) | 0.000 [0.00, 0.49] (n=4) | 0.000 [0.00, 0.32] (n=8) |

## Paired difference vs `neural:data/ckpt/bc_dgn_b0.pt#t=0` (same cells)

| subject | pairs | delta | 95% CI | better / worse / same | sign test p |
|---|---|---|---|---|---|
| `expert:<deck>` | 16 | -0.062 | [-0.34, +0.22] | 2 / 3 / 11 | 1.000 |
| `heuristic` | 16 | -0.188 | [-0.39, +0.01] | 0 / 3 / 13 | 0.250 |
| `legal_random` | 16 | -0.688 | [-0.90, -0.47] | 0 / 12 / 4 | 0.001 |

## Run health

- `neural:data/ckpt/bc_dgn_b0.pt#t=0` engine fallbacks 0, invalid 0, degraded 0
- `expert:<deck>` engine fallbacks 0, invalid 0, degraded 0
- `heuristic` engine fallbacks 0, invalid 0, degraded 0
- `legal_random` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
