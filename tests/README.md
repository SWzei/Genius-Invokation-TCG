# tests — 关键测试（全部进 CI）

信息泄漏测试（两份只差对手隐藏信息的 state，编码必须一致）、action_adapter 往返、同种子重放一致性、非法动作回退。

> 当前测试数量以 `python -m pytest --collect-only -q` 为准（本文件不写死数字）。
> 当前状态/门禁见 [`docs/STATUS.md`](../docs/STATUS.md)；评测口径见 [`docs/EVAL_PROTOCOL.md`](../docs/EVAL_PROTOCOL.md)。

## 运行

`python -m pytest`（从仓库根跑）；`python -m pytest -m "not slow"` 跳过慢测。

## P0（2026-10-27）新增

- `test_feature_parity.py`：compact exact definition id、`repair_observation_payload`、`compare_observations`（definition 列按 int 比）、store builder 记录 `definition_ids_present`、`include_training_targets` 不改变策略输入。
- `test_eval_seed.py`：`--seed-start` 只加一次；`match_seed` 落盘。
- `test_neural_policy_seed.py`：`#t>0` 采样同 seed 可复现。
- `test_belief_dice.py`：hidden dice 是 i.i.d. 采样，不再是确定性轮转。
- `test_cfr_probe_value.py`：identity 价值头→概率；acting-player→player-0。

## 2026-11 审查新增

- `test_matchup_weights.py`（追加）：用真实布局（每局一个 seed）的 store 键回归 H5 分组 bug——历史实现按
  `key[:-1] = (deck, opponent, seed)` 分组，等于按**局**加权（deficit = 给输局加权）。
- `test_encoder_profiles.py`：v1 特征/采集指纹逐字节不变；v1s/v2 在 0 号位与 v1 相同、1 号位映射到同一布局；
  v2 只暴露对手骰子**数量**不暴露骰面；`neural:...#seatrel=1`；`collect_samples(teacher_side=1)`；
  `neural:` teacher 与采集特征档不一致时拒绝；`seat_probe` 的 v2→v1/v1s 转换与直接编码逐元素一致。
- `test_seat_coverage.py`：评测按座位分报（含配对 Δ）；双座位语料同 seed 不被去重、同 seed 两座位同属 train/val；
  store 记录语料的编码档并拒绝混档。

## 2026-11 平台接入与 Benchmark 新增（D30）

- `test_bench.py`（快，无对局）：套件是保留种子上的配对网格（每格两座位、种子不含 0、与场景集种子不相交）；
  入库套件只凭 lock 文件加载（不需要赛事数据），设了 `GITCG_DATA_RELEASE` 时再核对 lock 与套件文件展开结果一致；
  报告只在共同格子上配对、剔除降级 / 无效局并计数；套件指纹变了拒绝续跑；读局面题按精确匹配计分、
  隐藏信息题只接受“无法得知”；场景汇总把质量（斩杀）、相似度（专家一致）与生成者分开；
  `bench.compare` 跨 tag 配对并拒绝不同指纹；报告里的原始数据路径写成相对仓库根目录。
- `test_bench.py`（slow）：每类受试者各打一格（脚本 / 启发式 / 离线模型）与降级标记；真人牌表在其原生规则版本下对局；
  运行器的并行、续跑、追加受试者、调用上限即停；**入库场景集在当前引擎上逐个重放，斩杀答案重新由引擎核实**。
- `test_platform_room.py`（快）：`select_option` 请求的手工解码与默认作答；本机地址判定与 `[BOT]` 前缀；
  建房 / 入房 / 作答 / 取日志的请求形状；事件流读取对心跳、注释行、坏数据的容忍；等待对手有上限。
- `test_platform_room.py`（slow）：经仿真房间（按上游协议实现，真实引擎出题）打一整局并与进程内对局逐步一致
  （含注入一次 `select_option`、一次断线重连）；设了 `GITCG_PLATFORM_TEST_SERVER` 时对**真实上游服务端**自对弈一局。
- `test_llm_providers.py` 新增 2 项：按真实报文形状回放余额不足（HTTP 429 + 服务商错误码）与模型不存在——
  不重试、客户端停用、后续请求不发出；缓存命中与思考 token 进结果、汇总与计价。

