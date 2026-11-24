# STATUS — 当前状态（2026-10-27；2026-11 增补：审查 D27、MASD-ADM 兼容层 D28、实验平台 D29、平台接入与 Benchmark D30、DeepSeek 与知识库评测 D31、知识接入分阶段优化 D32、针对性优化与防过拟合检验 D33、模型对战驱动的知识库分层进化 D34、排查与分歧点评测 D35、多轮进化与镜像对战 D36、评测指标与派生事实 D37）

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
| 真实模型接口 | ◐ 仅智谱 GLM 已实测（D30，见 §3d）；OpenAI / Anthropic / Gemini / DeepSeek 未调用 | `reports/review/2026-11_glm_validation.md` |
| LLM 完整对局策略（合法性 / 回退 / 留痕） | ✅ 已实现并测试（离线模型整局对战） | `agents/llm_policy.py`、`tests/test_llm_platform.py` |
| 知识配置（规则 / 策略 / 专家示例 / 自定义，分块、溯源、版本告警） | ✅ 已实现并测试 | `reps/knowledge_pack.py` |
| 知识注入对强度的影响 | ◐ 已小样本实测（D30）：未测出收益，方向偏负，不显著 | `reports/review/2026-11_benchmark.md §2.2` |
| Web 实验台（人机 / AI 对 AI / 干预 / 建议 / 讨论 / 评价 / 回放 / 对比 / 导出） | ✅ 已实现；API 测试 + 浏览器端到端 | `lab/`、`tests/test_lab.py` |
| 人工数据 → BC 语料 / 监督记录 / `--distill-target human` | ✅ 已实现并测试（导出 → 建 store → 训练 1 轮） | `lab/replay.py`、`lab/export.py` |
| 人工纠正的反事实校验 | ◐ 已实现，1 项慢测；未做规模化实验 | `lab/verify.py` |

用法与限制：`docs/howto/lab.md`。实验台与 LLM 玩家不进强度验收。

## 3d. 对战平台接入、Benchmark、GLM 实测（D30，2026-11-15）

| 项 | 状态 | 证据 |
|---|---|---|
| 平台调研（genius-invokation 对战平台、BetterGI、LPSim、dgisim、GITCGSim 等） | ✅ 完成 | `reports/review/2026-11_platform_review.md` |
| 对战平台房间客户端（任何策略 spec 以游客身份上桌） | ✅ 已实现；本机上游服务端整局实测（脚本、GLM-5.3 各 1 局）；**线上只读，未与真人对局** | `envs/platform_room.py`、`scripts/platform_play.py`、`tests/test_platform_room.py` |
| Benchmark 对局套件（`lite` 56 格 / `core` 480 格 / `home` 16 格） | ✅ 已实现并测试；`lite`、`home` 已跑，**`core` 未跑** | `bench/`、`configs/bench/`、`tests/test_bench.py` |
| 决策场景集 `v1`（292 个：斩杀 52 / 专家一致 160 / 读局面 80） | ✅ 已生成并评测 | `configs/bench/scenarios/v1.json`、`reports/bench/scen_v1.md` |
| 真实 GLM 接口（`glm-5.3`，Coding Plan 端点） | ✅ 85 局 + 平台 1 局 + 场景题；零回退；首答合法率 99.6% | `reports/review/2026-11_glm_validation.md` |
| GLM-5.3 在 `lite` 上的表现 | 28 局 0.929 [0.77, 0.98]；对 `heuristic` 配对 +0.41（13 好 / 0 差） | `reports/bench/lite_all.md` |
| 知识注入（规则、规则 + 策略） | 未测出收益：0 好 / 2 差、0 好 / 4 差，均不显著 | 同上 |
| 正式神经 checkpoint 上 Benchmark | ✗ 未做（云端只有 D28 的小模型 `bc_dgn_b0`，仅在 `home` 上跑通流程） | `reports/bench/home_refs.md` |
| 真人对局 | ✗ 未做（需约战；平台无天梯与匹配） | `docs/howto/platform.md` |

