---
title: "2026-11 MASD-ADM / VCSD 兼容层：实现、验证与最小闭环"
kind: report
status: valid
freshness: 2026-11-12
machines: [cloud-2c]
authority: evidence
related: ["PLAN.md#D28", "docs/howto/masd-adm.md", "reports/review/2026-11_technical_review.md"]
---

# 2026-11 MASD-ADM / VCSD 兼容层

> 基线：`review/2026-11-correctness`（D27 审查后的代码）。环境：云端 2 核 / 7 GB，Python 3.12，
> `gitcg 0.21.0`，torch CPU。接口与用法见 `docs/howto/masd-adm.md`，本报告只记录**实际执行结果**。
> 原始数字：`reports/review/masd_min_e2e_20261112.json`。

## 0. 结论

1. **功能正确（已验证）**：五项开发范围都有可运行的实现和测试；蒸馏关闭时训练权重与基线代码逐位相同；
   证据对局与普通采集对局逐决策一致；证据只从公共信念根出发。
2. **实验连通（已验证）**："对局数据 → 决策监督 → 反事实评价 → 蒸馏训练 → 配对评测" 在小规模上跑通，
   每一步的输入输出、版本和种子都落盘。
3. **算法性能（没有证据）**：最小闭环里，100 个被评估的决策只有 3 个通过门控，蒸馏臂 B1 与 BC 基线 B0 的
   配对差为 −0.025（95% 区间 [−0.068, +0.018]，n=120），分不出高下。这不是"VCSD 无效"的证据，
   也不是有效的证据：监督信号太少，实验没有检验力。真正的瓶颈是证据的统计功效（§5.5）。
4. **顺带发现并处理三个既有问题**（§4）：belief 根的两个保真缺陷——约 1% 的边界快照上搜索静默改打回退动作；
   确定化清掉行动方自己手牌上的附着，使合法动作列表与现场不一致（均已修并加回归）；
   引擎随机种子 0 退化（已告警、未改行为，需要决策）。前两个是被本次新增的校验暴露出来的。

## 1. 改动清单

新增（11 个文件）：

| 文件 | 作用 |
|---|---|
| `reps/strategy.py` | 监督记录契约：`StrategyUnit`、`OptionRef`、`CounterfactualEvidence`、`DecisionSupervision`；配对统计、精确符号检验、`verdict` 门控；JSONL 读写 |
| `reps/knowledge.py` | 知识库适配：加载/检索、14 个条件检测器、动作类别 → 规则条目 |
| `envs/tournament_decks.py` | 赛事数据 → `DeckSpec` 牌组池（带来源） |
| `envs/adaptive.py` | 搜索门控：`disagreement` / `margin` / `entropy` |
| `train/evidence.py` | label-only 信息合法证据对局、`summarize` |
| `train/strategy_targets.py` | `TargetSpec`、`DecisionTargets`（按键对齐）、KL 项 |
| `train/student.py` | `NetworkStudent`、`TextStudent`、`evidence_agreement` |
| `scripts/collect_evidence.py` | 证据采集 CLI（追加写、指纹、断点续跑） |
| `scripts/evidence_agreement.py` | checkpoint 对已存证据的离线一致性 |
| `tests/test_masd_adm.py` | 33 项测试（27 快 + 6 slow） |
| `docs/howto/masd-adm.md` | 接口、用法、边界、状态矩阵 |

修改（均为加法，默认行为不变）：

| 文件 | 改动 |
|---|---|
| `envs/fork_bridge.py` | `ForkTask.inject_key`、`legal_keys_digest`；注入动作语义 key 或合法动作列表与现场不符时把该 fork 标为 error |
| `envs/fork_search.py` | `ForkSearchPolicy` 新增 `act_on_search` / `request_types` / `require_empty_prefix` / `verify_inject_key` / `gate`；`SearchDecision` 记录逐 rollout 得分；`run_search_match(on_decision=…)` |
| `reps/belief.py` | **修复**：支持内联序列化的 `hands` / `pile`（§4.1）；保留行动方自己手牌上的附着与变量（§4.2） |
| `scripts/train_bc_scale.py` | `Config.distill_coef`（默认 0）；`run_batch` / `train` 的 `decision_targets` |
| `scripts/datafirst_bc_train.py` | `--supervision`、`--distill-*`；报告增加 `distill` 块 |
| `train/resolver.py` | 先验加载按 checkpoint 的 `arch` 分派（原先只认 mean-pool CVPN） |
| `train/collect.py` | 种子 0 告警（stderr，行为不变） |
| `agents/llm_assist.py` | 对手骰子数改用公开计数（原先恒为 0） |
| `PLAN.md`、`docs/STATUS.md`、`docs/decisions/README.md`、`docs/howto/collect-and-train.md`、`tests/README.md` | D28 及配套说明 |

