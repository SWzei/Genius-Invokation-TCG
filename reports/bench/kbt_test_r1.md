# Scenario set `v2`

- source games 160, scenarios {'lethal': 219}; lethal chance level 0.1623

| subject | lethal (picks a winning option) | chance | expert agreement | state reading | hidden-info probe |
|---|---|---|---|---|---|
| `llm:deepseek-flash` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s0` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | — | None | — | — | — |

| subject | lethal converted (plays on; wins before the opponent acts) | ended by |
|---|---|---|
| `llm:deepseek-flash` | 0.957 [0.88, 0.99] (n=70) | {'win': 67, 'step_budget': 1, 'opponent_turn': 2} |
| `llm:deepseek-flash#kb=kbt-s0` | 0.900 [0.81, 0.95] (n=70) | {'win': 63, 'step_budget': 1, 'opponent_turn': 6} |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 0.929 [0.84, 0.97] (n=70) | {'win': 65, 'opponent_turn': 5} |

| converted, paired on common items | vs | n | better / worse | delta | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s0` | `llm:deepseek-flash` | 70 | 0 / 4 | -0.057 | 0.125 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | `llm:deepseek-flash` | 70 | 1 / 3 | -0.029 | 0.625 |

| subject | lethal: final decision | lethal: one to three decisions earlier |
|---|---|---|
| `llm:deepseek-flash` | — | — |
| `llm:deepseek-flash#kb=kbt-s0` | — | — |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | — | — |

| model subject | decisions asked | first reply legal | answer used | s / item | tokens in / out | cost |
|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 70 | 0.9 | 0.9 | 1.536 | 125165 / 2834 | 0.019647 |
| `llm:deepseek-flash#kb=kbt-s0` | 70 | 0.9571 | 0.9571 | 1.551 | 236040 / 3126 | 0.0246 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 70 | 0.9714 | 0.9714 | 1.827 | 240381 / 4092 | 0.027975 |

_lethal = picks an option the engine verified as winning on the spot; chance = mean |winning|/|options|. Not taking it is not always a mistake (a free action first can keep the win), so read it as 'takes the win when it is on the table'. expert_agreement is similarity to the scripted pilot, not quality. A subject marked is_generator played the source games._
