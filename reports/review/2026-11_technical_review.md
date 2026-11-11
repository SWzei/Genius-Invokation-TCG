---
title: "2026-11 技术审查：算法路线、架构、实现质量与针对性修复"
kind: review
status: valid
freshness: 2026-11-11
machines: [cloud-2c]
authority: evidence
related: ["docs/STATUS.md", "docs/PLAYBOOK.md", "docs/failures/003-matchup-reweight-winonly.md", "reports/explore/lit/f07_code_audit.md", "PLAN.md#D27"]
---

# 2026-11 技术审查

> 范围：`genshin-GITCG@98b4dfa`（master）全部代码与文档，及工作区外的研究设想 `七圣召唤.md`。
> 审查环境：云端 2 核 / 7 GB，Python 3.12，`gitcg 0.21.0`，torch 2.15 CPU。没有使用任何既有 checkpoint 或
> `data/` 语料（不在仓库里，也不在可访问的机器上），所以本报告的引擎胜率数字全部来自仓库内已有报告；
> 本次新增的实验只用新采集的小语料，结论标明口径。
> 修改在分支 `review/2026-11-correctness`，默认行为逐字节不变（证据见 §6）。

## 0. 结论摘要

1. **路线判断：主线（逐 deck BC 底座 → on-policy PG 剥削阶梯 + 配对认证）是对的，应当保留。**
   它是仓库里唯一被独立种子复现、过完整门禁的方法（dgeo +16.8pp、ungeo +5.5pp），
   而且项目的评测、parity、失败归档纪律在同类个人项目里少见地扎实。不建议为了“形式上的先进性”替换它。
2. **发现并修复 3 个影响正确性的问题，其中 2 个此前未被识别：**
   - **H5 matchup 重加权的分组 bug**（新发现）：按局而不是按 matchup 分组；H5 的负结果测的是
     “输局加权 BC”，`failures/003` 的 H5 结论无效。
   - **对手公开骰子数恒为 0**（新发现）：引擎把对手骰子发成面值 0 的条目，快照过滤掉 0 的同时把“数量”也丢了；
     网络从未看到对手剩余骰子数——这是判断对手本回合还能做几动的核心公开信息。
   - **座位分布偏移**（f07 已指出现象，本次给出机制、量化与修复）：训练语料只来自 0 号位（引擎固定其为第 1 回合先手），
     而 global token 用**绝对座位** one-hot；1 号位评测时输入了一列训练中恒为 0、权重停在随机初始化的特征。
3. **座位缺陷的实测影响小**：同一模型改用座位相对编码，1 号位留出 CE 平均 −0.008 nats（第 1 回合 −0.018），
   top-1 不变；1 号位比 0 号位难模仿主要是局面本身（§7）。因此它是低风险的小改进，不是强度瓶颈；
   真正值得认证的是“PG 从未更新 1 号位”这一点（§3.5、§8 R3）。
4. **修复方式全部 opt-in、向后兼容**：新增特征档 `v1s/v2`、`--sides`、按座位分报；v1 特征（153 个真实决策逐字节比对）、
   采集指纹（与旧代码哈希一致）、旧 checkpoint 推理行为均不变。
5. **性能**：剖析表明 ~85% 墙钟在引擎 `game_step`，Python 侧（快照、动作枚举、编码、推理）合计 ≤15%；
   没有做无依据的 Python 性能优化。
6. **对研究设想（`七圣召唤.md` 的 VCSD）的支持度**：反事实动作价值（replay-branch MC）、分叉搜索、
   LLM 辅助/复盘的基础设施已有；**规则/策略知识库、人类专家对局、跨模型（LLM 学生）蒸馏、自适应推理预算**
   在代码里尚无落点。建议先在现有专用网络上做 E2（证据筛选）这一最小可证伪实验，而不是先引入 LLM 学生（§5）。

---

## 1. 现状：架构与算法路线

### 1.1 数据流