全部是模拟器内、小样本结果，不进强度验收，不代表真人竞技水平。用法：`docs/howto/benchmark.md`、`docs/howto/platform.md`。汇总、局限与后续建议：`reports/review/2026-11_d30_technical_summary.md`。

## 3e. DeepSeek-V4.1-Flash 与本地知识库评测（D31，2026-11-21）

| 项 | 状态 | 证据 |
|---|---|---|
| DeepSeek-V4.1-Flash 接入（`deepseek-flash`） | ✅ 非思考模式可用：1.5 万次决策调用全部成功，首答合法率 99.5%–100%，延迟中位 1.1 s；**思考模式不用于逐步对局**（约 1/3 回复为空） | `configs/models.toml`、`reports/review/2026-11_deepseek_kb.md` §1 |
| DeepSeek 非思考在 `lite` 上（无知识，两轮 112 局） | 0.737 [0.65, 0.81]；强于启发式、与脚本专家持平、弱于 GLM-5.3（低强度思考） | 同上 §4 |
| 知识库内容可用性（规则问答 56 题） | 闭卷 48；给原文或 BM25 检索 56（+8 / −0，p = 0.008） | `reports/bench/kbqa_ds.md` |
| 知识库检索 | ✅ `KnowledgeBase.search` 在空格切词无命中时回退到二元字 BM25（D32）：规则问答前 3 命中 0.893；决策时的规则选取见 §3f | 同上、`reports/review/2026-11_kb_training.md` §4 |
| 决策时的注入可达性（`rules-strategy`） | 规则 11/90 节、策略 14/70 单元；4 个策略单元几乎每个行动决策都被选中 | `reports/bench/kb_probe_lite.md` |
| 知识注入对表现的影响（`rules-strategy`） | 未测出（整局合并 +0.025 [−0.03, +0.08]；单步翻转在重测噪声内）；改进后的接入见 §3f | `reports/bench/ds_lite*.md`、`ds_scen*.md` |
| 运行间噪声 | 同配置重跑整局 7 / 0（p = 0.016）、单步 13% 选择变化：**配置比较至少两轮** | 同上 |

全部是模拟器内结果，不进强度验收。用法：`docs/howto/benchmark.md` §6。

## 3f. 知识接入的分阶段优化（D32，2026-11-21）

| 项 | 状态 | 证据 |
|---|---|---|
| D32 选定的知识接入 | `llm:deepseek-flash#kb=kbt-s4,reply=reason_first`（情境触发规则节 + 先写依据再作答）；当前接入见 §3g | `reports/review/2026-11_kb_training.md` |
| 情境规则题（test，260 题 × 2 轮，先写依据） | 0.923，对无知识 0.812：+0.112，39 / 2，p < 0.001；对原接入 0.840：+0.083，23 / 1 | `reports/bench/kbt_situ_test_reason.md` |
| 整局 `lite`（S5 两轮 112 局） | 0.821，对无知识（三轮）0.747：逐格 +0.074 [+0.007, +0.141]，11 / 4，p = 0.118——**正向但未显著**；新种子上未复现（§3g） | `reports/bench/kbt_lite.md` |
| 斩杀转化（test，70 题 × 2 轮） | S5 0.936，与无知识 0.943 持平；原接入 0.879，显著更差（0 / 7，p = 0.016） | `reports/bench/kbt_lethal_test.md` |
| 无收益的改动 | 规则 BM25 检索（S1）、训练集频次剪枝（S2）、斩杀窗口定向资料（S3）：train / dev 上都在噪声内 | `reports/bench/kbt_situ_dev.md` |
| 只改回复格式、不加知识 | 斩杀上无变化（0.898 对 0.922）；与触发规则合用才有效 | `reports/bench/kbt_lethal_dev.md` |
| 数据划分 | 场景集 v2 按种子 train / dev / test；test 与整局只跑过一次 | `docs/howto/benchmark.md` §7.1 |