## 2. 设计取舍（与研究文档的对应）

| 研究设计 | 本次落地 | 没有做、为什么 |
|---|---|---|
| 知识单元 `k=(c, φ, π_k, ΔQ, ρ)` | `c`/`φ` 文本来自知识库；`φ` 对 14/70 个单元有可判定检测器；`ΔQ`、`ρ` 来自反事实证据；`π_k` 来自**通过门控的证据** | 知识单元的建议文本 → `π_k`：没有可靠映射，硬做等于把未验证文本当标签 |
| `Q^μ(h,a)`，隐藏状态与观测一致 | 公共信念根 + 配对 rollout；μ 与信息假设逐条记录 | 叶子价值网络、序贯检验：先用终局胜负保证估计无偏，功效问题见 §5.4 |
| `L = L_RL + λ·E[w·KL(π_k‖π_θ)]` | `run_batch` 的可选项，对 ce / awr / q / pg 通用 | 在线自博弈中的蒸馏调度 |
| 跨模型学生 | 记录不含张量；CVPN / Transformer 按键对齐；文本学生读 `text`/`options` | LLM 后端（仓库约束：LLM 不参与强度验收，且本次无训练需求） |
| 自适应决策 | `ForkSearchPolicy(gate=…)` + 两种门控 | 学习型门控、整局预算调度 |

一个刻意的选择：**证据不用 `replay_branch`**。它重放真实对局、以真实隐藏状态为条件，得到的是
"已知对手手牌时哪个动作更好"，不是玩家可用的监督。Fork Bridge / 信念根被完整复用。

## 3. 测试结果

| 类别 | 内容 | 结果 |
|---|---|---|
| 兼容 | `pytest -m "not slow"` 全量 | 474 passed，3 skipped（基线 447 passed / 3 skipped，新增 27 项） |
| 兼容 | 与改动相关的既有 slow 测试，全部修复完成后重跑：belief root / fork bridge / CFR search（9 项），collect / info leak / replay consistency / engine bridge / llm / distill / train / feature parity（18 项） | 27 passed |
| 兼容 | 同一 store、同一命令，D27 代码 vs 本分支训练 2 epoch | 30 个权重张量逐位相同，checkpoint `config` 相同 |
| 单元/集成 | `tests/test_masd_adm.py` 快测 | 27 passed（含在上面的 474 内） |
| 信息安全/一致性/复现 | `tests/test_masd_adm.py` slow | 6 passed |
| 复现 | BC 基线同命令重训 | 权重逐位相同（B0 训练于加入训练挂钩之前，重训于之后） |

要点（各自对应一项测试）：

- 蒸馏关闭的三种写法（不传 target、`distill_coef=0`、只给 `--supervision`）都得到与基线相同的权重。
- one-hot 专家 target 的 KL 与交叉熵数值相等；padding、部分覆盖、PG 损失下损失与梯度有限。
- label-only 证据对局的 `(step, 选项数, 专家下标, 结果)` 序列与 `collect_samples` 完全相同，因此证据可按键并入任何同批语料。
- 每个 fork 任务：前缀为空、带注入 key 与合法动作列表摘要、根快照中对手手牌是合成 id；同一决策的候选共用根粒子与 rollout 种子。
- 合法动作列表与现场不符的 fork 报 `inject legal-list mismatch` 并被丢弃。
- 知识标注、状态文本、选项文本在去掉 `full_state` 后不变（只读 `player_view`）。
- 同一证据规格换不同 worker 数重跑，逐 rollout 得分相同。
- 使用真实隐藏状态的证据在任何 target 模式下都不产生 target。

