# Benchmark `d38_gptoss` — suite `mirror_dev200` (7783c19b2a879a6f)

- cells: 400 (mirror-dev 400); seed base 7100001
- generated: 2026-11-23T22:02:08; stopped: fatal API error: llm:groq-gpt-oss-120b#kb=kbt3-trig,reply=reason_first,elements=1: quota: [rate_limit_exceeded] Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01m85zmyv4eanvz81kzrc7d1zp` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 197742, Requested 2670. Please try again in 2m57.984s. Need more tokens? Upgrade to Dev Tier today at ; model calls 178, cost 0.039488

## Win rate (Wilson 95%)

| subject | valid / games | overall | model |
|---|---|---|---|
| `llm:groq-gpt-oss-120b#kb=kbt3-trig,reply=reason_first,elements=1` | 1 / 2 | 1.000 [0.21, 1.00] (n=1) | 1.000 [0.21, 1.00] (n=1) |

## Model subjects: legality, latency, tokens

| subject | decisions asked | first reply legal | answer used | fallbacks | s / call | p50 / p90 / max s | tokens / decision | calls / game | tokens / game | cost / game |
|---|---|---|---|---|---|---|---|---|---|---|
| `llm:groq-gpt-oss-120b#kb=kbt3-trig,reply=reason_first,elements=1` | 83 | 0.494 | 0.494 | 42 | 10.201 | 21.487 / 31.067 / 40.227 | 1439.5 | 41.5 | 59739 | 0.010929 |

Errors (why a model answer was not used): `llm:groq-gpt-oss-120b#kb=kbt3-trig,reply=reason_first,elements=1` {'api:quota': 42}

## Run health

- `llm:groq-gpt-oss-120b#kb=kbt3-trig,reply=reason_first,elements=1` engine fallbacks 0, invalid 0, degraded 1

_win rates are simulator results on this suite's cells; intervals are Wilson 95% on valid games (errors, truncations and degraded games excluded and counted)_
