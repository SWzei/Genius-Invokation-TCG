# Scenario set `v2`

- source games 160, scenarios {'lethal': 219}; lethal chance level 0.1623

| subject | lethal (picks a winning option) | chance | expert agreement | state reading | hidden-info probe |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt4-s1,reply=reason_first` | — | None | — | — | — |

| subject | lethal converted (plays on; wins before the opponent acts) | ended by |
|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 0.984 [0.92, 1.00] (n=64) | {'win': 63, 'opponent_turn': 1} |
| `llm:deepseek-flash#kb=kbt4-s1,reply=reason_first` | 0.938 [0.85, 0.98] (n=64) | {'win': 60, 'opponent_turn': 3, 'step_budget': 1} |

| converted, paired on common items | vs | n | better / worse | delta | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt4-s1,reply=reason_first` | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 64 | 0 / 3 | -0.047 | 0.250 |

| subject | lethal: final decision | lethal: one to three decisions earlier |
|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | — | — |
| `llm:deepseek-flash#kb=kbt4-s1,reply=reason_first` | — | — |

| model subject | decisions asked | first reply legal | answer used | s / item | tokens in / out | cost |
|---|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 64 | 1.0 | 1.0 | 1.748 | 225307 / 4049 | 0.005668 |
| `llm:deepseek-flash#kb=kbt4-s1,reply=reason_first` | 64 | 1.0 | 1.0 | 1.686 | 236584 / 4113 | 0.01532 |

_lethal = picks an option the engine verified as winning on the spot; chance = mean |winning|/|options|. Not taking it is not always a mistake (a free action first can keep the win), so read it as 'takes the win when it is on the table'. expert_agreement is similarity to the scripted pilot, not quality. A subject marked is_generator played the source games._
