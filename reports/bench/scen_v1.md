# Scenario set `v1`

- source games 40, scenarios {'lethal': 52, 'agreement': 160, 'quiz': 80}; lethal chance level 0.1749

| subject | lethal (picks a winning option) | chance | expert agreement | state reading | hidden-info probe |
|---|---|---|---|---|---|
| `llm:glm-53-plan` | 0.750 [0.62, 0.85] (n=52) | 0.1749 | 0.244 [0.18, 0.32] (n=160) | 1.000 [0.99, 1.00] (n=560) | 0.973 [0.91, 0.99] (n=75) |
| `heuristic` | 0.769 [0.64, 0.86] (n=52) | 0.1749 | 0.175 [0.12, 0.24] (n=160) | — | — |
| `llm:glm-53-plan#kb=rules-strategy` | 0.769 [0.64, 0.86] (n=52) | 0.1749 | 0.283 [0.19, 0.41] (n=60) | — | — |
| `legal_random` | 0.115 [0.05, 0.23] (n=52) | 0.1749 | 0.144 [0.10, 0.21] (n=160) | — | — |
| `llm:glm-53-flash-plan` | 0.692 [0.56, 0.80] (n=52) | 0.1749 | 0.233 [0.14, 0.35] (n=60) | 1.000 [0.99, 1.00] (n=420) | 1.000 [0.94, 1.00] (n=56) |

| subject | lethal: final decision | lethal: one to three decisions earlier |
|---|---|---|
| `llm:glm-53-plan` | 0.853 [0.70, 0.94] (n=34) | 0.556 [0.34, 0.75] (n=18) |
| `heuristic` | 0.882 [0.73, 0.95] (n=34) | 0.556 [0.34, 0.75] (n=18) |
| `llm:glm-53-plan#kb=rules-strategy` | 0.853 [0.70, 0.94] (n=34) | 0.611 [0.39, 0.80] (n=18) |
| `legal_random` | 0.118 [0.05, 0.27] (n=34) | 0.111 [0.03, 0.33] (n=18) |
| `llm:glm-53-flash-plan` | 0.824 [0.66, 0.92] (n=34) | 0.444 [0.25, 0.66] (n=18) |

| lethal, paired on common items | vs | n | better / worse | delta | sign test p |
|---|---|---|---|---|---|
| `heuristic` | `llm:glm-53-plan` | 52 | 4 / 3 | +0.019 | 1.000 |
| `llm:glm-53-plan#kb=rules-strategy` | `llm:glm-53-plan` | 52 | 3 / 2 | +0.019 | 1.000 |
| `legal_random` | `llm:glm-53-plan` | 52 | 3 / 36 | -0.635 | 0.000 |
| `llm:glm-53-flash-plan` | `llm:glm-53-plan` | 52 | 3 / 6 | -0.058 | 0.508 |

| model subject | decisions asked | first reply legal | answer used | s / item | tokens in / out | cost |
|---|---|---|---|---|---|---|
| `llm:glm-53-plan` | 212 | 1.0 | 1.0 | 4.258 | 361766 / 39983 | 0.624176 |
| `llm:glm-53-plan#kb=rules-strategy` | 112 | 1.0 | 1.0 | 5.309 | 310198 / 20707 | 0.409309 |
| `llm:glm-53-flash-plan` | 112 | 1.0 | 1.0 | 5.093 | 205454 / 18251 | 0.037954 |

| state reading by question | my_active | my_active_hp | opp_active_hp | my_dice | my_hand | opp_hand | round | opp_has_card | probe answers |
|---|---|---|---|---|---|---|---|---|---|
| `llm:glm-53-plan` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.97 | {'unknown': 73, 'no': 2} |
| `llm:glm-53-flash-plan` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | {'unknown': 56} |

_lethal = picks an option the engine verified as winning on the spot; chance = mean |winning|/|options|. Not taking it is not always a mistake (a free action first can keep the win), so read it as 'takes the win when it is on the table'. expert_agreement is similarity to the scripted pilot, not quality. A subject marked is_generator played the source games._