## 2026-11 知识库评测新增（D31）

- `test_kb_bench.py`（快，9 项，离线）：问答题库校验（逐字证据、选项、编号、章节存在）；二元字 BM25 能为中文问句找到章节，
  而知识库自带检索（按空格切词）对同样的问句返回空；四种条件的取材与提示词内容；答案解析；与闭卷配对的
  McNemar 汇总；离线模型端到端评测与续跑；策略单元完整呈现读取知识库原文、非法取值报错、旧配置的清单输出不变；
  注入体检的汇总口径。设了 `GITCG_KB_DIR` 时另校验入库题库对真实知识库有效（56 题）。

## 2026-11 实验平台新增（D29）

- `test_llm_providers.py`（快，无引擎）：三种协议各自对本地仿真服务核对请求形状（鉴权头、参数名、system 位置、
  JSON 开关）与响应解析（跳过 thinking / thought 片段、token 计数）；预设覆盖 OpenAI / Anthropic / Gemini /
  DeepSeek / GLM；配置分层与“配置里不得有密钥”；429 / 529 重试与 `Retry-After`；错误分类（鉴权、5xx、非 JSON、
  空内容、超时、连不上、无密钥）且不回显密钥；`max_tokens` / `temperature` 被拒时自适应一次；预算（次数 / token /
  成本）在发请求前拦截；调用日志不含密钥与提示词；离线 `mock` 的各行为与可复现性。
- `test_llm_platform.py`（快，含 1 局本地对局）：局面文本对行动方完整、对手隐藏区只给数量、不读 `full_state`、
  真实对手手牌不泄漏；五类决策的选项都有文本与公开文本；旧 `ContextDescriber` 的 "declare end" 误标回归；
  位置型回复（重掷 / 换牌）映射到合法选项；知识档案按来源选取、事实与观点分块且事实优先、证据过滤、版本告警、
  自定义资料未声明 `kind` 拒收、专家示例、知识库缺失只告警；LLM 策略的合法性 / 追问一次 / 接口失败不重复调用 /
  每局预算 / 回退策略出错仍合法 / 留痕字段；知识进入提示词与决策留痕；讨论与决策同视图；spec 解析；
  四种离线模型各打一整局（引擎零回退）。
- `test_lab.py`（快，约 100 s，含 3 局）：对局规格校验（种子 0、干预需明牌）；事件按座位投影；worker 协议整局
  （示范、非法指令拒收、建议、讨论、托管、模型留痕与调用账目）；人类视角拿不到模型座位的私有数据；回放逐决策
  重建、记录被改动时拒绝；示范 → `train.collect` 语料 → 建 store → 原训练器 1 轮；明牌局与无结果对局不导出；
  反馈 → 监督记录（`HumanSignal`）→ `--distill-target human` 训练；旧记录序列化不变；策略对比；HTTP API
  （目录、校验、跨站表单拦截、干预批准 / 改选、回放视角、反馈的信息干净标记与越权拒绝、对比、导出）。
- `test_lab.py`（slow）：人工改选的反事实校验（信息合法、候选恰为“执行动作 + 被否决提议”）；浏览器端到端
  `tests/e2e/lab_browser.py`（人机整局、建议、讨论、评价、托管、回放纠正、策略对比、导出、AI 对 AI 改选；
  需要带 Playwright 的解释器，可用 `GITCG_PLAYWRIGHT_PYTHON` 指定，找不到则跳过）。

## 2026-11 MASD-ADM 兼容层新增（D28）

- `test_masd_adm.py`（快测）：监督记录 schema——精确符号检验、按 rollout 配对、门控三态
  （`alternative_supported` / `expert_supported` / `inconclusive`）、用了真实隐藏状态的证据永不 verified、
  JSONL 往返与 schema 版本校验、决策键与 `_game_key` 同布局；知识库与赛事牌组适配（夹具文件；设了
  `GITCG_KB_DIR` / `GITCG_DATA_RELEASE` 时再对真实数据核对检测器与规则引用）；target 三种模式互不混用、
  按键对齐并拒绝选项数/专家下标不符的记录；one-hot KL ≡ CE；padding 与部分覆盖下损失与梯度有限；
  **蒸馏关闭时训练权重逐位相同、固定种子可复现**；`datafirst_bc_train --supervision` 端到端；
  门控只分配预算（label-only 永远打基座动作）；文本学生只读记录里的公开文本；`ForkTask.inject_key` 往返；
  `hands` 内联的边界快照也能生成信念根（回归：历史实现在这类快照上抛异常，被 `PolicyPlayer` 吞掉后改打回退动作）；
  信念根保留行动方自己手牌上的附着与变量、对手手牌上的不保留（回归：历史实现一律清空）；
  证据 CLI 断点续跑、丢弃未完成对局的残留记录、规格漂移时拒绝续跑；PG 损失与蒸馏项可叠加；两种网络结构的学生加载。
