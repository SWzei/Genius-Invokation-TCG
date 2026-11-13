# STATUS — 当前状态（2026-10-27；2026-11 增补：审查 D27、MASD-ADM 兼容层 D28、实验平台 D29）

> 只写“现在有效”的事实。历史与一次性结果见 `reports/`；失败归因见 `docs/failures/`。
> 所有胜率默认是**纯策略**、固定 20 套脚本池、双方各半、配对种子；门禁口径见 `docs/EVAL_PROTOCOL.md`。

## 1. 当前最强的已认证策略

| deck | arm | pooled | 同 deck 专家 | 配对 Δ [95% CI] | 配对数 | floor 违规 | 门禁 |
|---|---|---:|---:|---:|---:|---:|---|
| `double_geo_navia` | `final20_dgeo` | **0.8800** | 0.7125 | **+0.1675** [+0.134,+0.201] | 800 | 0 | **PASS** |
| `unyielding_geo` | `final20_ungeo` | **0.9087** | 0.8538 | **+0.0550** [+0.027,+0.083] | 800 | 0 | **PASS** |
| `dvalin_bonk` | `rl_dvalin1_dvalin_bonk` | 0.7800 | 0.7425 | +0.0375 [−0.009,+0.084] | 400 | 1 | fail（平台期 +3pp） |
| `shenhe_double_swirl` | `rl_shenhe1_...` | 0.7025 | 0.6650 | +0.0375 [−0.014,+0.089] | 400 | 2 | fail |
| `electro_manifestation_nuke` | `rl_electro1_...` | 0.6850 | 0.6550 | +0.0300 [−0.025,+0.085] | 400 | 2 | fail |

- 19 个 deck 有认证臂；**2 个完整门禁 PASS**（dgeo/ungeo）；6 个达到专家 parity 或更好。
- 生成源：`python -m scripts.specialist_table` → `reports/SPECIALISTS.md`；方法见 `docs/PLAYBOOK.md`。
- `dvalin` 的 +3.75pp 在 10 seeds 上 CI 含 0，不能写成“超过专家”；只算 plateau。

## 2. 通用 BC 基线（A0）

| deck | A0 pooled | 说明 |
|---|---:|---|
| `double_geo_navia` | 0.720 | `h4m e150` 4-deck 通用 BC；seed-900（旧协议实际 1800–1809），400 配对 |
| `unyielding_geo` | 0.828 | 同上 |
| `dvalin_bonk` | 0.760 | 同上 |

- **A2（identity embeddings）判负无效**：compact fp16 把 definition id 压成不可逆假 id；A0i 的 val_acc 0.866 / 引擎 dgeo 0.266 是数据事故，不是 id 路线结论。见 D25、`reports/explore/p0_parity_20261027.md`。
- A0 仍是当前 4-deck 通用 BC 基线；不要用 A0i/A0i_noid 当通用底座。

## 3. P0 状态（2026-10-27）

| 项 | 状态 | 证据 |
|---|---|---|
| parity harness（store↔engine 逐元素） | ✅ | `envs/parity.py`、`scripts/parity_store_live.py`、`tests/test_feature_parity.py` |
| exact definition id（compact int sidecar） | ✅ | 旧 fp16 2 决策 10 token/15 option id 失配；新 4-deck 85,573/85,573 决策有 exact id |
| 干净 4-deck 语料 / store | ✅ | `data/store/p0_clean_four_decks.pt`（1,600 局 / 74,407 train / 11,166 val） |
| `--save-best`（val_ce）+ last | ✅ | `datafirst_bc_train --save-best`；A2 best ep70 不再丢 |
| init / eval / 温度采样 seed | ✅ | 模型构造前 seed；`#t>0` 用 per-policy `torch.Generator`；`--seed-start` 不再双倍偏移 |
| 价值语义 / dice | ✅ | `PriorResolver.value_probability()`；identity→概率；acting→p0；dice i.i.d. |
| A2 重做（150ep，dgeo/dvalin） | ⏳ 等 A800 | `scripts/p0_a2_rerun.sh` 已封装 |
| seat 覆盖 A/B（p0-only vs 双边） | ◐ 模仿层面已测；胜率未测 | D27：`#seatrel=1` 使 1 号位留出 CE −0.008（第 1 回合 −0.018）、top-1 不变；`--sides both`/v1s/v2 已实现（opt-in）。胜率 A/B 见 `reports/review/2026-11_technical_review.md` §8 R2/R3 |