全部是模拟器内结果，不进强度验收。用法：`docs/howto/benchmark.md` §7。

## 3g. 针对性优化与防过拟合检验（D33，2026-11-22）

| 项 | 状态 | 证据 |
|---|---|---|
| 当前知识接入 | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first`（D34 后仍是它，见 §3h）（D32 方案 + "对方未结束且我方可结束 → R01 §4.2" 触发）；按预先登记规则选出，dev 优势在噪声内 | `reports/review/2026-11_kb_d33.md` §2 |
| 整局 `lite_fresh`（新种子，每方 112 局） | 0.768 对无知识 0.746：逐格 +0.022 [−0.065, +0.110]，9 / 9——**无可测提升** | `reports/bench/kbt3_fresh.md` |
| 斩杀转化 v3（141 题 × 2 轮） | 无知识 0.947 / D32 方案 0.954 / 当前 0.943，两两差 ≤ 0.011 | `reports/bench/kbt3_v3_lethal.md` |
| 情境题 v3 原题型（先写依据） | 0.950 对 0.865：+0.085，60 / 9，p < 0.001 | `reports/bench/kbt3_v3_situ_reason_designed.md` |
| 情境题 v3 留出题型 | 规则被注入的"下回合先手"0.154 → 0.958；其余 4 种 −0.036（25 / 46，p = 0.017），未注入的无收益 | `reports/bench/kbt3_v3_situ_reason_heldout.md` |
| 跨模型（GLM-4.7-Flash，v3 test 子集，先写依据，1 轮） | 0.644 对无知识 0.426：+0.218（114 / 29）；其余 4 种留出题型 +0.106（26 / 9）；"下回合先手"规则被注入但未用上（−0.075） | `reports/bench/kbt3_v3_situ_glm_test.md` |
| 已知缺陷 | 知识库 R03 §2 写"技能后 +1 充能"未写上限：充能已满题 76/84 → 37/84 | `reports/review/2026-11_kb_d33.md` §3.1 |
| 保留数据 | v3、`lite_fresh` 已各用一次；再比较需新种子 | `docs/howto/benchmark.md` §7.6 |

全部是模拟器内结果，不进强度验收。

## 3h. 模型对战与知识库版本（D34，2026-11-22）

| 项 | 状态 | 证据 |
|---|---|---|
| 知识库版本 | 仍为 **v1.0**；v1.1 / v1.2（规则卡）未过守门，v1.0-s1（策略层第 1 轮）被门禁拒绝，均保留为未入库版本 | `reports/review/2026-11_kb_d34.md` |
| 模型对战 A/B（v1.0 对无知识，dev 80 对） | 0.547 [0.488, 0.605]，16 好 / 56 平 / 8 差——方向为正，未显著 | `reports/bench/d34_ab_v10_dev.md` |
| A/A 噪声 | 30 对 0.500；三分之二的对两局相同；80 对的 95% CI 半宽约 ±0.06 | `reports/bench/d34_aa.md` |
| 规则卡的引擎核对 | 先手 141/141、重击 144/144、信息划分 144/144、上限一致；充能对普通角色 66/66（例外为特殊资源角色） | `reports/bench/kb_engine_check_v11.md` |
| 保留数据 | `mirror_test` 的前 100 对已并入 `mirror_test150` 并在 D36 用掉；`mirror_dev` 前 80 对已用于主指标与 1 次门禁 | `docs/howto/benchmark.md` §7.7 |

全部是模拟器内结果，不进强度验收。

## 3i. 教师管线与分歧点评测（D35，2026-11-23）

| 项 | 状态 | 证据 |
|---|---|---|
| 推荐的模型接入 | `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1`（`elements=1` 在整局对战中显著优于原配置，见 §3j） | `reports/review/2026-11_kb_d35.md` §1.3 |
| 知识库版本 | 仍为 v1.0；v1.2 在新题库上先手题 −0.061，未入库 | 同上 |
| 教师材料 | 精确重放 + 两边对照的模式计数（`bench.mirror_mine`）+ 同一局面问各策略（`bench.divergence probe`，可定向） | `docs/howto/benchmark.md` §7.8 |
| 分歧点评测 | 可行，但续打噪声淹没单个决定的作用；不作门禁初筛 | `reports/bench/d35_dp.md` |
| 规则层守门题库 | `situ_v2d33`（dev 487 题，含充能、先手、调和、手牌与骰子上限） | `configs/bench/kb_situ/situ_v2d33.json` |

全部是模拟器内结果，不进强度验收。

## 3j. 多轮进化与镜像对战（D36，2026-11-23）

| 项 | 状态 | 证据 |
|---|---|---|
| 知识库版本 | 仍为 **v1.0**；v1.0-s2（攻击优先）、v1.0-s3（起手换牌）机制核对通过但 dev 被拒，保留为未入库版本 | `reports/review/2026-11_kb_d36.md` |
| 镜像对战（v1.0 对无知识，新观测层，`mirror_test150` 150 对） | 0.535 [0.482, 0.588]，43 好 / 74 平 / 33 差，单侧 p = 0.151——方向为正，未显著，未达 0.70 | `reports/bench/d36_test_main_pairs.md` |
| 观测层 `elements=1` | 对旧观测层（都无知识，80 对）0.584 [0.522, 0.647]，单侧 p = 0.010，显著；推荐用法 | `reports/bench/d36_test_obs_pairs.md` |
| 守门 | 锚点 0.438（32 局，对 D34 0.531 不显著）；斩杀 0.938 | `reports/bench/d36_anchor.md` |
| 保留数据 | `mirror_test150` 已用（主测 150 对 + 观测层对照前 80 对）；`mirror_dev` 前 40 对用于两次第一阶段门禁 | `docs/howto/benchmark.md` §7.9 |

全部是模拟器内结果，不进强度验收。

## 3k. 评测指标、派生事实与跨模型（D37，2026-11-23）

| 项 | 状态 | 证据 |
|---|---|---|
| 镜像对战主指标 | **H（生命差，对分 = 两局之和）**，W 同时报告；脚本校准 A/A 拒绝率 0.022，n80 17.5 对（W 32.6）；真实模型对局上平局 56% → 0% | `reports/bench/d37_metric_validation.md` |
| 胜利优先的胜率区间 | `bench.metrics tiebreak`：先看胜负，平局按 K→H→D 判定。已有数据上 KB 对无 KB：train 重放 50 对 0.540 [0.401, 0.679]，对 GLM 10 对 0.600，都不显著 | `reports/bench/d37_tiebreak.md` |
| 推荐的模型接入 | 仍为 `llm:deepseek-flash#kb=kbt3-trig,reply=reason_first,elements=1`；`facts=1`、`cards=1` 可选，未测出提升 | `reports/review/2026-11_kb_d37.md` |
| 派生事实 `facts=1` | 预演每项都发生 0.997（train 2,101 次）；引擎泄漏测试通过；dev 上 `v11` 对 `base` H 0.475（40 对，不显著），`facts=1` 单独 H 0.425（20 对） | `reports/bench/d37_dev_metrics.md` |
| 跨模型（对 GLM-5.3-Flash，各 10 对） | `base` W 0.50 / H 0.60；`v11` W 0.45 / H 0.20（描述性） | `reports/bench/d37_cross_metrics.md` |
| 保留数据 | `mirror_dev200` 第 100–149 对已用；第 150–199 对未用；`mirror_train300` 第 60–179 对用于脚本校准 | `docs/howto/benchmark.md` §7.10 |

全部是模拟器内结果，不进强度验收。

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
