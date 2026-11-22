# Scenario set `v2`

- source games 160, scenarios {'lethal': 219}; lethal chance level 0.1623

| subject | lethal (picks a winning option) | chance | expert agreement | state reading | hidden-info probe |
|---|---|---|---|---|---|
| `llm:deepseek-flash` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s0` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | — | None | — | — | — |

| subject | lethal converted (plays on; wins before the opponent acts) | ended by |
|---|---|---|
| `llm:deepseek-flash` | 0.929 [0.84, 0.97] (n=70) | {'win': 65, 'opponent_turn': 5} |
| `llm:deepseek-flash#kb=kbt-s0` | 0.857 [0.76, 0.92] (n=70) | {'win': 60, 'opponent_turn': 10} |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 0.943 [0.86, 0.98] (n=70) | {'win': 66, 'opponent_turn': 4} |

| converted, paired on common items | vs | n | better / worse | delta | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s0` | `llm:deepseek-flash` | 70 | 0 / 5 | -0.071 | 0.062 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | `llm:deepseek-flash` | 70 | 4 / 3 | +0.014 | 1.000 |

| subject | lethal: final decision | lethal: one to three decisions earlier |
|---|---|---|
| `llm:deepseek-flash` | — | — |
| `llm:deepseek-flash#kb=kbt-s0` | — | — |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | — | — |

| model subject | decisions asked | first reply legal | answer used | s / item | tokens in / out | cost |
|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 70 | 0.8714 | 0.8714 | 1.704 | 126854 / 2931 | 0.004964 |
| `llm:deepseek-flash#kb=kbt-s0` | 70 | 0.9571 | 0.9571 | 1.608 | 236623 / 3099 | 0.006457 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 70 | 0.9714 | 0.9714 | 1.664 | 237034 / 3997 | 0.006419 |

_lethal = picks an option the engine verified as winning on the spot; chance = mean |winning|/|options|. Not taking it is not always a mistake (a free action first can keep the win), so read it as 'takes the win when it is on the table'. expert_agreement is similarity to the scripted pilot, not quality. A subject marked is_generator played the source games._