## 3b. MASD-ADM / VCSD 兼容层（D28，2026-11-11）

| 项 | 状态 | 证据 |
|---|---|---|
| 决策监督契约（`DecisionSupervision`）、精确符号检验门控 | ✅ 已实现并测试 | `reps/strategy.py`、`tests/test_masd_adm.py` |
| 知识库 / 赛事牌组适配 | ✅（知识单元 14/70 有条件检测器；人类数据仅牌组与胜负） | `reps/knowledge.py`、`envs/tournament_decks.py` |
| 信息合法反事实证据（label-only、公共信念根） | ✅ 已实现并测试 | `train/evidence.py`、`scripts/collect_evidence.py` |
| 蒸馏挂钩（默认关，关闭时权重逐位相同） | ✅ 已实现并测试 | `train/strategy_targets.py`、`datafirst_bc_train --supervision` |
| 文本/LLM 学生、自适应门控 | ◐ 接口与信息边界已测；无 LLM 后端；门控未做强度评测 | `train/student.py`、`envs/adaptive.py` |
| 蒸馏臂强度 | ✗ 未认证（最小闭环只验证连通性） | `reports/review/2026-11_masd_adm_compat.md` §5 |

用法与边界：`docs/howto/masd-adm.md`。

## 3c. 实验平台（D29，2026-11-12）

| 项 | 状态 | 证据 |
|---|---|---|
| 模型档案与三种协议（OpenAI 兼容 / Anthropic / Gemini）、重试、预算、调用日志 | ✅ 已实现；对本地仿真服务测试 | `common/llm_providers.py`、`tests/test_llm_providers.py` |
| 真实模型接口 | ✗ 未调用（无密钥） | 用 `scripts.llm_smoke` 自检 |
| LLM 完整对局策略（合法性 / 回退 / 留痕） | ✅ 已实现并测试（离线模型整局对战） | `agents/llm_policy.py`、`tests/test_llm_platform.py` |
| 知识配置（规则 / 策略 / 专家示例 / 自定义，分块、溯源、版本告警） | ✅ 已实现并测试 | `reps/knowledge_pack.py` |
| 知识注入对强度的影响 | ✗ 未测量 | 工具：`scripts.llm_arena` |
| Web 实验台（人机 / AI 对 AI / 干预 / 建议 / 讨论 / 评价 / 回放 / 对比 / 导出） | ✅ 已实现；API 测试 + 浏览器端到端 | `lab/`、`tests/test_lab.py` |
| 人工数据 → BC 语料 / 监督记录 / `--distill-target human` | ✅ 已实现并测试（导出 → 建 store → 训练 1 轮） | `lab/replay.py`、`lab/export.py` |
| 人工纠正的反事实校验 | ◐ 已实现，1 项慢测；未做规模化实验 | `lab/verify.py` |

用法与限制：`docs/howto/lab.md`。实验台与 LLM 玩家不进强度验收。

## 4. 当前排产