```
gitcg 0.21.0 引擎 (JS/V8, pybinding)
  └─ envs/match.py  Player 适配：每个请求 → reps/action_adapter 枚举全部低层合法动作
        (行动×骰子支付组合、重投子集、换牌子集、选角、选牌)
        观测只取 notification.state（信息隐藏），god view 只用于标签
  └─ reps/observation_encoder.py  token 化：global/玩家摘要/角色/状态/召唤/支援/手牌/骰子 tokens (65 维)
        + 每个候选动作的 option 特征 (68 维)
  └─ train/collect.py  一行一局 JSONL（compact，exact int id），manifest 指纹，可续跑
  └─ scripts/datafirst_bc_store.py → store (.pt) → scripts/datafirst_bc_train.py
        CVPN：token 线性投影 → 均值池化 → [全局向量 ⊕ option 向量] → MLP 打分；价值头；可选 belief 头
        loss = ce (BC) | pg (REINFORCE + value baseline + entropy) | awr | q
  └─ scripts/eval_protocol.py  20 脚本对手 × seeds × 双座位，配对 Δ、Wilson/cluster CI、floor、Elo
```

### 1.2 已验证 / 理论推测 / 未完成规划

| 类别 | 内容 | 证据 |
|---|---|---|
| **已验证（过完整门禁）** | 逐 deck PG 剥削阶梯：dgeo 0.880（Δ+0.168，800 配对）、ungeo 0.909（Δ+0.055） | `docs/PLAYBOOK.md` §1、`reports/SPECIALISTS.md` |
| **已验证（打平级）** | 逐 deck 稠密 BC 底座达到专家 parity；训练时长比数据量更重要 | `failures/005`、`reports/datafirst_bc.md` |
| **已验证（负结果，有效）** | 20-deck 单模型、AWR、胜局筛选、当前预算下的搜索蒸馏 | `failures/001,002,004` |
| **负结果但实验无效** | A2 id embedding（fp16 落盘，D25）；**H5 matchup 重加权（本次发现，§3.1）** | `failures/006`、`failures/003` 更正 |
| **理论推测/待验证** | 座位相对编码与双座位数据能提升 1 号位强度；对手骰子数能帮助 PG 学会“抢先/防守时机” | §7 给出模仿层面的证据，胜率待认证 |
| **未完成规划** | SoG/ReBeL 主线（公共信念 + continual resolving，D3/D15）、league/PFSP、orchestrator 自迭代、LLM 组牌 | `PLAN.md` §10、`orchestrator/README.md`（占位） |

一个值得直说的观察：`PLAN.md` D3 把 “SoG/ReBeL” 定为训练主线，但实际产出强度的是 BC + REINFORCE，
搜索线在 D23/D26 后处于“限定/冻结”。文档已经如实记录了这一点，但 README 首句仍写“SoG/ReBeL 路线”，
对新读者有误导；建议在 README 把“当前有效主线”与“长期研究路线”分开写。

---

## 2. 研究对比：技术路线的适用条件

| 路线 | 代表工作 | 适用条件 | 在本项目的位置与判断 |
|---|---|---|---|
| BC 冷启动 + on-policy PG | AlphaStar（监督预训练 + RL）、DouZero（大规模 MC 自博弈） | 有强示范、引擎可快速模拟、目标是剥削固定对手池 | **当前主线，证据最强**。局限：REINFORCE 以整局回报给每一步记功，方差大，所以只在 parity+ deck 上有效（PLAYBOOK 已写明） |
| 信念 + 搜索（continual resolving） | DeepStack、ReBeL、Student of Games | 价值函数校准、信念可算、搜索预算足够 | 冻结。D26 已修价值语义；本次进一步让信念追踪器使用引擎给出的**精确**对手骰数（§3.2）。重开仍需 D23 三前置 |
| 完全信息采样（PIMC/确定化） | Long et al. 2010 对 PIMC 的分析 | 隐藏信息对决策影响小、策略融合误差可接受 | `envs/cfr_search` 的粒子根本质上属于此类；七圣召唤中对手手牌与牌序影响中等，风险是“策略融合”导致过度自信 |
| League / PFSP | AlphaStar | 目标是鲁棒而非剥削；需大量算力 | P2 排产合理；当前 20 脚本池固定，剥削目标下收益有限 |
| DAgger | Ross et al. 2011 | 学生分布偏离专家分布 | 正确定位为“修分布”而非“超专家”（文献报告已写） |
| 实体集合编码 | Deep Sets（均值池化）、Transformer 实体编码（AlphaStar） | 状态是可变长实体集合 | 现用 Deep Sets 式均值池化 + 标量 id；表达力的主要短板是卡牌身份只是一个单调标量（A2 正要修），而不是“缺注意力” |

