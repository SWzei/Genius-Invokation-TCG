---
title: "2026-11 Technical Summary（D30）：实际修改、验证结果、局限与后续建议"
kind: report
status: valid
freshness: 2026-11-15
machines: [cloud-2c]
authority: evidence
related: ["PLAN.md#D30", "reports/review/2026-11_platform_review.md", "reports/review/2026-11_benchmark.md",
          "reports/review/2026-11_glm_validation.md", "docs/howto/benchmark.md", "docs/howto/platform.md"]
---

# 2026-11 Technical Summary（D30）

> 基线：D29 之后的代码（`gitcg 0.21.0`，`engine.lock` 锁定上游 `6f01d5c`）。环境：云端 2 核 / 8 GB，Python 3.12。
> 日期 2026-11-14 / 15。本文件只做汇总与交叉索引，细节与数字的出处在三份分报告里。

## 0. 交付物

| 交付物 | 文件 | 一句话 |
|---|---|---|
| 1. Platform Review | `reports/review/2026-11_platform_review.md` | 能程序化接入、有完整记录、可复现的只有 genius-invokation 及其对战平台；已接入并在本机上游服务端实测 |
| 2. Benchmark | `reports/review/2026-11_benchmark.md`（设计与用法 `docs/howto/benchmark.md`） | 对局套件 + 引擎核实答案的决策场景集；脚本、启发式、神经、GLM 四类受试者已跑 |
| 3. GLM Validation | `reports/review/2026-11_glm_validation.md` | 对智谱真实接口 5,000+ 次调用；整局、合法性、知识、异常、成本逐项验证 |
| 4. Technical Summary | 本文件 | |

## 1. 结论

1. **平台**：真人高水平对局没有可程序化接入的来源。官方客户端无接口；BetterGI 只打 NPC、靠截图操作、有封号风险；
   其余开源模拟器停更一年半以上、规则停在 4.x–5.0。genius-invokation 对战平台是唯一可行的真人通道，但没有天梯与匹配，只能约战。
2. **评测体系可用**：对局套件逐局配对、保留种子、lock 文件可复现；场景集的斩杀答案由引擎逐选项实打核实。
3. **GLM-5.3 在模拟器里明显强于启发式基线**（`lite` 28 局 0.929，配对 13 好 / 0 差，p < 0.001），对脚本专家 6 / 8；
   **知识注入没有测出收益**（0 好 / 2–4 差，不显著；每局 token 多 63%–86%）。
4. **真实接口暴露了 5 个仿真测不到的问题**，最严重的是"余额不足被当限流重试、回退策略悄悄替模型打完整局"，均已修复并加测试。
5. 以上全部是**模拟器内、小样本**结果：不是强度认证，不代表真人竞技水平；LLM 玩家不进强度验收（D1 不变）。

## 2. 实际修改

相对 D29 提交，50 个文件（含本文件），其中 Python 16 个（+3,278 / −17 行）；其余为配置、入库的套件 lock 与场景集、评测汇总和文档。

### 2.1 新增

| 文件 | 行数 | 作用 |
|---|---|---|
| `envs/platform_room.py` | 433 | 对战平台房间客户端（标准库）：建房 / 入房 / SSE 事件流 / 作答 / 认输 / 取日志；`play_seat` 让任何策略 spec 上桌；`select_option` 手工解码；断线重连与 rpc 去重 |
| `scripts/platform_play.py` | 217 | 命令行 `info` / `host` / `join` / `selfplay`；非本机服务器加 `[BOT] ` 前缀、默认私有房间 |
| `bench/suite.py` | 267 | 套件 = 组 × 牌组 × 对手 × 种子 × 座位；保留种子区段；赛事牌表 `test` 划分；lock 与指纹 |
| `bench/run.py` `play.py` | 257 | 每局一个子进程、并行、续跑、全局调用 / 费用上限、致命错误即停、降级局标记 |
| `bench/report.py` `compare.py` | 295 | Wilson 区间、共同格子配对差、精确符号检验、模型侧指标；跨 tag 比较并校验指纹；报告路径写成相对仓库 |
| `bench/scenarios.py` | 790 | 场景集生成（斩杀逐选项实打核实 / 专家一致 / 读局面 + 隐藏信息探针）与评测 |
| `configs/bench/{lite,core,home}.toml` + `.lock.json`，`configs/bench/scenarios/v1.json` | — | 三个套件与 292 个场景，入库以便复现（不需要赛事数据） |
| `tests/test_bench.py` `tests/test_platform_room.py` | 796 | 快测 18 + 慢测 6（见 §3） |
| `docs/howto/benchmark.md` `docs/howto/platform.md` | — | 用法、口径、防泄漏措施、限制 |

