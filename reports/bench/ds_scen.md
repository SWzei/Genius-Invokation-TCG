# Scenario set `v1`

- source games 40, scenarios {'lethal': 52, 'agreement': 160, 'quiz': 80}; lethal chance level 0.1749

| subject | lethal (picks a winning option) | chance | expert agreement | state reading | hidden-info probe |
|---|---|---|---|---|---|
| `llm:deepseek-flash` | 0.750 [0.62, 0.85] (n=52) | 0.1749 | 0.225 [0.17, 0.30] (n=160) | 1.000 [0.99, 1.00] (n=560) | 1.000 [0.95, 1.00] (n=75) |
| `llm:deepseek-flash#kb=rules` | 0.712 [0.58, 0.82] (n=52) | 0.1749 | 0.225 [0.17, 0.30] (n=160) | — | — |
| `llm:deepseek-flash#kb=rules-strategy` | 0.731 [0.60, 0.83] (n=52) | 0.1749 | 0.231 [0.17, 0.30] (n=160) | — | — |
| `llm:deepseek-flash#kb=rules-strategy-full` | 0.750 [0.62, 0.85] (n=52) | 0.1749 | 0.237 [0.18, 0.31] (n=160) | — | — |
| `llm:deepseek-flash-think` | 0.788 [0.66, 0.88] (n=52) | 0.1749 | — | 1.000 [0.99, 1.00] (n=560) | 1.000 [0.95, 1.00] (n=75) |

| subject | lethal: final decision | lethal: one to three decisions earlier |
|---|---|---|
| `llm:deepseek-flash` | 0.824 [0.66, 0.92] (n=34) | 0.611 [0.39, 0.80] (n=18) |
| `llm:deepseek-flash#kb=rules` | 0.824 [0.66, 0.92] (n=34) | 0.500 [0.29, 0.71] (n=18) |
| `llm:deepseek-flash#kb=rules-strategy` | 0.824 [0.66, 0.92] (n=34) | 0.556 [0.34, 0.75] (n=18) |
| `llm:deepseek-flash#kb=rules-strategy-full` | 0.882 [0.73, 0.95] (n=34) | 0.500 [0.29, 0.71] (n=18) |
| `llm:deepseek-flash-think` | 0.882 [0.73, 0.95] (n=34) | 0.611 [0.39, 0.80] (n=18) |

| lethal, paired on common items | vs | n | better / worse | delta | sign test p |
|---|---|---|---|---|---|
| `llm:deepseek-flash#kb=rules` | `llm:deepseek-flash` | 52 | 0 / 2 | -0.038 | 0.500 |
| `llm:deepseek-flash#kb=rules-strategy` | `llm:deepseek-flash` | 52 | 2 / 3 | -0.019 | 1.000 |
| `llm:deepseek-flash#kb=rules-strategy-full` | `llm:deepseek-flash` | 52 | 3 / 3 | +0.000 | 1.000 |
| `llm:deepseek-flash-think` | `llm:deepseek-flash` | 52 | 4 / 2 | +0.038 | 0.688 |

| model subject | decisions asked | first reply legal | answer used | s / item | tokens in / out | cost |
|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 212 | 1.0 | 1.0 | 1.191 | 358531 / 12464 | 0.060092 |
| `llm:deepseek-flash#kb=rules` | 212 | 1.0 | 1.0 | 1.229 | 472757 / 7556 | 0.047487 |
| `llm:deepseek-flash#kb=rules-strategy` | 212 | 1.0 | 1.0 | 1.291 | 571899 / 7744 | 0.036994 |
| `llm:deepseek-flash#kb=rules-strategy-full` | 212 | 1.0 | 1.0 | 1.304 | 615640 / 7776 | 0.041241 |
| `llm:deepseek-flash-think` | 52 | 0.9615 | 0.9808 | 4.772 | 143281 / 71792 | 0.063928 |

| state reading by question | my_active | my_active_hp | opp_active_hp | my_dice | my_hand | opp_hand | round | opp_has_card | probe answers |
|---|---|---|---|---|---|---|---|---|---|
| `llm:deepseek-flash` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | {'unknown': 75} |
| `llm:deepseek-flash-think` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | {'unknown': 75} |

_lethal = picks an option the engine verified as winning on the spot; chance = mean |winning|/|options|. Not taking it is not always a mistake (a free action first can keep the win), so read it as 'takes the win when it is on the table'. expert_agreement is similarity to the scripted pilot, not quality. A subject marked is_generator played the source games._