**方法创新性的区分**：仓库内目前的方法全部是已有方法的工程整合（BC、REINFORCE、MCCFR、replay-branch MC）。
可能构成原创贡献的方向是 `七圣召唤.md` 提出的“按证据质量与适用边界加权的教师监督”（§5），
但它目前没有实现，也没有最小实验。

---

## 3. 关键问题（按影响排序）

### 3.1 H5 matchup 重加权按“局”分组（正确性；结论层影响）

- **代码依据**：`scripts/train_bc_scale.py::matchup_weights_for_store` 用 `group = tuple(key[:-1])`；
  store 键由 `load_store`/`datafirst_bc_store` 写成 `(deck, opponent, seed, step)`，所以 `key[:-1]` 是 **(deck, opponent, seed)**＝一局。
- **实际影响**：每局只有一个回报值，`deficit` 退化为“输局 ×1.45、胜局 ×1.0 再归一化”，`balance` 退化为“每局等权”。
  仓库报告里的“实测权重范围 0.84–1.22”恰好是这个两点分布（输局约 40% 时 1.45/1.18≈1.23、1/1.18≈0.85），
  而不是 matchup 粒度的连续权重——旁证 bug 在 H5 实验中确实生效。
- **为什么测试没抓到**：fixture 把同一 matchup 的所有样本放在 seed 0。
- **修复**：`matchup_of_key()`（兼容 3/4/5 元键）；新增 3 个使用真实键布局的测试，旧实现其中 2 个失败。
- **结论修订**：H5 的 −9.1pp（SA）/−3.4pp（dvalin）测的是“输局加权 BC”；matchup 重加权本身未被检验。
  `failures/003` 的其余归因（teacher 胜负方向、样本稀少、没有新信息）仍成立，所以重开条件不变。

### 3.2 对手公开骰子数恒为 0（信息缺失；影响模型能力上限）

- **代码依据**：`reps/snapshot.py` 中 `dice=tuple(... if int(die) != 0)`。实测引擎视角下对手骰子是
  8 个 `0`（面值隐藏、数量公开），过滤后对手 `dice == ()`；编码器的 `player_summary` 骰子标量因此对对手恒为 0。
  编码器为此预留了 `opponent_public_dice_count` 参数，但采集与推理都没有传（f07 审计把它判为“训练/推理一致”，
  一致是对的，但信息是缺的）。
- **实际影响**：对手剩余骰子数决定对手本回合还能做几个动作，是“继续行动 / 宣布结束（抢先）/ 提前防守”的核心输入
  （知识库 S02-P5、S08-P1）。脚本专家不读这个量，所以它对 BC 指标几乎没有影响，但它限制了 PG 能学到的策略上限。
  另外 `reps/public_state.py` 的信念追踪器用“8 − 观察到的花费”估计对手骰数，忽略生骰/转骰/卡牌效果。
- **修复**：快照新增 `dice_count`（含隐藏面值的公开数量）；`v2` 档把它编码进对手摘要 token；信念追踪器优先使用精确值。
  信息安全测试：同一公开数量、不同骰面 → v2 输入逐元素相同。

### 3.3 座位分布偏移（分布偏移；影响一半的评测局）

- **代码依据**：`train/data.py::collect_samples` 的 teacher 永远是 player 0；引擎固定 0 号位为第 1 回合先手
  （本次 12/12 局复核；KB R01 同结论）；`reps/observation_encoder.py::_build_token` 在 global token 写
  `acting_player`/`current_turn` 的**绝对**座位 one-hot；评测协议双座位各半。