### 2.2 修改既有文件

| 文件 | 改动 | 原因 |
|---|---|---|
| `common/llm_providers.py` | +95 / −14：`classify_http_error`、`FATAL_KINDS` 与客户端停用；缓存命中 / 思考 token 进结果与计价（`price_cached_in`）；空回复说明里给出思考 token 数 | 真实服务行为（GLM Validation §2–§3） |
| `agents/llm_policy.py` | +45 / −1：空回复可追问一次；`DecisionTrace` 增加首答是否合法及原因；按请求类型汇总、决策耗时分位数 | "执行合法率 100%"会掩盖模型自己的出错 |
| `reps/describe.py` | +3 / −1：`winner` 只在终局给出 | 对局中快照用 0 表示"无胜者"，读起来像"0 号位已胜" |
| `configs/models.toml` | GLM 档案（已用真实接口核对的模型 id、`reasoning_effort`、价目、Coding Plan 端点） | D29 时 GLM 只有注释模板 |
| `scripts/llm_smoke.py` | `--max-tokens` 默认取档案值 | 思考模型在 64 token 下必然空回复 |
| `tests/test_llm_providers.py` | +2 项（按真实报文形状回放 429 + 1113、400 + 1211；token 计价） | 防回归 |
| 文档 | `PLAN.md` D30、`docs/STATUS.md` §3d、`docs/decisions/README.md`、`AGENTS.md`、`README.md`、`reports/README.md`、`tests/README.md`、`docs/howto/lab.md`、`pyproject.toml`（`bench` 包） | |

既有行为不变：D29 的接口、spec、留痕格式只做加法；`data/` 与密钥不入库。

## 3. 验证结果

### 3.1 测试

| 范围 | 结果 |
|---|---|
| `pytest -m "not slow"` 全量 | **536 passed，3 skipped**（D29 时 516 / 3；新增 20：`test_bench` 13、`test_platform_room` 5、`test_llm_providers` 2） |
| 慢测全量（76 项，含 D30 新增 6；设了 `GITCG_PLATFORM_TEST_SERVER`） | **46 passed，27 skipped，3 failed**。D30 新增的 6 项全部通过（含对真实上游服务端自对弈一局）。3 项失败（`test_npc_contestant` / `test_npc_eval` / `test_npc_policy` 各 1 项）在 D29 提交上同样失败、报错相同（`Unknown character id 3102`）：NPC 关卡的敌方角色需要 PvE 引擎覆盖层，本环境未安装；27 项跳过是同一原因（`test_npc_enemies` 带了跳过条件，这 3 项没有）。与本轮改动无关，未修改 |
| 真实上游服务端 | 本机构建上游 `ce9e06c`（与线上同一提交）：平台慢测的"真实服务端自对弈"一项通过；另有两局整局实测（脚本对脚本、GLM-5.3 对脚本），双方流一致、零超时、零回退、零重连 |
| 真实 GLM 接口 | 5,051 次 `glm-5.3` 调用 + 172 次 `glm-5.3-flash`，全部 HTTP 200；85 局零引擎回退、零无效局、零降级局 |

跳过的 3 项快测与本次改动无关：2 项 Web 用例需要本机引擎工作区（`share_id.json`），1 项需要安装 PvE 引擎覆盖层。

### 3.2 数字复核

交付前从原始记录（`data/bench/*/games.jsonl`、`calls.jsonl`、`scenarios.jsonl`、`data/platform/*/result.json`）独立重算了
三份分报告里的主要数字：胜率与 Wilson 区间、配对差与符号检验、分层计数、首答合法率（按请求类型）、token 与成本、延迟分位数、
场景集各项得分、平台对局指标。**全部一致**，只有一处措辞被纠正：16 次空回复的耗时原写"每次约 34–43 秒"，实际是 14 次 34–43 秒、
1 次 73 秒（首局试跑，输出上限 4,096）、1 次 2.1 秒（思考正常结束但正文为空）；相关措辞已在两份报告里改正。

### 3.3 关键数字（出处见各报告）

