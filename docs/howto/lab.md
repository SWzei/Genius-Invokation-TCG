# howto — 实验台：模型接入、知识配置、人机实验闭环

> 决策：`PLAN.md §0` D29。实测结果与限制：`reports/review/2026-11_lab_platform.md`。
> 定位：实验与数据工具。**强度验收仍是纯策略**（`AGENTS.md`），LLM 玩家与人工数据都不进认证口径。
> 与 `web-debug.md` 的关系：那套界面的引擎跑在浏览器里（图形化、依赖上游前端构建）；实验台的引擎跑在
> Python 里（文字界面、零构建、全程落盘）。两者共用 `envs.policy.build_policy`，所以 `llm:` spec 在两边都能用。

## 1. 结构

```
configs/models.toml ──► common/llm_providers.py ──┐   三种协议 + 重试 + 预算 + 调用日志
configs/knowledge.toml ► reps/knowledge_pack.py ──┤   规则 / 策略 / 专家示例 / 自定义，分块标注
                         reps/describe.py ────────┤   行动方可见局面与合法动作 → 文本 / 结构
                                                  ▼
                         agents/llm_policy.py      LLM 完整对局策略（spec: llm:<档案>#kb=…）
                                                  ▼
lab/runner.py ─ lab/worker.py（每局一个进程）─ lab/server.py + static/index.html（Web）
        │ events.jsonl / feedback.jsonl / chat.jsonl / calls.jsonl
        ▼
lab/replay.py ─► lab/export.py ─► BC 语料（train.collect 格式）· 监督记录（DecisionSupervision）
lab/verify.py ─► 人工纠正的反事实校验（复用 envs.fork_search / reps.strategy）
```

复用的现有模块：引擎循环（`PolicyPlayer`）、`build_policy`、`reps.knowledge`、`reps.strategy`、
`train.strategy_targets`、`scripts.datafirst_bc_*`、`envs.fork_search`。没有改动训练器的默认行为。

## 2. 模型接入

`configs/models.toml` 定义"模型档案"；个人改动写 `configs/models.local.toml`（不入库）或
`$GITCG_MODELS_CONFIG`，同名覆盖。

| provider | 协议 | 默认地址 | 密钥环境变量 |
|---|---|---|---|
| `openai` | chat completions | api.openai.com/v1 | `OPENAI_API_KEY` |
| `anthropic` / `claude` | Messages | api.anthropic.com/v1 | `ANTHROPIC_API_KEY` |
| `gemini` | chat completions（官方兼容端点） | generativelanguage.googleapis.com/v1beta/openai | `GEMINI_API_KEY` / `GOOGLE_API_KEY` |
| `gemini-native` | generateContent | generativelanguage.googleapis.com/v1beta | 同上 |
| `deepseek` | chat completions | api.deepseek.com | `DEEPSEEK_API_KEY` |
| `glm` / `zhipu` | chat completions | open.bigmodel.cn/api/paas/v4 | `ZAI_API_KEY` / `ZHIPUAI_API_KEY` |
| `openai-compatible` | chat completions | 自填 `base_url`（vLLM / Ollama / 网关） | 自填或不需要 |
| `mock` | 无网络 | — | — |

- **密钥**：档案里只写环境变量名；值来自进程环境或仓库根 `.env`。配置文件里出现 `api_key` 会被拒绝加载。
  日志、报告、接口返回都不含密钥。
- **推理参数**：`temperature`（`"none"` = 不发送）、`max_tokens`、`max_tokens_param`、`top_p`、`timeout`、
  `json_mode`、`extra_body`（原样并入请求体）。两类参数被拒时客户端会自动改一次并记在结果里：
  `max_tokens` → `max_completion_tokens`；模型不接受 `temperature` 时去掉它。GLM 的温度钳到 ≥ 0.01。
- **可靠性**：429 / 5xx / 529 / 超时按指数退避重试（`retries`，尊重 `Retry-After`）；401/403 不重试。
  每次失败都有类别：`auth` `rate_limit` `timeout` `network` `http_<码>` `bad_response` `empty_content`
  `blocked` `budget` `no_key`。
- **预算与成本**：`[profiles.<名>.budget]` 的 `max_calls` / `max_tokens` / `max_cost` 是硬上限，超过后不再发请求。
  成本只在你填了 `price_in` / `price_out`（每百万 token）时统计，否则记为未知。
- **模型 id**：OpenAI / Gemini 档案是注释模板，填上 `model` 即可。**GLM 档案已用真实接口核对**（2026-11，D30）：
  `glm-flash`（免费档，关思考）、`glm-53` / `glm-53-flash`（通用端点，需余额）、`glm-53-plan` / `glm-53-flash-plan`（Coding Plan 端点）。
  GLM-5.3 系列不能关闭思考，用 `extra_body = { reasoning_effort = "low" }`；思考 token 占用 `max_tokens`，留 2,048 以上。