- **机制**：0 号位语料里 `acting_player==1` 列恒为 0，这一列对第一层线性投影的梯度恒为 0，权重停留在随机初始化；
  1 号位推理时这列变成 1，相当于向 global token 加一个随机向量，同时去掉一个训练中一直存在的偏置。
  此外“第 1 回合后手”这一真实局面在训练中从未出现。
- **修复**：
  - `v1s`/`v2` 档：flag 改为相对行动方（槽 0＝行动方 / 轮到行动方）。**在 0 号位与 v1 逐字节相同**，
    所以对所有现有（只在 0 号位训练的）checkpoint，`neural:<ckpt>#seatrel=1` 是**零训练**的修复候选；
  - `train.collect --sides both`（双座位采集，同一 seed 两座位同属 train 或 val）；
  - 评测报告新增 `per_side`（含配对 Δ 分座位）。
- **量化**：见 §7。

### 3.4 模型表达力（设计；本次不改）

CVPN 先对每个 token 独立线性投影再均值池化，卡牌/实体身份只以 `id/400000` 一个标量进入。
这意味着“哪张牌”只能靠一个单调数值区分，且 token 之间没有交互。这是比注意力更基础的短板，A2（exact int id embedding）
正是对症方案，D25 已经安排在 parity 后重做。本次不引入新结构，理由：parity 门禁规定在先，
而且结构改动必须用引擎胜率而非 val 指标验收，超出本次可用算力。

### 3.5 PG 实现细节（检查通过，有两处效率建议）

逐行检查了 `run_batch` 的 pg 分支：屏蔽填充选项后计算熵、优势标准化有方差阈值、裁剪、梯度裁剪、
采样温度 1.0 与 log-prob 一致、温度采样 RNG 按任务种子复现——未发现错误。两点建议：

1. 阶梯脚本用 `datafirst_bc_store --val-every 10`，会丢掉 10% 的 on-policy 局；PG 不靠 val 选型，可用 `--val-every 0`。
2. PG 只在 0 号位采样，所以 1 号位策略从未被 RL 改进；`--sides both` 后 PG 可以同时改进两座位（需配合 v1s/v2）。

### 3.6 性能（剖析结论：不改）

cProfile（3 局 neural vs expert，随机初始化 CVPN d256）：`gitcg.low_level.game_step` 自身耗时约 85%，
`envs.match._decide` 合计约 13%（其中动作枚举/高层编码 ~5%、观测编码 ~2%、网络前向 <1%）。
吞吐瓶颈是引擎本身；Python 侧优化的上限约 1.15×，不值得为此增加复杂度。

### 3.7 测试卫生

`tests/test_npc_spec.py::test_skill_damage_table_matches_engine_gts` 在没有 `refs/` 的机器上必失败
（标准角色的 `.gts` 只在 `refs/` 里）。改为无 `refs/` 时跳过这些条目。修复后快速门禁全绿。

---

## 4. 修改清单

| # | 修改 | 文件 | 兼容性 |
|---|---|---|---|
| 1 | H5 分组改为 matchup；`matchup_of_key`/`game_of_key` | `scripts/train_bc_scale.py` | 只影响 `--matchup-weight` 非 none（PLAYBOOK 已禁用原实现） |
| 2 | `PlayerSnapshot.dice_count`、`public_dice_count()` | `reps/schema.py`、`reps/snapshot.py`、`reps/replay.py`、`reps/public_state.py` | 新增字段有默认值；追踪器优先精确值 |
| 3 | 编码器 flag `seat_relative_turn`、`public_opponent_dice`；档位 v1/v1s/v2；`to_dict` 对 v1 不输出新键 | `reps/observation_encoder.py`、`envs/observation.py` | v1 逐字节不变 |
| 4 | `neural:<ckpt>#seatrel=1`；`neural_spec_encoder()` | `envs/policy.py` | 新选项，默认关 |
| 5 | `train.collect --sides --encoder-profile`；manifest 记录 `encoder_config`；`neural:` teacher 档位校验 | `train/collect.py`、`train/data.py` | 默认值下指纹与旧代码相同 |
| 6 | store 从 manifest 取编码档、拒绝混档；1 号位局键加 side | `scripts/datafirst_bc_store.py`、`scripts/train_bc_scale.py` | 0 号位键不变 |
| 7 | `--init-from` 编码档不一致时告警 | `scripts/datafirst_bc_train.py` | 只打印 |
| 8 | 评测按座位分报（汇总与配对 Δ） | `eval/scoreboard.py`、`scripts/eval_protocol.py` | 报告新增字段 |
| 9 | 座位探针 `scripts/explore/seat_probe.py` | 新文件 | — |
| 10 | 测试：`test_encoder_profiles.py`、`test_seat_coverage.py`、`test_matchup_weights.py` 追加；`test_npc_spec.py` 跳过条件 | `tests/` | — |
| 11 | 文档：PLAN D27、decisions、failures/003 更正、STATUS、howto、tests/README | `docs/`、`PLAN.md` | 追加不改写 |

