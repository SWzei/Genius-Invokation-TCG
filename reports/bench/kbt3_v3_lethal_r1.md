# Scenario set `v3`

- source games 120, scenarios {'lethal': 141}; lethal chance level 0.1508

| subject | lethal (picks a winning option) | chance | expert agreement | state reading | hidden-info probe |
|---|---|---|---|---|---|
| `llm:deepseek-flash` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | — | None | — | — | — |

| subject | lethal converted (plays on; wins before the opponent acts) | ended by |
|---|---|---|
| `llm:deepseek-flash` | 0.950 [0.90, 0.98] (n=141) | {'win': 134, 'opponent_turn': 7} |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 0.957 [0.91, 0.98] (n=141) | {'win': 135, 'opponent_turn': 6} |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 0.943 [0.89, 0.97] (n=141) | {'win': 133, 'opponent_turn': 8} |

| converted, paired on common items | vs | n | better / worse | delta | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | `llm:deepseek-flash` | 141 | 5 / 4 | +0.007 | 1.000 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | `llm:deepseek-flash` | 141 | 6 / 7 | -0.007 | 1.000 |

| subject | lethal: final decision | lethal: one to three decisions earlier |
|---|---|---|
| `llm:deepseek-flash` | — | — |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | — | — |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | — | — |

| model subject | decisions asked | first reply legal | answer used | s / item | tokens in / out | cost |
|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 141 | 0.9716 | 0.9716 | 1.156 | 266381 / 5823 | 0.042096 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 141 | 0.9929 | 0.9929 | 1.296 | 498357 / 8306 | 0.057779 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 141 | 0.9929 | 0.9929 | 1.39 | 500830 / 8560 | 0.035968 |

_lethal = picks an option the engine verified as winning on the spot; chance = mean |winning|/|options|. Not taking it is not always a mistake (a free action first can keep the win), so read it as 'takes the win when it is on the table'. expert_agreement is similarity to the scripted pilot, not quality. A subject marked is_generator played the source games._