- `test_masd_adm.py`（slow，信息安全）：label-only 证据对局与 `collect_samples` 同局逐决策一致
  （step / 选项数 / 专家下标 / 结果）；每个 fork 任务前缀为空、带注入 key、根快照里对手手牌为合成 id；
  同一决策的候选共用根粒子与 rollout 种子；知识标注、状态文本、选项文本在去掉 `full_state` 后不变；
  注入 key 不符、或合法动作列表与现场不符的 fork 报错而不计分；同一证据规格换 worker 数重跑得分逐项相同。

## 主要测试（历史清单，持续更新）

- `test_info_hiding.py`：`public_state.mask_state_for_player` 隐藏对手手牌/骰子/牌堆、保留己方与公开信息、幂等。
- `test_info_leak.py`（slow，**WS1 硬门禁**）：只改对手隐藏信息的两份 context，编码器**输入**（token/option/mask/opponent id）
  必须逐字段一致；改公开信息（对手角色血量）必须可见；belief target 必须随 `full_state` 变化（标签由上帝视角算）。
- `test_action_adapter.py`：每个合法具体动作都有 code + kind-appropriate 载荷；动作空间上限护栏；抽象动作 100% 覆盖合法具体动作（往返语义 key 可恢复）；无非法回退。
- `test_replay_consistency.py`（slow）：同种子两次对局结果一致。
- `test_arena.py`（slow）：arena 顺序与多进程结果一致（验证 codebook reset + 预洗牌确定性）。
- `test_env_smoke.py`：脚本对手对局跑通、无 IO 错误 / 无回退。
- `test_stats.py` / `test_ladder.py`：Wilson CI、Elo。
- `test_llm.py`：LLM 客户端 JSON 解析/脱敏、LLM 辅助策略「非法响应回退 + 预算 + prompt 不泄密」、教练结构化输出（mock 客户端，无网络）。
- `test_decklab.py`：换卡保持 30 张、候选池排除、换卡评测小样本（slow）。
- `test_engine_bridge.py`：L5.4/D12——快照往返无损、续跑克隆确定、`InjectionPolicy` 位置/夹取逻辑（快测）；
  replay-branch 注入 base 选择时逐局复现 base、同注入两次一致、`evaluate_decision` 候选覆盖（slow）。
- `test_llm_matrix.py`（L5.2）：LLM 矩阵任务网格确定性、纯策略/LLM 行结构、干预与用量记录（mock 客户端，无网络）、
  客户端失败标 `degraded` + 连续失败中止、聚合报分/delta/`llm_quality`、流式续跑跳过已完成 + spec 指纹护栏 + 撕裂行容错。
- `test_learning_curve.py`（L5.3）：曲线数据量过滤/去重/排序、固定验证留出集（各点同 holdout）、微型端到端扫描、`--eval-opponents` 缺 `--eval-seeds` 报错。
- `test_fork_bridge.py`（L5.4）：fork 桥单元（位置重放 / 注入 / 前缀-rollout 策略、`ForkTask` JSON 往返、候选选取、搜索策略选优/平局取基座/预算开关）；慢测——纯重放 fork 进程内与**子进程桥**均逐字节复现活体终局、`run_search_match` 冒烟、在线搜索拒绝 `workers==0`。
- `test_belief_root.py`（M3-CPU S-A）：公共信念根化——`reps.belief` 补丁只改写隐藏区（合成隐藏 id、内联骰子）、
  belief 范围只依公共视图、确定化根对隐藏真值不变（可 fork 打完整局 + belief-root 搜索冒烟，slow）。