- **错误分类**：鉴权失败、余额不足（含智谱的 HTTP 429 + 1113）、模型不存在属于致命错误——不重试，且该客户端之后的请求不再发出，
  这样一局对局不会在无人察觉时由回退策略打完。限流与 5xx 才重试。

```bash
python -m scripts.llm_smoke --list          # 看档案与密钥是否就绪（不发请求）
python -m scripts.llm_smoke deepseek-chat   # 真实调用一次：延迟、token、JSON 开关是否可用
```

### 策略 spec

```
llm:<模型档案>[#kb=<知识档案>,fallback=<策略spec>,budget=<每局调用上限>,model=<id>,detail=0|1]
llm-assist:<模型档案>#base=<策略spec>[,budget=N]      # 旧的“关键点重排”模式，换成新客户端
```

任何接受策略 spec 的入口都可用（`run_match`、`scripts.llm_arena`、`web/ai_rpc_server.py --policy`、实验台）。
本地策略照旧：`expert:<deck>`、`heuristic`、`legal_random`、`neural:<ckpt>#t=0`。

LLM 玩家的三条保证（与模型无关，均有测试）：

1. **合法**：回复被映射到引擎给出的合法选项并校验；解析失败、越界、接口失败、预算用尽都落到回退策略
   （默认 `heuristic`），对局不会卡住也不会出现非法动作。回复不可用时带原因追问一次。
2. **信息边界**：提示词只由行动方的 `player_view` 与合法选项生成；对方手牌、骰子与双方牌库只给数量。
3. **可追溯**：每个决策一条 `DecisionTrace`——来源（模型 / 回退 / 唯一选项）、理由、原始回复、延迟、
   token、成本、错误类别、注入的知识条目 id 与知识库版本、提示词哈希。

回复协议：行动 / 选人 / 挑牌回 `{"choice": n}`；重掷回 `{"reroll": [骰子位置]}`；换牌回 `{"swap": [手牌位置]}`。

## 3. 知识配置

`configs/knowledge.toml` 定义"知识档案"（内置 `none`）；知识库位置取 `$GITCG_KB_DIR` 或档案里的 `kb_root`。

| 来源 | 性质 | 提示词里的标题 | 选取方式 |
|---|---|---|---|
| `rules` | 事实 | 【规则事实】 | 按当前合法动作类别取规则条目；默认只收证据含「官方」或「引擎」的条目，含「待核」的会标注 |
| `strategy` | **观点** | 【策略观点（未经验证）】 | 适用条件检测器命中的策略单元（14/70 个有检测器）；可按知识库置信度、文档过滤 |
| `expert_examples` | 行为 | 【专家对局示例】 | 监督记录里同类决策的脚本专家选择；写明"不保证最优" |
| `custom` | 你声明的 | 【自定义资料·规则 / 策略】 | Markdown / TXT，按与当前局面的字面重合度取片段 |

- 自定义文件头必须写 `kind: rule` 或 `kind: strategy`（建议加 `version:`），**没有声明的文件拒收**并给出告警。
- 四类分块输出、事实在前；总长度受 `max_chars` 限制，超限时先丢观点。
- 版本：每条知识带知识库版本与其 `version_baseline`；规则条目的基线版本与本地卡牌数据版本不一致时记入
  `warnings`（随决策日志保存，界面可见）。
- 选取只读行动方视图。知识库缺失时不报错，改为告警并且不注入内容。

对比不同模型 / 知识配置（同一批对局、配对比较）：

```bash
python -m scripts.llm_arena --deck natlan_battleship \
    --contestants "llm:deepseek-chat" "llm:deepseek-chat#kb=rules-strategy" heuristic \
    --opponents superconduct_aggro unyielding_geo --seeds 2 --max-calls 600 --tag kb_ab
```

报告含胜率（Wilson 区间）、模型作答率、错误类别、每次调用耗时、token、成本，以及其余参赛者对第一个的配对差。
结果逐局追加、同命令续跑；`--max-calls` / `--max-cost` 到顶即停。这是筛选工具，不是强度结论。

## 4. Web 实验台

```bash
export GITCG_KB_DIR=<…>/GITCG_KB          # 可选
python -m lab.server --port 8780          # 浏览器打开 http://127.0.0.1:8780/
```

| 页面 | 能做什么 |
|---|---|
| 新对局 | 每个座位选牌组与操作者：人类 / 本地策略 / 大模型（模型档案 + 知识档案 + 回退 + 每局调用上限）；种子（≥1，默认取未用过的）；人工干预；明牌 |
| 对局 | 当前视角的完整局面；点选项行动，重掷 / 换牌点选骰子或手牌后确认；"看它会怎么走"（任一策略在**你的**视角下的建议）；托管到终局；中止 |
| 对局 · 决策 | 每步由谁执行、策略自述（LLM：理由 / 来源 / 延迟 / token / 成本 / 注入的知识 / 原始回复；网络：价值与前 5 项概率）；认可 / 不认可 / 更好的选项 / 评语 |
| 对局 · 讨论 | 就当前待决策的局面向任一模型提问（可带知识档案）；问答随对局保存 |
| 人工干预 | AI 每步先出提议：批准、改选（记为人工纠正）、或之后全部自动批准 |
| 回放与导出 | 已存对局列表；逐步回放、单座位或全知视角；补评价与纠正；策略对比（重放并询问其他策略在每个决策点的选择）；导出 BC 语料 / 监督记录 |

