# Scenario set `v2`

- source games 160, scenarios {'lethal': 219}; lethal chance level 0.1623

| subject | lethal (picks a winning option) | chance | expert agreement | state reading | hidden-info probe |
|---|---|---|---|---|---|
| `llm:deepseek-flash` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s0` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s4` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | — | None | — | — | — |
| `llm:deepseek-flash#reply=reason_first` | — | None | — | — | — |

| subject | lethal converted (plays on; wins before the opponent acts) | ended by |
|---|---|---|
| `llm:deepseek-flash` | 0.922 [0.83, 0.97] (n=64) | {'win': 59, 'opponent_turn': 5} |
| `llm:deepseek-flash#kb=kbt-s0` | 0.906 [0.81, 0.96] (n=64) | {'win': 58, 'opponent_turn': 6} |
| `llm:deepseek-flash#kb=kbt-s4` | 0.891 [0.79, 0.95] (n=64) | {'win': 57, 'opponent_turn': 7} |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 0.984 [0.92, 1.00] (n=64) | {'win': 63, 'opponent_turn': 1} |
| `llm:deepseek-flash#reply=reason_first` | 0.891 [0.79, 0.95] (n=64) | {'win': 57, 'opponent_turn': 6, 'step_budget': 1} |

| converted, paired on common items | vs | n | better / worse | delta | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s0` | `llm:deepseek-flash` | 64 | 0 / 1 | -0.016 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s4` | `llm:deepseek-flash` | 64 | 1 / 3 | -0.031 | 0.625 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | `llm:deepseek-flash` | 64 | 4 / 0 | +0.062 | 0.125 |
| `llm:deepseek-flash#reply=reason_first` | `llm:deepseek-flash` | 64 | 1 / 3 | -0.031 | 0.625 |

| subject | lethal: final decision | lethal: one to three decisions earlier |
|---|---|---|
| `llm:deepseek-flash` | — | — |
| `llm:deepseek-flash#kb=kbt-s0` | — | — |
| `llm:deepseek-flash#kb=kbt-s4` | — | — |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | — | — |
| `llm:deepseek-flash#reply=reason_first` | — | — |

| model subject | decisions asked | first reply legal | answer used | s / item | tokens in / out | cost |
|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 64 | 0.9219 | 0.9219 | 1.728 | 134123 / 3138 | 0.020741 |
| `llm:deepseek-flash#kb=kbt-s0` | 64 | 0.9375 | 0.9375 | 1.564 | 228969 / 2987 | 0.024434 |
| `llm:deepseek-flash#kb=kbt-s4` | 64 | 1.0 | 1.0 | 1.413 | 210759 / 2520 | 0.023059 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 64 | 1.0 | 1.0 | 1.704 | 217421 / 3720 | 0.00728 |
| `llm:deepseek-flash#reply=reason_first` | 64 | 0.9688 | 0.9688 | 2.166 | 122110 / 4408 | 0.006548 |

_lethal = picks an option the engine verified as winning on the spot; chance = mean |winning|/|options|. Not taking it is not always a mistake (a free action first can keep the win), so read it as 'takes the win when it is on the table'. expert_agreement is similarity to the scripted pilot, not quality. A subject marked is_generator played the source games._
