# Benchmark `d37_cal_v3sb` — suite `mirror_train300same` (1d42b7ca20886d5e)

- cells: 600 (mirror-train 600); seed base 7100001
- generated: 2026-11-23T14:08:27; stopped: None; model calls 0, cost 0.0

## Win rate (Wilson 95%)

| subject | valid / games | overall | model |
|---|---|---|---|
| `noisy:0.1@a:heuristic` | 240 / 240 | 0.490 [0.43, 0.55] (n=240) | 0.490 [0.43, 0.55] (n=240) |

## By rules version

| subject | v6.2.0 | v6.3.0 |
|---|---|---|
| `noisy:0.1@a:heuristic` | 0.500 [0.41, 0.59] (n=120) | 0.479 [0.39, 0.57] (n=120) |

## Run health

- `noisy:0.1@a:heuristic` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