可见性规则（服务端强制，`lab.session.project_event`）：

- 人机对战中，人只能看到自己座位的私有信息；AI 的决策只显示公开动作（不含其手牌、选项、理由）。
- "明牌"或 AI 对 AI 时可见全部；**明牌局标记为非信息干净，默认不导出为示范**。
- 对局中不能纠正对方 AI 的选择（看不到它的选项），只能评价；纠正在赛后回放里做。
- 回放时以该决策所属座位的单座位视角给出的评价记为"信息干净"，全知视角给出的记为非干净。

每局一个 worker 进程（动作码本是进程级的，引擎不可重入）。服务默认只绑 127.0.0.1：页面提交的策略 spec 会在本机执行。

## 5. 数据与训练对接

每局保存在 `data/lab/<id>/`：`session.json`（规格、引擎锁、状态、结果）、`events.jsonl`（全部事件，含双方私有视图）、
`feedback.jsonl`、`chat.jsonl`、`calls.jsonl`（模型调用账目，不含提示词与密钥）。对局只存"每步选了第几个选项"，
导出时用同一种子重跑引擎重建决策上下文，并逐步核对选项数与引擎标签，对不上就拒绝导出。

```bash
# 人类示范 → train.collect 格式语料 → 原训练器（BC / AWR / PG 均可）
python -m lab.export bc --tag human_v1 --sessions all
python -m scripts.datafirst_bc_store --replays data/replays/human_v1 --store-cache data/store/human_v1.pt --seed-start 1
python -m scripts.datafirst_bc_train --store-cache data/store/human_v1.pt --out data/checkpoints/human_bc.pt

# 示范 / 改选 / 纠正 / 评价 → DecisionSupervision（带 HumanSignal）
python -m lab.export supervision --name human_v1 --sessions all
python -m scripts.datafirst_bc_train … --supervision data/lab_exports/human_v1/supervision.jsonl \
    --distill-coef 1.0 --distill-target human

# 人工纠正的反事实校验（VCSD 用在人工反馈上；每个决策 2×rollouts 局续行对局）
python -m lab.export verify <session id> --rollouts 12
```

- `bc --seats human`（默认）导出人类自己的决策；`corrected` 导出被人工改选过的 AI 座位的整条轨迹；`all` 全部。
  托管步与明牌局默认不导出；没有胜负结果的对局不导出（没有价值目标）。
- `HumanSignal` 四类：`demonstration`（人打的）、`override`（执行前改选）、`correction`（事后指出更好的选项）、
  `rating`。前者证据类别是 `human_demonstration`，后三者是 `human_preference`。
- `--distill-target human` 只把 `override` / `correction` 变成 target（one-hot 到人偏好的选项），它是**未经验证的观点**，
  与 `evidence_gated` 分开；非信息干净的信号被跳过。
- `verify` 输出同时带 `human` 与 `evidence` 的记录，`reps.strategy.verdict` 给出 rollout 是否支持人的偏好；
  限制与 `train/evidence.py` 相同（仅行动决策、空前缀、假设对手牌表公开、牌组须在脚本池内）。

## 6. 已知限制

- 真实模型接口只有智谱 GLM 实测过（`reports/review/2026-11_glm_validation.md`）；其余各家的协议实现对照文档、用本地仿真服务验证。
  接入新模型先跑 `scripts.llm_smoke`。
- 知识注入对模型强度的影响：GLM-5.3 上小样本实测**未测出收益**（`reports/review/2026-11_benchmark.md §2.2`）；横向评测用 `bench/`（`docs/howto/benchmark.md`），`scripts.llm_arena` 仍可做单牌组的快速比较。
- 牌组只支持 `envs.decks` 里的 20 个脚本池牌组；赛事牌组（`envs.tournament_decks`）尚未接入界面。
- 界面是文字局面，没有卡图与动画；需要图形界面时用 `web-debug.md` 的 standalone。
- 策略知识的自定义检索是字面重合度，没有向量检索；56/70 个策略单元没有条件检测器，不会被选中。
- 一个决策点的选项超过 `max_options`（默认 40）时只列前 40 个（重掷 / 换牌走位置协议，不受此限）。
- 讨论与"看它会怎么走"只在有决策等待输入时可用；人对人热座模式未做界面。
- 不要用种子 0（引擎随机数退化）；实验台拒绝种子 0。