---

## 5. 对研究设想（`七圣召唤.md`）的支持度评估

| 设想中的要素 | 当前框架支持 | 差距 | 建议 |
|---|---|---|---|
| 高质量规则/策略知识 | 无（模型不读任何规则/策略文本；脚本专家规则是唯一的人类知识来源） | `GITCG_KB` 70 个策略单元与仓库无连接 | 先把 KB 单元作为**评测探针**：对能形式化的条件（如“能击倒时优先击倒”）写局面检测器，统计模型/专家在这些局面的行为一致率；这比直接蒸馏文本便宜且可证伪 |
| 专家对局数据 | 只有 20 个脚本专家；`NOTICE`/PLAN 提到 piovium 公开复盘但未接入 | 无人类对局 | 人类对局接入的前提是动作/观测与现有 adapter 对齐（需 parity 级验证），工作量大；在剥削脚本池的目标下优先级低 |
| 反事实 ΔQ | `train/replay_branch.py`（同种子重放 + 注入候选 + rollout 均值）、`envs/fork_bridge`（边界快照分叉） | rollout 策略固定、上帝视角分叉会泄漏隐藏信息 | 这是 VCSD 的“证据”部件，已经可用；关键是用**信念采样**而非真实隐藏状态做分叉（D26 已修 dice 采样） |
| 证据/可靠性加权蒸馏 w(h,k) | `--matchup-weight` 是唯一的样本权重通路（本次修正其分组） | 没有按决策的权重 | 最小实验 E2：对一小批 BC 决策用 replay-branch 估计 ΔQ(teacher, alt)，按 ΔQ 置信度加权 vs 均匀，配对认证。成本可控（每决策 1+K·R 局） |
| 跨模型蒸馏（LLM 学生） | LLM 只做辅助重排/复盘，且与纯策略分开报分 | 无 LLM 训练管线 | 在专用网络上证实证据加权有用之前，不建议引入 LLM 学生：评测成本与方差会同时上升，且无法区分“知识有用”与“模型更大” |
| 自适应决策/推理预算 | 无（搜索冻结；神经策略固定前向） | — | 待搜索价值头校准后，可做“价值不确定度门控的按需搜索”（与 D23 的“门控式覆盖”一致） |

---

## 6. 验证

| 项 | 方法 | 结果 |
|---|---|---|
| 快速门禁 | `pytest -m "not slow"` | 见 §6.1 |
| v1 特征不变 | 同两局（双座位，153 个决策）分别用旧代码与新代码编码，比较 pickle 哈希 | 完全一致（`7b69aa8d…`） |
| 采集指纹不变 | 两个代表性 spec（jsonl 默认、compact + neural teacher）在旧/新代码下的指纹 | 完全一致（写入 `test_encoder_profiles.py`） |
| H5 修复 | 新增测试在旧实现上失败、新实现上通过 | 2 失败 → 通过 |
| 双座位采集端到端 | `train.collect --sides both --encoder-profile v2`（8 局）→ store → 续跑 | 8 局、0 去重、续跑 0 待跑 |
| v2→v1/v1s 转换 | 与直接编码逐元素比较 | 一致 |

### 6.1 测试结果