未覆盖：仓库共 68 项 slow 测试，本次跑了与改动相关的 33 项，其余（NPC、Web、LLM agent 等）没有跑；
TransformerCVPN 只测了加载与前向，没有用它跑过蒸馏训练；`eval_protocol` 本身未改动、未新增测试。

## 4. 审查中发现的既有问题

### 4.1 belief-root 搜索在内联 `hands` 快照上静默回退（已修）

引擎有时把玩家的 `hands` 直接内联在玩家节点上，而不是放在 store 引用后面。`reps.belief._StatePatcher`
只处理引用形式，遇到内联形式抛 `ValueError`；`PolicyPlayer` 吞掉策略异常并改打回退动作，
且没有 recorder 时不留任何记录。

- 复现：`aywolfskirk` vs `double_geo_navia`，seed 3，第 14 步边界；D27 代码对双方视角都抛异常，本分支正常产生信念根。
- 频率：6 局（3 个种子 × 2 个座位安排）568 个边界快照中 7 个（1.2%）。
- 影响：历史上所有 `belief_root=True` 的搜索（D22/D23）在这些决策上打的是回退动作而不是搜索结果；
  影响幅度没有量化，也不改变 D26 对搜索 teacher 的限定结论。
- 修复：`ref_list` / `zone_definition_ids` 接受内联列表；回归测试 `test_belief_roots_accept_an_inline_hidden_zone`。
- 证据采集额外做了防护：出现回退动作的对局整局不产出记录。

### 4.2 确定化清掉了行动方自己手牌上的附着（已修）

`_StatePatcher.patch_card_zone` 对每张手牌都重置 `variables = {}`、`attachments = []`，包括行动方自己、
本来就看得见的手牌。手牌上的附着会改变费用与可打性，于是确定化世界在同一决策点给出的合法动作列表与现场不同。

- 暴露方式：第一轮证据采集（只校验被注入动作的语义 key）在 85 个被评估决策中有 6 个的全部或一半 rollout 被判
  key 不符，全部出现在对 `electrocharged_moon` 的两局里。
- 定位：`double_geo_navia` vs `electrocharged_moon` seed 2，第 24 步。现场 8 个合法动作，确定化根给出 11 个
  （多出 3 个"打出奇瑰之汤"）；用**原始**边界快照 fork 则与现场完全一致，所以不是快照/fork 的问题。
  原始快照与信念根逐字段比较，除被重采样的隐藏区和随机数状态外，唯一差别是行动方 4 张手牌的 `attachments` 被清空。
- 影响：历史 belief-root 搜索按**下标**注入候选动作、不做校验；列表错位时注入的是另一个动作，其得分被记到原候选头上。
  影响幅度没有量化。
- 修复：信念根里，行动方看得见且与脚手架节点是同一实体的手牌保留 `variables` / `attachments`；对手手牌仍全部重置。
  修复后上述 3 个决策的全部 rollout 通过校验。回归测试 `test_belief_roots_keep_what_the_player_sees_on_its_own_hand`
  （在 D27 代码上失败）。
- 额外防线：证据生成现在要求 fork 在注入点给出的**整个合法动作列表**与现场一致，否则丢弃该 rollout（§5.2 报告丢弃数）。
  这只检查了合法动作这一项观测，不等于确定化世界与玩家全部观测一致。

### 4.3 引擎随机种子 0 退化（已告警，行为未改）

`seed=0` 时每次掷骰都是同一面：`double_geo_navia` vs `aywolfskirk` seed 0，11 个回合的初始 8 骰全部是同一面；
换两组牌组、双方视角都如此。同一语料里：

| 种子 | 局数 | 专家胜率 | 平均每局教师决策数 |
|---|---|---|---|
| 0 | 40 | 0.44 | 107.5 |
| 1–9（各 40 局） | 360 | 0.65–0.80 | 约 50 |

后果：

- `--seed-start 0` 采的语料含这类对局；按 `val_every` 划分时种子 0 **固定落在 val**
  （`(seed − seed_start) % val_every == 0`）。种子数少时 val 的相当一部分是退化对局。
- **D27 的座位探针受影响**：它的训练语料（种子 0–9）里 18.8% 的决策（4,298 / 22,851）来自种子 0。
  各训练臂受到相同污染、评测语料（种子 1000–1003）干净，臂间比较仍是同口径，但绝对数值应重跑后再引用。
