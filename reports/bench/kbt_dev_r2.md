# Scenario set `v2`

- source games 160, scenarios {'lethal': 219}; lethal chance level 0.1623

| subject | lethal (picks a winning option) | chance | expert agreement | state reading | hidden-info probe |
|---|---|---|---|---|---|
| `llm:deepseek-flash` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s0` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s4` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | — | None | — | — | — |
| `llm:deepseek-flash#reply=reason_first` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt3-lean,reply=reason_first` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s4,reply=checklist` | — | None | — | — | — |

| subject | lethal converted (plays on; wins before the opponent acts) | ended by |
|---|---|---|
| `llm:deepseek-flash` | 0.922 [0.83, 0.97] (n=64) | {'win': 59, 'opponent_turn': 5} |
| `llm:deepseek-flash#kb=kbt-s0` | 0.906 [0.81, 0.96] (n=64) | {'win': 58, 'opponent_turn': 6} |
| `llm:deepseek-flash#kb=kbt-s4` | 0.906 [0.81, 0.96] (n=64) | {'win': 58, 'opponent_turn': 6} |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 0.969 [0.89, 0.99] (n=64) | {'win': 62, 'opponent_turn': 2} |
| `llm:deepseek-flash#reply=reason_first` | 0.906 [0.81, 0.96] (n=64) | {'win': 58, 'opponent_turn': 5, 'step_budget': 1} |
| `llm:deepseek-flash#kb=kbt3-lean,reply=reason_first` | 0.953 [0.87, 0.98] (n=64) | {'win': 61, 'opponent_turn': 3} |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 0.953 [0.87, 0.98] (n=64) | {'win': 61, 'opponent_turn': 3} |
| `llm:deepseek-flash#kb=kbt-s4,reply=checklist` | 0.969 [0.89, 0.99] (n=64) | {'win': 62, 'opponent_turn': 2} |

| converted, paired on common items | vs | n | better / worse | delta | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s0` | `llm:deepseek-flash` | 64 | 0 / 1 | -0.016 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s4` | `llm:deepseek-flash` | 64 | 1 / 2 | -0.016 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | `llm:deepseek-flash` | 64 | 3 / 0 | +0.047 | 0.250 |
| `llm:deepseek-flash#reply=reason_first` | `llm:deepseek-flash` | 64 | 1 / 2 | -0.016 | 1.000 |
| `llm:deepseek-flash#kb=kbt3-lean,reply=reason_first` | `llm:deepseek-flash` | 64 | 3 / 1 | +0.031 | 0.625 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | `llm:deepseek-flash` | 64 | 4 / 2 | +0.031 | 0.688 |
| `llm:deepseek-flash#kb=kbt-s4,reply=checklist` | `llm:deepseek-flash` | 64 | 4 / 1 | +0.047 | 0.375 |

| subject | lethal: final decision | lethal: one to three decisions earlier |
|---|---|---|
| `llm:deepseek-flash` | — | — |
| `llm:deepseek-flash#kb=kbt-s0` | — | — |
| `llm:deepseek-flash#kb=kbt-s4` | — | — |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | — | — |
| `llm:deepseek-flash#reply=reason_first` | — | — |
| `llm:deepseek-flash#kb=kbt3-lean,reply=reason_first` | — | — |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | — | — |
| `llm:deepseek-flash#kb=kbt-s4,reply=checklist` | — | — |

| model subject | decisions asked | first reply legal | answer used | s / item | tokens in / out | cost |
|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 64 | 0.9531 | 0.9531 | 1.836 | 129060 / 2970 | 0.005318 |
| `llm:deepseek-flash#kb=kbt-s0` | 64 | 0.9531 | 0.9531 | 1.712 | 231053 / 2983 | 0.005271 |
| `llm:deepseek-flash#kb=kbt-s4` | 64 | 1.0 | 1.0 | 1.538 | 213882 / 2592 | 0.004456 |
| `llm:deepseek-flash#kb=kbt-s4,reply=reason_first` | 64 | 1.0 | 1.0 | 1.929 | 231284 / 3978 | 0.007595 |
| `llm:deepseek-flash#reply=reason_first` | 64 | 0.9688 | 0.9688 | 2.086 | 127319 / 4773 | 0.006627 |
| `llm:deepseek-flash#kb=kbt3-lean,reply=reason_first` | 64 | 0.9844 | 0.9844 | 2.296 | 212336 / 4818 | 0.006858 |
| `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first` | 64 | 1.0 | 1.0 | 2.045 | 232668 / 4134 | 0.006974 |
| `llm:deepseek-flash#kb=kbt-s4,reply=checklist` | 64 | 1.0 | 1.0 | 1.755 | 202056 / 4543 | 0.005151 |

_lethal = picks an option the engine verified as winning on the spot; chance = mean |winning|/|options|. Not taking it is not always a mistake (a free action first can keep the win), so read it as 'takes the win when it is on the table'. expert_agreement is similarity to the scripted pilot, not quality. A subject marked is_generator played the source games._
