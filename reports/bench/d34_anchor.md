# Benchmark `d34_anchor` — suite `anchor` (77f4eabf75b1b957)

- cells: 32 (anchor-expert 32); seed base 7100001
- generated: 2026-11-22T14:21:27; stopped: None; model calls 3568, cost 1.404046

## Win rate (Wilson 95%)

| subject | valid / games | overall | L2-expert |
|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 32 / 32 | 0.531 [0.36, 0.69] (n=32) | 0.531 [0.36, 0.69] (n=32) |
| `llm:deepseek-flash#kb=kbt4-s1,reply=reason_first` | 32 / 32 | 0.469 [0.31, 0.64] (n=32) | 0.469 [0.31, 0.64] (n=32) |

## Paired difference vs `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` (same cells)

| subject | pairs | delta | 95% CI | better / worse / same | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt4-s1,reply=reason_first` | 32 | -0.062 | [-0.24, +0.11] | 3 / 5 / 24 | 0.727 |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 1813 | 1.0 | 1.0 | 0 | 1.375 | 1.334 / 1.715 / 3.515 | 2565.9 | 56.7 | 145374 | 0.022656 |
| `llm:deepseek-flash#kb=kbt4-s1,reply=reason_first` | 1755 | 1.0 | 1.0 | 0 | 1.38 | 1.316 / 1.681 / 12.682 | 2592.4 | 54.8 | 142178 | 0.02122 |

Errors (why a model answer was not used): `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` {}; `llm:deepseek-flash#kb=kbt4-s1,reply=reason_first` {}

## Run health

- `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` engine fallbacks 0, invalid 0, degraded 0
- `llm:deepseek-flash#kb=kbt4-s1,reply=reason_first` engine fallbacks 0, invalid 0, degraded 0

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