- 本次实验已剔除种子 0（§5.1）。

处理：`train.collect` 与 `collect_evidence` 遇到种子 0 告警；对局行为未改，因为重映射会让已有语料的种子 0
对局无法续跑或重放。是否在 `_build_create_param` 里重映射需要单独决策（D28 ⑥）。

## 5. 最小端到端实验

目的是验证闭环连通，不是比较强度。全部在 2 核机器上完成，总计算量约 1.2 小时（证据 49 分钟，4 次训练约 9 分钟，评测 11 分钟）；另有一轮作废的证据采集约 45 分钟（§5.2 末）。

### 5.1 设置

| 步骤 | 内容 |
|---|---|
| 对局数据 | `double_geo_navia` 脚本专家 vs 20 个专家牌组，种子 1–9，双座位，v2 编码：360 局、18,553 个决策（由 D27 语料剔除种子 0 得到）。train = 种子 2–9（16,451），val = 种子 1（2,102） |
| BC 基线 B0 | CVPN d=128，12 epoch，lr 1e-3，batch 128，seed 0；val_ce 0.918，val_acc 0.644 |
| 决策监督 / 反事实评价 | 训练集内的对局（种子 2 起，按对手字母序、双座位）；每 3 个教师决策考虑 1 个，只评估 B0 首选与专家不同的 `action` 决策；候选 = 专家动作 + B0 首选；每候选 12 个配对 rollout；续行策略 = 双方脚本专家 |
| 蒸馏 B1 | 与 B0 完全相同的命令，加 `--supervision … --distill-coef 4.0 --distill-target evidence_gated` |
| 消融 B1s | 同上，`--distill-target evidence_soft`（不过门控的软标签），只做离线对比 |
| 配对评测 | `scripts.eval_protocol`：B1 vs B0，同牌组 `double_geo_navia`，20 个对手 × 3 种子（1000–1002）× 双座位，贪心 |

### 5.2 反事实证据

30 局证据对局（种子 2，15 个对手 × 双座位），其中 29 局有被评估的决策；1,427 个教师决策中评估了 100 个，
共 2,400 个 rollout，用时 2,934 s。规格指纹、先验 checkpoint 的 sha256、引擎锁、知识库版本都写在 `manifest.json`。

| 指标 | 数值 |
|---|---|
| 信息合法的证据 | 100 / 100 |
| 被丢弃的 rollout（注入 key 或合法动作列表不符） | 0 / 2,400 |
| 12 对里**没有一对**结果不同的决策 | 61 |
| 不一致对数足以通过门控（≥6）的决策 | 4 |
| 通过门控（verified） | 3：`alternative_supported` 2，`expert_supported` 1 |
| 同一批比较在"两动作等价"假设下的期望通过数 | 0.078 |
| 100 个决策合计：B0 首选更好的对 / 专家动作更好的对 | 57 / 57（共 1,200 对） |
| 平均 \|ΔQ\| | 0.067 |
| 带知识单元标注的决策 | 100 / 100（平均 5.3 个单元，出现过 10 个不同单元） |

读法：

- 3 个 verified 远多于偶然期望的 0.078，不太可能是偶然（结论相对续行策略 μ = 双方脚本专家）。
- 但产出率只有 3%。61% 的"学生与专家分歧"在 12 个配对世界里结局完全相同，对胜负没有可测影响。
  按动作类别看（专家→备选：打牌→切人 27，切人→技能 20，切人→切人 15，打牌→结束回合 9，技能→技能 9，其余 20），
  不少分歧是行动先后或切换目标的差别；这只是按类别的观察，没有逐个核对。
- 合计 57 : 57。在这批样本上，B0 偏离专家的地方**平均而言既不更好也不更差**；BC 准确率 64% 里
  没被学到的那部分，相当一部分可能本来就不影响胜负。这是这次实验最有信息量的观察，但只有 100 个决策、
  一个牌组、一种续行策略，不宜外推。
- 知识标注是条件检测器的输出，覆盖率高是因为若干检测器的条件很宽（"可以切人""充能已满"）；
  它不说明这些单元的建议在该决策上是否正确，本实验也没有用它做任何监督。

