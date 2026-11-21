# Scenario set `v1`

- source games 40, scenarios {'lethal': 52, 'agreement': 160, 'quiz': 80}; lethal chance level 0.1749

| subject | lethal (picks a winning option) | chance | expert agreement | state reading | hidden-info probe |
|---|---|---|---|---|---|
| `llm:deepseek-flash` | 0.712 [0.58, 0.82] (n=52) | 0.1749 | 0.231 [0.17, 0.30] (n=160) | — | — |

| subject | lethal: final decision | lethal: one to three decisions earlier |
|---|---|---|
| `llm:deepseek-flash` | 0.824 [0.66, 0.92] (n=34) | 0.500 [0.29, 0.71] (n=18) |

| model subject | decisions asked | first reply legal | answer used | s / item | tokens in / out | cost |
|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 212 | 1.0 | 1.0 | 1.283 | 297993 / 7411 | 0.011198 |

_lethal = picks an option the engine verified as winning on the spot; chance = mean |winning|/|options|. Not taking it is not always a mistake (a free action first can keep the win), so read it as 'takes the win when it is on the table'. expert_agreement is similarity to the scripted pilot, not quality. A subject marked is_generator played the source games._
