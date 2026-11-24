# Scenario set `v2`

- source games 160, scenarios {'lethal': 219}; lethal chance level 0.1623

| subject | lethal (picks a winning option) | chance | expert agreement | state reading | hidden-info probe |
|---|---|---|---|---|---|
| `llm:subagent-sonnet#kb=kbt3-trig,reply=reason_first,elements=1` | 0.922 [0.83, 0.97] (n=64) | 0.1656 | — | — | — |
| `llm:subagent-sonnet#reply=reason_first,elements=1` | 0.875 [0.77, 0.94] (n=64) | 0.1656 | — | — | — |

| subject | lethal kept (wins now, or a win-now option at our next decision before the opponent acts) |
|---|---|
| `llm:subagent-sonnet#kb=kbt3-trig,reply=reason_first,elements=1` | 0.969 [0.89, 0.99] (n=64) |
| `llm:subagent-sonnet#reply=reason_first,elements=1` | 0.969 [0.89, 0.99] (n=64) |

| subject | lethal: final decision | lethal: one to three decisions earlier |
|---|---|---|
| `llm:subagent-sonnet#kb=kbt3-trig,reply=reason_first,elements=1` | 0.955 [0.85, 0.99] (n=44) | 0.850 [0.64, 0.95] (n=20) |
| `llm:subagent-sonnet#reply=reason_first,elements=1` | 0.955 [0.85, 0.99] (n=44) | 0.700 [0.48, 0.85] (n=20) |

| lethal, paired on common items | vs | n | better / worse | delta | sign test p |
|---|---|---|---|---|---|
| `llm:subagent-sonnet#reply=reason_first,elements=1` | `llm:subagent-sonnet#kb=kbt3-trig,reply=reason_first,elements=1` | 64 | 2 / 5 | -0.047 | 0.453 |

| model subject | decisions asked | first reply legal | answer used | s / item | tokens in / out | cost |
|---|---|---|---|---|---|---|
| `llm:subagent-sonnet#kb=kbt3-trig,reply=reason_first,elements=1` | 64 | 1.0 | 1.0 | 0.001 | 145646 / 1898 | 0.0 |
| `llm:subagent-sonnet#reply=reason_first,elements=1` | 64 | 1.0 | 1.0 | 0.001 | 69446 / 2041 | 0.0 |

_lethal = picks an option the engine verified as winning on the spot; chance = mean |winning|/|options|. Not taking it is not always a mistake (a free action first can keep the win), so read it as 'takes the win when it is on the table'. expert_agreement is similarity to the scripted pilot, not quality. A subject marked is_generator played the source games._
