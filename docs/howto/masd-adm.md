# howto — MASD-ADM / VCSD 兼容层

> 决策：`PLAN.md §0` D28。实测结果与问题清单：`reports/review/2026-11_masd_adm_compat.md`。
> 本页只写接口、用法与边界；不重复 `collect-and-train.md` 已有内容。

## 1. 这层做什么

把"知识 / 对局数据 → 决策监督 → 反事实证据 → 蒸馏训练 → 评测"接到现有管线上，
不改引擎、不改默认训练行为：

```
GITCG_KB ──reps/knowledge──┐
GITCG_Data ─envs/tournament_decks─(牌组池)        ┌─ train/strategy_targets ─ scripts/datafirst_bc_train --supervision
train.collect 语料 ────────┼─ train/evidence ─────┤        （BC/PG 损失 + λ·w·KL）
envs/fork_search(belief) ──┘  supervision.jsonl   └─ train/student（CVPN / Transformer / 文本学生）
                                                              └─ scripts/eval_protocol（配对认证，不变）
```

共享契约是 `reps/strategy.py` 的 `DecisionSupervision`（JSONL，一行一个决策）：决策身份、合法选项
（语义 key + 文本）、专家动作、可选的反事实证据、匹配到的策略知识单元、来源与版本。
它不含张量与编码器布局；网络学生按决策键与 store 对齐，文本学生直接读 `text` / `options`。

## 2. 证据边界

| 类别 | 载体 | 含义 | 能否成为动作标签 |
|---|---|---|---|
| `expert_action` | `expert_index` | 专家策略实际打出的动作 | 是（即 BC 标签） |
| `language_strategy` | `knowledge`（策略单元 id） | 知识库文本单元的**适用条件**在此决策成立 | **否**。只作标注；没有任何 target 模式读它 |
| `search_estimate` | `evidence.candidates[*].scores` | 给定续行策略 μ 与公共信念下的蒙特卡洛胜率估计 | 仅 `evidence_soft`（消融用，未验证） |
| verified | **不落盘**，由 `reps.strategy.verdict` 现算 | 配对 rollout 的精确符号检验 `p ≤ α` 且信息合法 | 是（`evidence_gated`，默认） |

- "verified" 是逐决策、水平 α 的结论，一批结论要对照偶然通过数来读：`train.evidence.summarize` 同时给出
  `verified` 与 `expected_by_chance`（假设备选与专家动作等价时，按各比较的不一致对数精确计算的期望通过数），
  两者接近时这批结论没有信息量。`can_pass` 是不一致对数足以通过门控的决策数（α=0.05 时至少 6 对）。
- 估计值是相对 μ（默认双方脚本专家）的 `Q^μ`，不是博弈论价值；μ 写在每条证据的 `continuation` 里。

## 3. 信息合法性（硬约束）

`train/evidence.py` 只用 `envs.fork_search` 的公共信念根：边界快照先遮蔽到行动方视角，再按公开信息重采样
对手手牌/牌库/骰子与己方牌库顺序。每条证据的 `information` 记录：

- `root = public_belief`、`empty_prefix = true`、`inject_key_verified = true`；
- `assumptions = ["opponent_decklist_known"]`（对手 30 张牌表公开，赛事规则；没有牌表则估计无定义）。

三条限制由代码强制，而不是约定：

1. 只评估 `action` 决策，且只在边界快照与决策重合（重放前缀为空）时评估；否则跳过。
   前缀是真实世界里的位置索引，在确定化世界里不保证指向同一动作。
2. 每个 fork 在注入点校验两件事（`ForkTask.inject_key`）：被注入动作的语义 key 与现场一致；
   **整个合法动作列表**与现场一致。玩家看得到自己的合法动作，给出不同列表的确定化世界不是玩家可能身处的世界。
   不一致的 rollout 记入 `errors` 并丢弃，有效配对不足 `min_pairs` 的决策不进门控。
3. 使用了真实隐藏状态的证据（`root != public_belief`）永远不会被判为 verified，也不产生 target。

`train.replay_branch` 重放真实对局、以真实隐藏状态为条件，**不用于**本层。

## 4. 用法

```bash
export GITCG_KB_DIR=<…>/GITCG_KB                     # 可选：给记录盖知识库版本戳
export GITCG_DATA_RELEASE=<…>/GITCG_Data/release/v1.0 # 可选：人类赛事牌组池

# ① 语料与 BC 基线（照常；种子从 1 起，见 §7）
python -m train.collect --deck <deck> --all-opponents --seed-start 1 --seed-count 9 \
    --sides both --encoder-profile v2 --tag <corpus>
python -m scripts.datafirst_bc_store --replays data/replays/<corpus> --store-cache data/store/<corpus>.pt \
    --seed-start 1 --val-every 9
python -m scripts.datafirst_bc_train --store-cache data/store/<corpus>.pt --out data/checkpoints/bc.pt

# ② 反事实证据（同一批对局；label-only，不改变对局本身）
python -m scripts.collect_evidence --deck <deck> --all-opponents --seed-start 2 --seed-count 1 --sides 0 1 \
    --rollouts 12 --top-k 1 --prior data/checkpoints/bc.pt --gate disagreement --search-every 3 \
    --max-decisions 100 --workers 2 --tag <evidence>
#   → data/evidence/<evidence>/{supervision.jsonl, games.jsonl, manifest.json}；同命令续跑，改参数需换 tag

# ③ 蒸馏训练（不带 --distill-coef 时与原训练逐字节相同）
python -m scripts.datafirst_bc_train --store-cache data/store/<corpus>.pt \
    --supervision data/evidence/<evidence>/supervision.jsonl \
    --distill-coef 1.0 --distill-target evidence_gated --out data/checkpoints/vcsd.pt

# ④ 配对评测（不变）
python -m scripts.eval_protocol …        # 见 docs/EVAL_PROTOCOL.md
```