| 项 | 数值 | 出处 |
|---|---|---|
| GLM-5.3 `lite` 胜率 | 0.929 [0.77, 0.98]（28 局）；对随机 8 / 8、启发式 12 / 12、脚本专家 6 / 8 | Benchmark §2.1 |
| 对启发式配对 | +0.41 [+0.24, +0.59]，13 好 / 0 差，p < 0.001 | Benchmark §2.2 |
| 知识注入 | + 规则 0.857（0 / 2，p = 0.5）；+ 规则 + 策略 0.786（0 / 4，p = 0.125） | Benchmark §2.2 |
| 斩杀场景 | GLM-5.3 0.750、启发式 0.769、随机 0.115（随机水平 0.175） | Benchmark §3 |
| 读局面 / 隐藏信息 | 560 / 560；75 问中 73 次答"无法得知" | Benchmark §3 |
| 首答合法率 | 99.64%（4,406 次询问；16 次不可用，追问后全部合法） | GLM Validation §4 |
| 调用延迟 | p50 3.95 s · p90 8.15 s · p99 14.96 s | GLM Validation §5 |
| 单局 | 约 50 次调用、263 秒、7.7 万 token（无知识） | GLM Validation §5、Benchmark §2.4 |
| 成本（按公开价目估算） | 合计约 16.9 美元；单局 0.12（无知识）– 0.22（规则 + 策略）美元；实际走 Coding Plan 额度 | GLM Validation §6 |

## 4. 局限

1. **模拟器 ≠ 官方**：引擎是社区实现，与官方客户端有已登记的差异（知识库 R12）。
2. **对手上限是脚本专家，没有对人类标定**；GLM-5.3 已赢下 6 / 8，阶梯顶端需要更强的对手。
3. **样本小**：`lite` 每个受试者 28 局，总体胜率半宽 ±0.1–0.18；知识配置之间的差别在这个样本量下分不出来。
4. **"没见过的牌组"轴只测到启发式强度**：赛事牌表没有对应的脚本专家。
5. **真人评测没有做**：平台接入只在本机服务端打过整局；线上服务只发过只读请求；没有与任何真人对局。
6. **只验证了智谱一家**；其余服务商的错误分类按文档写成。`reasoning_effort` 只测了 `low`；套餐额度耗尽的报错形状未见过。
7. **正式神经 checkpoint 没有参评**：云端只有 D28 的小模型，只在单牌组套件上跑通流程。`core` 套件（480 格）未跑任何受试者。
8. 场景集只覆盖"当场能赢"一类可由引擎直接核实的决策；专家一致率只衡量相似度，不当质量用。
9. 正式实验走的是 Coding Plan 端点（官方定位为 Coding Agent 用途），是在账户持有人明确确认后使用的。

## 5. 后续建议（按投入产出排序）

| # | 建议 | 为什么 | 投入 |
|---|---|---|---|
| 1 | 把正式神经 checkpoint 跑进 `core` 套件 | 给出纯策略与 GLM 在同一口径下的位置；也补上阶梯顶端 | 约 1 CPU·小时 / 受试者，无 API 费用 |
| 2 | `lite` 补第 2 轮种子（同 tag 续跑），再比较知识配置 | 样本翻倍；不一致对目前只有 2–4 个 | 约 170 局 × 50 次调用 |
| 3 | 让神经或模型策略驾驶对面的赛事牌表 | 把"没见过的牌组"轴补到 L2 强度 | 改套件配置即可 |
| 4 | 约 2–3 位真人在平台私有房间各打先后手若干局 | 唯一的真人对照；先征得同意并说明对面是 AI | 按 `docs/howto/platform.md` |
| 5 | 向平台维护者询问：机器人可否标明身份进入公开房间；能否提供脱敏历史对局日志 | 后者是"真实高手完整行动记录"的唯一现实来源 | 一封邮件 |
| 6 | 若继续做知识增强：先改知识的选取与呈现（目前 70 个策略单元只有 14 个有适用条件检测器），再测 | 当前配置下"加得越多越差"的方向一致 | 中 |
| 7 | 测 `reasoning_effort = high` 的强度与成本 | `low` 下 79% 的输出已是思考；更深的思考是否换来更强未知 | 每局成本约数倍 |
| 8 | 升级 `gitcg` 后让策略处理 `select_option`，并重新生成场景集 lock | 上游已新增该请求，目前按默认作答 | 小 |
| 9 | 给 3 项依赖 PvE 覆盖层的 NPC 慢测加上与 `test_npc_enemies` 相同的跳过条件 | 未装覆盖层的机器上它们报失败而不是跳过（既有问题，见 §3.1） | 小 |

## 6. 安全与合规

- 密钥只存在于仓库外的文件（权限 600），以环境变量注入，只发往 `open.bigmodel.cn`；交付前对仓库、数据、报告全文检索均无命中。
  **密钥曾以明文出现在对话里，建议作废重建。**
- 没有向线上平台做任何写操作；没有创建任何账号；没有操作官方客户端。
- 没有推送任何提交。
