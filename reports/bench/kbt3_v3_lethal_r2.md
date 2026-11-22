# Scenario set `v3`

- source games 120, scenarios {'lethal': 141}; lethal chance level 0.1508

| subject | lethal (picks a winning option) | chance | expert agreement | state reading | hidden-info probe |
|---|---|---|---|---|---|
| `llm:deepseek-flash` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | — | None | — | — | — |

| subject | lethal converted (plays on; wins before the opponent acts) | ended by |
|---|---|---|
| `llm:deepseek-flash` | 0.943 [0.89, 0.97] (n=141) | {'win': 133, 'opponent_turn': 7, 'step_budget': 1} |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 0.950 [0.90, 0.98] (n=141) | {'win': 134, 'opponent_turn': 7} |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 0.943 [0.89, 0.97] (n=141) | {'win': 133, 'opponent_turn': 8} |

| converted, paired on common items | vs | n | better / worse | delta | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | `llm:deepseek-flash` | 141 | 6 / 5 | +0.007 | 1.000 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | `llm:deepseek-flash` | 141 | 6 / 6 | +0.000 | 1.000 |

| subject | lethal: final decision | lethal: one to three decisions earlier |
|---|---|---|
| `llm:deepseek-flash` | — | — |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | — | — |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | — | — |

| model subject | decisions asked | first reply legal | answer used | s / item | tokens in / out | cost |
|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 141 | 0.9645 | 0.9645 | 1.201 | 268466 / 5929 | 0.010224 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 141 | 0.9858 | 0.9858 | 1.581 | 507029 / 8413 | 0.015718 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 141 | 0.9858 | 0.9858 | 1.682 | 479663 / 8094 | 0.012571 |

_lethal = picks an option the engine verified as winning on the spot; chance = mean |winning|/|options|. Not taking it is not always a mistake (a free action first can keep the win), so read it as 'takes the win when it is on the table'. expert_agreement is similarity to the scripted pilot, not quality. A subject marked is_generator played the source games._
