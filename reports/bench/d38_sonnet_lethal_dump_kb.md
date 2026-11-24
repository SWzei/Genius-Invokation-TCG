# Scenario set `v2`

- source games 160, scenarios {'lethal': 219}; lethal chance level 0.1623

| subject | lethal (picks a winning option) | chance | expert agreement | state reading | hidden-info probe |
|---|---|---|---|---|---|
| `llm:subagent-sonnet#kb=kbt3-trig,reply=reason_first,elements=1` | 0.750 [0.63, 0.84] (n=64) | 0.1656 | — | — | — |

| subject | lethal kept (wins now, or a win-now option at our next decision before the opponent acts) |
|---|---|
| `llm:subagent-sonnet#kb=kbt3-trig,reply=reason_first,elements=1` | 0.828 [0.72, 0.90] (n=64) |

| subject | lethal: final decision | lethal: one to three decisions earlier |
|---|---|---|
| `llm:subagent-sonnet#kb=kbt3-trig,reply=reason_first,elements=1` | 0.818 [0.68, 0.90] (n=44) | 0.600 [0.39, 0.78] (n=20) |

| model subject | decisions asked | first reply legal | answer used | s / item | tokens in / out | cost |
|---|---|---|---|---|---|---|
| `llm:subagent-sonnet#kb=kbt3-trig,reply=reason_first,elements=1` | 64 | 0.0 | 0.0 | 0.003 | 0 / 0 | 0.0 |

_lethal = picks an option the engine verified as winning on the spot; chance = mean |winning|/|options|. Not taking it is not always a mistake (a free action first can keep the win), so read it as 'takes the win when it is on the table'. expert_agreement is similarity to the scripted pilot, not quality. A subject marked is_generator played the source games._