- 快速门禁 `pytest -m "not slow"`：**447 passed, 3 skipped**（审查前 428 passed + 1 failed；失败项即 §3.7 的环境依赖）。
- 慢测 `pytest -m slow`：除 3 个 NPC 用例外全部通过；这 3 个（`test_npc_contestant/eval/policy` 的同种子复现）
  在**未修改的 HEAD** 上同样失败——它们需要 NPC 引擎 overlay（PvE-B1）却没有像 `test_npc_enemies.py` 那样
  在未安装时跳过。属既有的测试卫生问题，记入 §8。

---

## 7. 座位实验（模仿层面，非胜率）

**问题**：§3.3 的座位缺陷在实际网络上有多大影响？v1s/v2 与双座位数据能消除多少？

**设计**（`scripts/explore/seat_probe.py`，原始结果 `reports/review/seat_probe_20261111.json`、`seat_probe_flip_20261111.json`）：

- 语料：`double_geo_navia` 脚本专家 vs 全部 20 个对手，`--sides both --encoder-profile v2`；
  训练 seeds 0–9（400 局 / 22,851 决策），留出 seeds 1000–1003（160 局 / 7,785 决策，两座位各一半）。
- 脚本专家不读座位，所以同一局面在两个座位上的“正确”动作相同；用留出专家决策上的 CE / top-1 一致率
  衡量座位对**模型**的影响，不受胜率噪声干扰。v1/v1s 特征由 v2 特征**精确**换算（有测试），所有臂看到完全相同的决策。
- CVPN d=128，20 epoch，lr 1e-3，每臂 4 个训练种子（臂 A 另加 2 个种子做 argmax 翻转诊断）。

| 臂 | 训练数据 | 特征 | 留出 seat0 CE / acc | 留出 seat1 CE / acc | seat1 第 1 回合 CE |
|---|---|---|---|---|---|
| A（现状） | 0 号位 200 局 | v1 | 0.782±0.020 / 0.708 | 0.915±0.014 / 0.681 | 1.031 |
| A + `#seatrel=1`（同一模型） | 同上 | v1s 推理 | 0.782（逐字节相同） | 0.904±0.010 / 0.680 | 1.010 |
| C | 0 号位 200 局 | v2 | 0.782 / 0.707 | 0.906±0.010 / 0.681 | 1.013 |
| D | 两座位各 100 局（seeds 0–4） | v2 | 0.885±0.050 / 0.671 | 0.924±0.037 / 0.655 | 1.133 |
| E | 两座位各 200 局（seeds 0–9） | v2 | 0.684±0.029 / 0.740 | 0.756±0.013 / 0.717 | 0.854 |

（± 为训练种子间标准差。）

**结论**（按证据强度排序）：

1. **座位 flag 缺陷是真实的，但在模仿层面很小。** 同一模型改用座位相对编码（`#seatrel=1`），1 号位 CE 在 6/6 个训练种子中
   5 个下降、1 个持平：平均 −0.008 nats（配对 t=−2.5）；第 1 回合 −0.018 nats（6/6 下降，t=−4.0）；
   top-1 一致率不变（−0.0003）。贪心动作翻转率 1.4–4.0%，低于 f07 预设的 10% 阈值；翻转处 seatrel 与专家一致的次数
   ≥ 原样（15 vs 15、48 vs 42）。0 号位逐字节不变（这是设计保证）。
2. **1 号位比 0 号位难模仿，主要是局面本身，而不是特征。** 修正特征后 seat1−seat0 的 CE 差距仍有 0.12（A/C）；
   即使用两座位数据训练（E），差距仍有 0.07。“0 号位先手”的引擎规则让两个座位面对的局面分布确实不同。
3. **对手骰子数对模仿没有可测影响**（C ≈ A+seatrel），符合预期：脚本专家不读这个量。它的价值只能在 PG/胜率层面检验。
4. **1 号位对局本身就是有用的训练数据。** E 的数据量是 A 的两倍，两个座位都显著变好（seat0 0.78→0.68，seat1 0.90→0.76）；
   这里数据量与座位覆盖混在一起，不能单独归因于座位。D（总局数与 A 相同，但只有一半的不同发牌）
   在两座位都不如 A，且方差大，说明在这个小数据规模下**不同发牌的数量**比座位多样性更重要。
   注意：仓库已有证据表明 BC 数据量对引擎胜率不显著（`failures/005`），所以 E 的模仿收益不能推出胜率收益。