成本：每个被评估的决策跑 `(备选数 + 1) × rollouts` 局续行对局（本机约 1.8 s/局·2 worker）。
用 `--gate`、`--search-every`、`--max-searches-per-game`、`--max-decisions` 控制预算。

### 损失

```
L = L_base + distill_coef · (1/B) · Σ_i  w_i · KL(π_k,i ‖ π_θ,i)
```

`L_base` 是训练器原有损失（ce / awr / q / pg），`B` 是 batch 大小，没有 target 的样本 `w_i = 0`。
one-hot target 下 KL 即该动作的交叉熵；当 target 与专家动作不同，`distill_coef · w` 就是最优解里
target 对专家标签的赔率。`w` 取 `1 − p_sign`（`--distill-weighting reliability`）或 1（`uniform`）。

| `--distill-target` | target | 用途 |
|---|---|---|
| `evidence_gated`（默认） | 通过门控的决策 → 被支持动作的 one-hot；其余无 target | VCSD |
| `evidence_soft` | 候选平均胜率的 softmax（不过门控） | 消融；未验证的搜索估计 |
| `expert` | 专家动作 one-hot | 管线自检（KL ≡ CE） |

对齐按 `(deck, opponent, seed[, side], step)`，并核对选项数与专家动作下标；不一致的记录计入
`mismatched_records` 并丢弃。训练报告的 `distill` 块给出全部计数。

### 学生与自适应接口

- `train.student.NetworkStudent.from_checkpoint(path)`：CVPN / TransformerCVPN，实现 `distribution(built)`
  （与 `ForkSearchPolicy.prior` 同一协议），以及按 store 特征离线出分布。
- `train.student.TextStudent(scorer)`：文本学生。`render_record` / `render_context` 限定了它能读到的内容
  （行动方公开视图、合法选项、知识单元文本）；`scorer(prompt, options) -> scores` 由调用方注入。
- `envs.adaptive`：`ForkSearchPolicy(gate=…)` 的门控（`disagreement`、`margin:<x>`、`entropy:<x>`）。
  门控只决定某决策是否花搜索预算，不改变合法动作、候选集与 rollout 所见信息。
- `train.student.evidence_agreement`：学生选择与证据的一致性（离线指标，不是强度）。

## 5. 知识与数据适配

- `reps/knowledge.py`：读取 `GITCG_KB/data/derived/{strategy_units,rule_sections}.jsonl`，保留来源、
  知识库版本、文档、证据类别与知识库自带置信度标签；`matching_units(context)` 对其中 14 个单元
  （共 70 个）给出可判定的适用条件检测器，只读行动方 `player_view` 与合法选项；
  `RULE_REFS_BY_OPTION_KIND` 把每类合法动作映射到规则条目。其余 56 个单元没有检测器，不做标注。
- `envs/tournament_decks.py`：`GITCG_Data` 的对局是**结果级**记录（阵容、牌表、先后手、胜负、版本），
  没有动作或状态轨迹。适配器只提供有效牌组（→ `DeckSpec`，带来源）作为对手/参赛牌组池；
  它不能、也没有被用来生成动作监督。

## 6. 状态

| 能力 | 状态 | 依据 |
|---|---|---|
| 监督记录 schema、配对统计、门控、JSONL 往返 | 已实现，已测试 | `tests/test_masd_adm.py` |
| 知识库加载/检索/规则映射、14 个条件检测器 | 已实现，已测试（真实 KB：70 单元 / 90 规则条目） | 同上 |
| 赛事牌组适配 | 已实现，已测试（真实数据：4,365 套不重复有效牌组；抽 6 个版本各 1 套引擎可打完） | 同上 |
| label-only 信息合法证据生成、断点续跑 | 已实现，已测试（证据对局与采集对局逐决策一致） | 同上（slow） |
| 蒸馏损失挂钩（`run_batch` / `train` / CLI） | 已实现，已测试（关闭时权重逐位相同） | 同上 |
| CVPN / TransformerCVPN 学生 | 已实现；CVPN 路径已测试，Transformer 走同一加载器 | 同上 |
| 文本 / LLM 学生 | **部分**：接口与信息边界已实现并用假 scorer 测试；没有 LLM 后端 | 同上 |
| 自适应搜索 | **部分**：门控钩子与两种门控已实现并测试；未评测其对强度的影响 | 同上 |
| 策略知识 → 动作偏好 `π_k` | **未实现**：知识单元只作标注，建议文本没有到动作分布的映射 | — |
| PG 路径上的蒸馏项 | **部分**：`--loss pg` 与 KL 项可同时开启（同一 `run_batch`），未做实验 | — |
| 真实隐藏状态下的证据（`replay_branch`） | 不提供；永不判为 verified | — |
| 人类对局的动作级监督 | 不可行：数据没有轨迹 | — |

## 7. 注意

- **不要用种子 0**：引擎随机种子为 0 时每次掷骰都是同一面（见报告 §4.3）。本层默认从种子 1 起，
  `scripts.collect_evidence` 遇到种子 0 会告警。
- 接口测试通过只说明功能正确。新训练臂是否更强，只能由 `scripts.eval_protocol` 的配对认证回答
  （`docs/EVAL_PROTOCOL.md`），小样本结果只作筛选。