第一轮采集（修复 §4.2 之前、只校验被注入动作的 key）在 85 个决策处中止并作废，它的唯一用途是暴露了 §4.2 的缺陷。

### 5.3 蒸馏训练与离线一致性

| 臂 | target 数 | 末轮 train CE | val CE | val acc | 与 B0 的 argmax 差异（val，2,102 个决策） |
|---|---|---|---|---|---|
| B0（BC） | — | 0.79678 | 0.91844 | 0.6441 | — |
| B0 重训（同命令） | — | 0.79678 | 0.91844 | 0.6441 | 0（权重逐位相同） |
| B1（`evidence_gated`，λ=4） | 3（2 个改判为备选，1 个确认专家） | 0.79672 | 0.91884 | 0.6461 | 27 |
| B1s（`evidence_soft`，λ=4） | 18（8 个最大项不是专家动作） | 0.79709 | 0.91867 | 0.6461 | 18 |

- 100 条记录全部按键对齐到训练 store（`unmatched = 0`、`mismatched = 0`）；97 条因证据未过门控不产生 target。
  `evidence_soft` 只有 18 个 target：符号检验 p = 1 的记录（没有不一致对、只有 1 对、或两边持平）可靠性权重为 0，被剔除。
- 3 个 verified 决策上，B1 把被支持动作的概率推向 target（0.595→0.615、0.464→0.499、0.166→0.176），
  方向正确、幅度很小，argmax 都没变；`expert_supported` 那一个仍然选错。
- 离线一致性（`scripts.evidence_agreement`，100 个决策）：verified 一致率 B0 = B1 = B1s = 2/3。
  这个 2/3 对 B0 是**构造出来的**：证据只在 B0 与专家分歧处采集，候选就是 B0 的首选，所以两个
  `alternative_supported` 恰好是 B0 已经在做的选择。它不能当作 B0 的成绩。
- B1 与 B0 在 1.3% 的决策上 argmax 不同，远多于 3 个 target 能直接解释的数量——损失的微小变化让整条
  优化轨迹偏离。也就是说，B1 与 B0 的差别主要是训练噪声，不是蒸馏信号。

### 5.4 配对评测

`scripts.eval_protocol`，`double_geo_navia`，20 个对手 × 种子 1000–1002 × 双座位，贪心，n = 120 对：

| | 胜率 | |
|---|---|---|
| B1（蒸馏） | 0.575 | Wilson 95% [0.486, 0.660] |
| B0（BC） | 0.600 | |
| 配对差 B1 − B0 | **−0.025** | 95% [−0.068, +0.018]；按对手聚类 [−0.071, +0.021] |
| 0 号位 / 1 号位 | −0.017 / −0.033 | [−0.090, +0.057] / [−0.079, +0.012] |

回退率 0、错误率 0。按对手的净差：13 个对手为 0，5 个 −1 局，2 个 +1 局。
区间包含 0。协议的非劣判定未通过（容差 0.02，区间下界 −0.068）：n=120 时区间半宽约 4.3pp，任何接近持平的臂都过不了这条线。
B0 / B1 都只是 12 epoch 的小 BC，协议里的 pooled / floor 强度门禁不在本实验的目的之内。

### 5.5 怎么读这些结果

1. **功能**：闭环每一环都产出了可检查的结果，对齐计数为 0 误配，重训可复现。这一层结论成立。
2. **实验**：作为"蒸馏是否有用"的实验，它**没有检验力**。3 个 target 相对 16,451 个训练样本，
   预期效应远小于评测噪声；B1 与 B0 的差异主要来自优化轨迹的扰动。−0.025 不应被读成负结果。
3. **功效是下一步的前提**。本次数据给出的量级：配对差的平均方差 0.082，按正态近似（双侧 α=0.05、功效 0.8），
   检出 ΔQ = 0.3 / 0.2 / 0.1 / 0.05 分别需要约 8 / 16 / 64 / 256 对 rollout；而实测平均 |ΔQ| 只有 0.067。
   终局胜负作为 rollout 回报，只能验证"失误级"的差异。可行的方向，按代价从低到高：
   - 先筛后验：用便宜的信号（先验分歧 + 语义去重，排除只差顺序/等价目标的候选）挑决策，把 rollout 集中到少数决策上；
   - 序贯检验：对不一致对数增长快的决策追加 rollout，用带停时校正的检验代替固定 12 对；
   - 低方差回报：用价值网络或生命值差做叶子评估代替终局胜负（引入偏差，需要单独校准）。
   这三项都没有实现，接口上只需要替换候选选择（`gate` / `top_k`）与 `CandidateEstimate.scores` 的来源。
