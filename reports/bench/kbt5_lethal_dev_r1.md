# Scenario set `v2`

- source games 160, scenarios {'lethal': 219}; lethal chance level 0.1623

| subject | lethal (picks a winning option) | chance | expert agreement | state reading | hidden-info probe |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt6-r1,reply=reason_first,elements=1` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt6-r2,reply=reason_first,elements=1` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt6-r3,reply=reason_first,elements=1` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | — | None | — | — | — |

| subject | lethal converted (plays on; wins before the opponent acts) | ended by |
|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 0.953 [0.87, 0.98] (n=64) | {'win': 61, 'opponent_turn': 3} |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 0.938 [0.85, 0.98] (n=64) | {'win': 60, 'step_budget': 1, 'opponent_turn': 3} |
| `llm:deepseek-flash#kb=kbt6-r1,reply=reason_first,elements=1` | 0.953 [0.87, 0.98] (n=64) | {'win': 61, 'opponent_turn': 3} |
| `llm:deepseek-flash#kb=kbt6-r2,reply=reason_first,elements=1` | 0.953 [0.87, 0.98] (n=64) | {'win': 61, 'opponent_turn': 3} |
| `llm:deepseek-flash#kb=kbt6-r3,reply=reason_first,elements=1` | 0.969 [0.89, 0.99] (n=64) | {'win': 62, 'opponent_turn': 2} |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | 0.984 [0.92, 1.00] (n=64) | {'win': 63, 'opponent_turn': 1} |

| converted, paired on common items | vs | n | better / worse | delta | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 64 | 0 / 1 | -0.016 | 1.000 |
| `llm:deepseek-flash#kb=kbt6-r1,reply=reason_first,elements=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 64 | 1 / 1 | +0.000 | 1.000 |
| `llm:deepseek-flash#kb=kbt6-r2,reply=reason_first,elements=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 64 | 2 / 2 | +0.000 | 1.000 |
| `llm:deepseek-flash#kb=kbt6-r3,reply=reason_first,elements=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 64 | 2 / 1 | +0.016 | 1.000 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 64 | 3 / 1 | +0.031 | 0.625 |

| subject | lethal: final decision | lethal: one to three decisions earlier |
|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | — | — |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | — | — |
| `llm:deepseek-flash#kb=kbt6-r1,reply=reason_first,elements=1` | — | — |
| `llm:deepseek-flash#kb=kbt6-r2,reply=reason_first,elements=1` | — | — |
| `llm:deepseek-flash#kb=kbt6-r3,reply=reason_first,elements=1` | — | — |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | — | — |

| model subject | decisions asked | first reply legal | answer used | s / item | tokens in / out | cost |
|---|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 64 | 1.0 | 1.0 | 1.841 | 247948 / 4483 | 0.006428 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1` | 64 | 1.0 | 1.0 | 1.747 | 224943 / 3897 | 0.035421 |
| `llm:deepseek-flash#kb=kbt6-r1,reply=reason_first,elements=1` | 64 | 1.0 | 1.0 | 1.823 | 231351 / 3725 | 0.019646 |
| `llm:deepseek-flash#kb=kbt6-r2,reply=reason_first,elements=1` | 64 | 0.9844 | 0.9844 | 1.707 | 226887 / 3802 | 0.013171 |
| `llm:deepseek-flash#kb=kbt6-r3,reply=reason_first,elements=1` | 64 | 1.0 | 1.0 | 1.844 | 215895 / 3638 | 0.005479 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1,facts=1,cards=1` | 64 | 1.0 | 1.0 | 1.615 | 263474 / 2941 | 0.035189 |

_lethal = picks an option the engine verified as winning on the spot; chance = mean |winning|/|options|. Not taking it is not always a mistake (a free action first can keep the win), so read it as 'takes the win when it is on the table'. expert_agreement is similarity to the scripted pilot, not quality. A subject marked is_generator played the source games._