**对排产的含义**：

- 对现有 v1 checkpoint，`#seatrel=1` 是零训练、零风险（0 号位不变）的改进候选，但预期效应小；
  需要用 `eval_protocol --sides 1` 做配对 A/B 才能写进 PLAYBOOK。按 EVAL_PROTOCOL 的功效表，若真实效应 ≤2pp，
  400 局只能做筛选。
- 对 PG 阶梯，更重要的是 1 号位**从未被 RL 更新过**（§3.5）。双座位采集 + v1s/v2 让 PG 同时更新两个座位，
  这在模仿实验里无法评估，只能做一轮配对认证。

---

## 8. 尚未解决的问题与建议

按“预期影响 / 成本”排序。所有强度结论都必须走 `scripts/eval_protocol.py` 配对认证（预注册 + 新种子）。

| # | 问题 | 为什么重要 | 建议的最小实验 | 估计成本（本机 12 核） |
|---|---|---|---|---|
| R1 | 现有已认证臂（dgeo/ungeo PG）在 1 号位是否弱于 0 号位 | 一半评测局在 1 号位；新报告已按座位分报，可直接回答 | 在保存了 raw 流（`data/eval/<tag>.jsonl`）的机器上重跑原认证命令：已完成任务全部跳过，只重新聚合，报告里出现 `per_side`；两臂比较用 `compare_eval_runs`（同样含 `per_side`）。零新对局 | 分钟级 |
| R2 | `#seatrel=1` 的胜率效应 | 零训练的修复候选 | `eval_protocol --sides 1`，`neural:<ckpt>` vs `neural:<ckpt>#seatrel=1`，20 seeds × 20 对手 | ~800 局，~0.5 h |
| R3 | 双座位 PG（v1s 迁移） | PG 从未更新 1 号位 | 在 dgeo 上做一轮：`--teacher-spec neural:<ckpt>#t=1.0#seatrel=1 --encoder-profile v1s --sides both`，与单座位轮配对比较 | 一轮阶梯（~2k 采集 + 800 评测） |
| R4 | 对手骰子数（v2）对 PG 的作用 | 涉及“抢先/防守时机”这类 BC 学不到的决策 | v2 必须从 BC 底座重新训练（新特征在 v1 底座里没有权重）；先只在一个 parity+ deck 上做 | 一次底座训练 + 一轮阶梯 |
| R5 | H5（真正的 matchup 重加权）未被检验 | 原负结果无效 | 不建议重开 loss 层权重；按 failures/003 的重开条件在采集层做 | — |
| R6 | 模型表达力（标量 id + 均值池化） | 卡牌身份不可学是结构性上限 | 按 D25 在 exact id 语料上重做 A2（不变） | 依 A800 窗口 |
| R7 | 知识库与模型断开 | VCSD 的前提 | 先做“KB 条件 → 局面检测器 → 行为一致率”评测探针，再决定是否蒸馏 | 小 |
| R8 | 证据加权蒸馏（VCSD E2） | 可能的原创贡献点 | replay-branch ΔQ 只标 1–2k 决策，按 ΔQ 置信度加权 vs 均匀，配对认证 | 标注成本 (1+K·R) 局/决策，需预算评估 |
| R10 | 3 个 NPC 慢测在未安装 overlay 的机器上失败而非跳过 | CI 噪声，掩盖真实回归 | 复用 `test_npc_enemies.py` 的 overlay 检测，未安装时 skip | 小 |
| R9 | README 首句的路线表述 | 新读者会以为 SoG/ReBeL 是在用的主线 | 区分“当前有效主线”与“长期研究路线” | 文档 |

**实验限制**：本次审查没有接触任何已训练 checkpoint 或历史语料；第 7 节只是一个 deck、小数据量、模仿指标的实验，
不能代替引擎胜率；剖析在 2 核共享机器上进行，比例可信、绝对值不可信。