4. **候选设计的含义**：候选 = 专家动作 + 学生首选时，门控蒸馏回答的是"学生与专家分歧时谁对"。
   `alternative_supported` 的 target 就是学生已有的选择，蒸馏只是抵消 BC 标签的拉力；
   真正教给学生新东西的只有 `expert_supported`。要让证据提出学生和专家都没选的动作，需要更宽的候选集和相应的预算。
5. **μ 的含义**：两个 `alternative_supported` 结论是"此处偏离一步、之后照脚本专家打"更好，
   其中一个是"不打出鎏金殿堂、直接结束回合"8:0。它可能反映专家的真实失误，也可能反映专家续行策略在该牌打出后的
   某个固定弱点；区分两者需要换续行策略复验，本次没有做。

## 6. 尚未完成与风险

| 项 | 状态 | 重开/推进条件 |
|---|---|---|
| 蒸馏臂的强度结论 | 无 | 先解决证据功效（见 §5.5），再按 `docs/EVAL_PROTOCOL.md` 做配对认证 |
| 策略知识 → 动作偏好 | 未实现 | 需要一个可检验的映射（例如单元 → 选项类别的先验），并用反事实证据逐单元检验后才可作 target |
| 56/70 个知识单元无条件检测器 | 未实现 | 条件依赖意图或隐藏信息的单元不应硬写检测器；可判定的按需补 |
| LLM 学生 | 仅接口 | 需要 scorer 后端；仍不得进入强度验收 |
| 门控搜索的强度影响 | 未评测 | 配对评测"门控搜索 vs 全量搜索 vs 无搜索"，同时报告预算 |
| 证据只覆盖 `action` 且空前缀的决策 | 设计限制 | 掷骰/选人/换牌需要在确定化世界里按语义 key 重放前缀，尚未实现 |
| 信念模型 | 假设对手牌表公开；粒子对公开信息的条件化程度取决于 `reps.belief` 的 tracker | 天梯等牌表不公开的场景需要牌表先验 |
| 种子 0 | 已告警 | 决策是否重映射；复核用过种子 0 的 val 选型 |
| 人类赛事数据 | 仅牌组池 | 数据没有轨迹，动作级监督不可行 |

## 7. 复现

```bash
export GITCG_KB_DIR=<GITCG_KB>  GITCG_DATA_RELEASE=<GITCG_Data/release/v1.0>
python -m pytest -m "not slow"                       # 兼容 + 快测
python -m pytest tests/test_masd_adm.py -m slow      # 信息安全 / 一致性 / 复现

# 最小闭环（语料与 store 见 docs/howto/masd-adm.md §4 ①）
python -m scripts.datafirst_bc_train --store-cache $STORE --d-model 128 --epochs 12 --seed 0 --out b0.pt
python -m scripts.collect_evidence --deck double_geo_navia --all-opponents --seed-start 2 --seed-count 3 \
    --sides 0 1 --rollouts 12 --top-k 1 --prior b0.pt --gate disagreement --search-every 3 \
    --max-decisions 100 --workers 2 --tag vcsd_min
python -m scripts.datafirst_bc_train --store-cache $STORE --d-model 128 --epochs 12 --seed 0 \
    --supervision $DATA/evidence/vcsd_min/supervision.jsonl --distill-coef 4.0 --out b1.pt
python -m scripts.evidence_agreement --store-cache $STORE \
    --supervision $DATA/evidence/vcsd_min/supervision.jsonl --checkpoints b0.pt b1.pt
python -m scripts.eval_protocol --contestant "neural:b1.pt#t=0" --contestant-deck double_geo_navia \
    --baseline "neural:b0.pt#t=0" --baseline-deck double_geo_navia --seeds 3 --seed-start 1000 \
    --workers 2 --tag masd_min_b1_vs_b0
```

语料、checkpoint 与证据文件在审查机的临时目录里，没有入库（`data/` 不入库）；按上面的命令可重建。
