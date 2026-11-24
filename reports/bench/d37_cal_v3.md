# Benchmark `d37_cal_v3` — suite `mirror_train300` (d560cb3cfad99b37)

- cells: 600 (mirror-train 600); seed base 7100001
- generated: 2026-11-23T12:59:07; stopped: None; model calls 0, cost 0.0

## Win rate (Wilson 95%)

| subject | valid / games | overall | model |
|---|---|---|---|
| `noisy:0.1:heuristic` | 240 / 240 | 0.500 [0.44, 0.56] (n=240) | 0.500 [0.44, 0.56] (n=240) |

## By rules version

| subject | v6.2.0 | v6.3.0 |
|---|---|---|
| `noisy:0.1:heuristic` | 0.500 [0.41, 0.59] (n=120) | 0.500 [0.41, 0.59] (n=120) |

## Run health

- `noisy:0.1:heuristic` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