| 优先级 | 实验 | 目的 | 预算 | 停止条件 |
|---|---|---|---|---|
| P1 | DAgger 诊断（200 局，0 训练） | 模型状态 vs 专家状态一致率 gap | ~0.5h | gap <3pp → 停 |
| P1 | 可修 matchup 靶向采集 pilot（nahida × 1 target） | floor 修补 | 1,400 采集 + 960 评测，2–3h | target Δ <+10pp → 停 |
| P1 | specialist 扩张（dvalin/shenhe/electro） | 把 PASS 从 2 个扩到更多 deck | 18k 采集，6–10h CPU | 3 轮 0/3 → 停 |
| P1 | portfolio/router（0 新训练） | 现有 arm 的 floor 路由 | 12k 评测 | routed <最佳单 arm +3pp → 不做 |
| P2 | league/PFSP + anchor | specialist 防漂移 | 每轮 2k 局 | 非劣 CI 下界 <−0.02 → 回滚 |
| P2 | value 拆头 + 搜索重开 | 修复 D23 的测量问题后再判 | 1 次训练 + 3.2k 局 | parity/价值门禁不过 → 不重开 |
| P3 | 候选 self-attention probe | 只在 0 成本诊断有信号时做 | 0 新采集 | store 涨引擎不涨 → 停 |

## 5. 评测与统计口径（当前）

- **筛选**：400 配对局（10 seeds）只抓大效应；不能做“非劣”判定。
- **确认/非劣**：1,400–1,600 配对局；`CI_low ≥ −0.02` 需要 ~1,400 局。
- ** superiority 5pp**：20–28 seeds（800–1,120 局）；3pp 需 2,000–3,000 局。
- **floor**：绝对 floor + 相对同 deck 专家的配对 Δ；teacher-limited matchup（expert Wilson low <45%）不要求绝对 45%（D25）。
- **model selection**：`val_ce` early stop + 小样本配对引擎 screen + 冻结认证种子；**不看 val_acc**。

## 6. 阻塞与已知风险

1. **A800 不可随时可用**：A2 150ep 重做、GPU 放大训练依赖窗口；采集/评测不要放窗口（D21）。
2. **本机 CPU 是共享资源**：采集/评测/训练不要同时开满；评测 worker 设 `OMP_NUM_THREADS=1`。
3. **旧 compact 语料不能用于 id 特征训练**：缺 exact id；只能用于非 id 模型或重采。
4. **P0-E seat 覆盖（2026-11 更新，D27）**：机制已确认（训练只在 0 号位 + global token 绝对座位 one-hot），
   模仿层面影响小；评测报告现已按座位分报（`summary.per_side`、`paired_vs_baseline.per_side`）。
   PG 阶梯仍只在 0 号位采样，1 号位策略从未被 RL 更新——双座位 PG 未认证前，不要把 1 号位强度差异归因于模型。
5. **H5 matchup 重加权的负结果无效（D27）**：实现按局分组，测的是“输局加权 BC”；已修复，`failures/003` 已更正。
6. **引擎随机种子 0 退化（D28）**：种子 0 的对局每次掷骰都是同一面，不是正常分布内的对局。
   `--seed-start 0` 采的语料含这类对局，且按 `val_every` 划分时它们固定落在 val；新采集从种子 1 起，
   旧语料上依据 `val_ce` 的选型要按此复核。对局行为未改，重映射与否待定。
7. **belief-root 搜索的两个历史缺陷（D28，已修）**：约 1% 的边界快照把 `hands` 内联序列化，旧实现在这些决策上
   抛异常并被吞成回退动作；确定化还会清掉行动方自己手牌上的附着，使合法动作列表与现场不一致、按下标注入的
   动作可能不是原动作。对 D22/D23 搜索结果的影响未量化。
8. **文档迁移已落地主体**：`docs/` 骨架、`AGENTS.md`/`README.md`、`STATUS`/`PLAYBOOK`/`EVAL_PROTOCOL`、
   `failures/`、`environments/`、`decisions/`、`howto/` 已建；旧报告保留在 `reports/`。
   仍待持续清理：模块 README 的历史状态、全部报告的 front-matter、`PLAN §10` 之外的旧状态句。

## 7. 相关入口

- 有效方法：`docs/PLAYBOOK.md`
- 失败/重开：`docs/failures/README.md`
- 机器环境：`docs/environments/README.md`
- 评测协议：`docs/EVAL_PROTOCOL.md`
- 决策索引：`docs/decisions/README.md`