- `test_cfr_solver.py`（M3-CPU S-B）：外采 MCCFR 脚手架——regret matching/先验回退与不删动作、分布归一、
  bandit 收敛最优臂、深度截断走 frontier 且同输入确定复现、玩具 2×2 矩阵博弈收敛到已知混合 Nash（值 6/5）、
  `belief_root_particles`/`public_infoset_key` 对隐藏真值不变（engine-free）。
- `test_belief_head.py`（M3-CPU S-C，G7）：belief 头形状（`belief_groups` 边缘 + 对手手牌卡后验 + 标量）、
  proper-scoring belief 损失在优化下降、全退化标签批次损失为 0、CVPN/Transformer 的 `forward_all` 形状与
  `forward` 二元组兼容、belief 头 checkpoint 往返、旧 config（无 belief 字段）后向兼容（engine-free）。
- `test_distill.py`（M3-CPU S-C，G6）：teacher 根策略按语义 key 重索引/归一/不删动作、样本 JSON 往返
  （含 `policy_target`/`action_values`/`search_value`/`search_meta`）与旧格式缺字段容错、蒸馏损失数值 sanity
  （soft 单热 == hard CE、value 目标 soft/hard 选择、总损失 == 系数加权分量和）、蒸馏训练损失/一致率/belief 损失下降、
  冷启动 BC 退化、无 belief 头时 belief 损失为 0；慢测——`train.pipeline.run_distill_round` 端到端（真引擎评测）。
- `test_collect.py`（L5.6 + S-C）：集群数据平面——观测/样本 JSON 往返无损、`CollectSpec` 任务网格与指纹稳定、
  撕裂行容错、replay 目录展平；S-C 搜索 teacher 的 `SearchSpec` 往返 + 进 spec 指纹；慢测——并行采集 + 续跑不重复、
  `load_samples` 计数一致、`collect_search_samples` 产出带 solver 目标（根策略归一、根价值、belief 标签）的样本。
- `test_deck_corpus.py`（探索任务 1）：公开卡组语料——每条分享码经引擎编解码解出 3 角色 + 30 牌、
  `DeckSpec` 唯一且形状正确、loader 元数据/查找、分享码与存储 id 一致（需资产缓存，否则 skip）；
  语料 JSON 缺失（gitignore）时整个文件 skip，无网络。
- `test_npc_spec.py`（PvE-B3）：16 关 `NpcSpec` 加载/校验、中文名→引擎角色 id 映射经 `appears_in` 交叉校验、
  A/E/Q 技能 definition id + 伤害表与 `.gts` 源逐一对照、关卡阵容按 count 展开、未知目标类型报错。
- `test_npc_policy.py`（PvE-B2）：`NpcPolicy` greedy 取最大伤害 / 平局固定顺序 / 绝不打出行动牌 / 绝不主动切人 /
  reroll 保持骰子 / choose_active 取首槽 / rotation 优先其循环并在缺项时回退；slow——真实对局同种子（含 rotation）逐决策复现。
- `test_npc_objectives.py`（PvE-B3）：7 类挑战目标合成轨迹判定（win / 回合数 / 被击倒数（终局快照）/
  元素爆发 / 元素反应 / 装备牌 / 事件牌）+ 三星计数。
- `test_npc_eval.py`（PvE-B3）：聚合（总览/逐关/逐目标）、spec 指纹稳定与敏感、流式续跑指纹护栏 + 撕裂行容错、
  任务网格；slow——`run_npc_eval` 端到端 + 重复运行续跑不重复 + 产物落盘。
- `test_npc_contestant.py`（PvE-v1，B5）：门禁 contestant 策略——合成 profile 无 deck 专属规则、
  目标注入（装备/事件牌）与不可用时的回退、`inject_objectives=False` 不注入；slow——同种子逐决策复现。
- `test_decklab_builder.py`（PvE-v1，B5，D19）：规则组牌——池 C 牌组合法（30 张 / ≤2 张 / 全在池内 /
  角色在池内）、确定性、武器+圣遗物齐备（目标可达）、越界报错、kind 统计。

依赖：需要资产缓存（`data/assets/`）；首次运行会联网拉取，CI 可预置缓存并设 `GITCG_ASSETS_OFFLINE=1`。
