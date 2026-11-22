# Scenario set `v1`

- source games 40, scenarios {'lethal': 52, 'agreement': 160, 'quiz': 80}; lethal chance level 0.1749

| subject | lethal (picks a winning option) | chance | expert agreement | state reading | hidden-info probe |
|---|---|---|---|---|---|
| `llm:deepseek-flash` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s0` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s1` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s2` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s3` | — | None | — | — | — |
| `llm:deepseek-flash#kb=kbt-s4` | — | None | — | — | — |

| subject | lethal converted (plays on; wins before the opponent acts) | ended by |
|---|---|---|
| `llm:deepseek-flash` | 0.923 [0.82, 0.97] (n=52) | {'opponent_turn': 4, 'win': 48} |
| `llm:deepseek-flash#kb=kbt-s0` | 0.942 [0.84, 0.98] (n=52) | {'win': 49, 'opponent_turn': 3} |
| `llm:deepseek-flash#kb=kbt-s1` | 0.904 [0.79, 0.96] (n=52) | {'win': 47, 'opponent_turn': 5} |
| `llm:deepseek-flash#kb=kbt-s2` | 0.904 [0.79, 0.96] (n=52) | {'win': 47, 'opponent_turn': 5} |
| `llm:deepseek-flash#kb=kbt-s3` | 0.923 [0.82, 0.97] (n=52) | {'win': 48, 'opponent_turn': 4} |
| `llm:deepseek-flash#kb=kbt-s4` | 0.942 [0.84, 0.98] (n=52) | {'win': 49, 'opponent_turn': 3} |

| converted, paired on common items | vs | n | better / worse | delta | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=kbt-s0` | `llm:deepseek-flash` | 52 | 1 / 0 | +0.019 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s1` | `llm:deepseek-flash` | 52 | 1 / 2 | -0.019 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s2` | `llm:deepseek-flash` | 52 | 1 / 2 | -0.019 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s3` | `llm:deepseek-flash` | 52 | 1 / 1 | +0.000 | 1.000 |
| `llm:deepseek-flash#kb=kbt-s4` | `llm:deepseek-flash` | 52 | 1 / 0 | +0.019 | 1.000 |

| subject | lethal: final decision | lethal: one to three decisions earlier |
|---|---|---|
| `llm:deepseek-flash` | — | — |
| `llm:deepseek-flash#kb=kbt-s0` | — | — |
| `llm:deepseek-flash#kb=kbt-s1` | — | — |
| `llm:deepseek-flash#kb=kbt-s2` | — | — |
| `llm:deepseek-flash#kb=kbt-s3` | — | — |
| `llm:deepseek-flash#kb=kbt-s4` | — | — |

| model subject | decisions asked | first reply legal | answer used | s / item | tokens in / out | cost |
|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 52 | 0.8846 | 0.8846 | 1.552 | 93135 / 2281 | 0.004935 |
| `llm:deepseek-flash#kb=kbt-s0` | 52 | 0.8846 | 0.8846 | 1.51 | 165724 / 2196 | 0.005048 |
| `llm:deepseek-flash#kb=kbt-s1` | 52 | 0.9423 | 0.9423 | 1.495 | 161791 / 2271 | 0.015828 |
| `llm:deepseek-flash#kb=kbt-s2` | 52 | 0.9038 | 0.9038 | 1.682 | 142228 / 2228 | 0.00743 |
| `llm:deepseek-flash#kb=kbt-s3` | 52 | 0.9808 | 0.9808 | 1.748 | 155480 / 2226 | 0.008551 |
| `llm:deepseek-flash#kb=kbt-s4` | 52 | 0.9808 | 0.9808 | 1.584 | 166668 / 2114 | 0.017895 |

_lethal = picks an option the engine verified as winning on the spot; chance = mean |winning|/|options|. Not taking it is not always a mistake (a free action first can keep the win), so read it as 'takes the win when it is on the table'. expert_agreement is similarity to the scripted pilot, not quality. A subject marked is_generator played the source games._
