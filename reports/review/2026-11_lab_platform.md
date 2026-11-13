---
title: "2026-11 实验平台：模型接入、知识配置、人机实验闭环 —— 实现与验证"
kind: report
status: valid
freshness: 2026-11-12
machines: [cloud-2c]
authority: evidence
related: ["PLAN.md#D29", "docs/howto/lab.md", "reports/review/2026-11_masd_adm_compat.md"]
---

# 2026-11 实验平台（D29）

> 基线：D28 之后的代码。环境：云端 2 核 / 7 GB，Python 3.12，`gitcg 0.21.0`，torch CPU，Chromium（Playwright）。
> 架构与用法见 `docs/howto/lab.md`；本报告只记录实际执行结果。

## 0. 结论

1. **已实现并验证（离线）**：统一的模型接入层、LLM 完整对局策略、可配置知识注入、Web 实验台、
   人工数据到现有训练接口的导出，全部有测试；浏览器端到端跑通人机整局与 AI 对 AI 改选。
2. **没有验证的两件事**，都需要真实模型与你的密钥：
   - **真实服务的连通性**。三种协议按各家当前文档实现，测试对象是本地仿真服务，不是真实接口。
   - **知识注入是否让模型打得更好**。只验证了知识确实按配置进入提示词并被记录；强度影响没有测量。
   工具已备好：`scripts.llm_smoke`（连通性）与 `scripts.llm_arena`（配对比较）。
3. **原有功能无回归**：快测 516 通过 / 3 跳过（上一轮 474 / 3，新增 42 项）；相关慢测 23 项通过；
   既有代码文件只改了 7 个（新增 107 行、改写 6 行），不改变原有行为；旧监督记录重新序列化逐条相同。
4. LLM 玩家与人工数据**不进强度验收**；此前蒸馏实验没有性能结论，本层不以它为前提。

## 1. 改动清单

新增：

| 文件 | 行数 | 作用 |
|---|---|---|
| `common/llm_providers.py` | 673 | 模型档案、三种协议、重试 / 自适应 / 预算 / 成本 / 调用日志、离线 `mock` |
| `reps/describe.py` | 426 | 行动方可见局面与合法选项 → 结构与文本（提示词、界面、回放共用） |
| `reps/knowledge_pack.py` | 459 | 知识档案、按决策选取、分块渲染、溯源与版本告警 |
| `agents/llm_policy.py` | 427 | LLM 完整对局策略、讨论、`llm:` / `llm-assist:` spec |
| `lab/session.py` `runner.py` `worker.py` | 716 | 对局规格与存储、事件流与座位逻辑、每局一个进程 |
| `lab/server.py` + `static/index.html` | 1,126 | HTTP API 与单页界面（标准库、零构建） |
| `lab/replay.py` `export.py` `verify.py` | 711 | 确定性回放、BC / 监督记录导出、策略对比、人工纠正的反事实校验 |
| `scripts/llm_smoke.py` `llm_arena.py` | 243 | 连通性自检；模型 / 知识配置的配对比较 |
| `configs/models.toml` `knowledge.toml` | — | 档案配置（不含密钥） |
| `tests/test_llm_providers.py` `test_llm_platform.py` `test_lab.py` `e2e/lab_browser.py` | 1,456 | 44 项测试（42 快 + 2 慢）与浏览器脚本 |
| `docs/howto/lab.md` | — | 架构、配置、用法、限制 |

修改（7 个既有代码文件，新增 107 行、改写 6 行）：`envs/policy.py`（两种新 spec）、`reps/strategy.py`（`HumanSignal`、两种证据类别、
`DecisionSupervision.human`）、`train/strategy_targets.py` 与 `scripts/datafirst_bc_train.py`（`human` target 模式）、
`agents/llm_assist.py`（修一处误标，见 §4）、`pyproject.toml`、`.gitignore`。文档：`PLAN.md` D29、`docs/STATUS.md`、
`docs/decisions/README.md`、`AGENTS.md`、`README.md`、`agents/README.md`、`web/README.md`、`tests/README.md`。

## 2. 需求对照

| 需求 | 落地 | 验证 |
|---|---|---|
| OpenAI / Claude / Gemini / DeepSeek / GLM / 兼容接口 | provider 预设 + 三种协议 | 请求与响应形状对本地仿真服务逐项核对；**未调真实接口** |
| 现有本地策略模型 | 同一套 spec（`expert:` `heuristic` `neural:`）；界面可选 checkpoint | 界面与 API 测试；网络策略的价值 / 前 5 项概率展示已手工核对 |
| 配置、切换、对比模型 | `configs/models.toml`、`llm:<档案>#model=…`、`scripts.llm_arena`、回放页"策略对比" | 配置分层 / spec 解析测试；`llm_arena` 用离线模型跑通 |
| API Key 管理 | 只认环境变量 / `.env`；配置含密钥即拒绝；日志与接口不含密钥 | 测试 |
| 推理参数与调用预算 | 档案字段；每档案硬预算；每局调用上限；`llm_arena --max-calls / --max-cost` | 测试（预算在发请求前拦截） |
| 模型准确理解局面 | `reps/describe.py`：角色 / 装备 / 状态 / 召唤 / 支援 / 骰子 / 手牌（含费用与牌面文字）/ 技能文字 | 对行动方信息的完整性有测试；**模型是否真的读懂，没有用真实模型测** |
| 执行合法行动 | 回复映射到合法选项并校验，否则回退 | 四种离线模型（随机、乱答、越界、接口失败）各打一整局，引擎零回退 |
| 记录决策、延迟、成本、异常 | `DecisionTrace`、`calls.jsonl`、对局结束汇总 | 测试 |
| 选择性加载规则 / 策略 / 专家对局 / 自定义 | `configs/knowledge.toml` 四类来源 | 测试 |
| 知识增强推理 | `llm:<档案>#kb=<知识档案>`；讨论也可带知识 | 测试（知识进入提示词并写入留痕） |
| 不同知识配置的效果比较 | `scripts.llm_arena`（配对）、回放页策略对比 | 工具跑通；**没有真实模型的比较结果** |
| 来源可信、版本一致、事实与观点分开 | 证据类别过滤、分块标题、知识库版本与基线告警、自定义须自报类别 | 测试 |
| 杜绝隐藏信息泄漏 | 提示词 / 知识选取 / 界面事件都只取行动方视图；服务端按座位过滤 | 测试（含"真实对手手牌不出现在文本里"与"人类视角拿不到模型座位私有数据"） |
| Human vs AI、AI vs AI、Web 交互 | `lab/` | API 测试 + 浏览器端到端 |
| 决策查看、干预、纠错、评价、讨论、回放、对比 | 见 `docs/howto/lab.md §4` | 同上 |
| 自动保存对局、示范、偏好反馈 | `data/lab/<id>/` 五个文件 | 测试 |
| 兼容 BC / PG / MASD-ADM / VCSD | `lab.export bc` → 原 store 与训练器；`HumanSignal` → `--distill-target human`；`lab.verify` | 导出 → 建 store → `ce` / `pg` / `awr` 各训 1 轮；监督记录按键对齐；反事实校验 1 项慢测 |
| 新实验规避种子 0 | 实验台与 `llm_arena` 拒绝种子 0；默认取未用过的种子 | 测试 |

## 3. 测试结果

| 范围 | 结果 |
|---|---|
| `pytest -m "not slow"` 全量 | **516 passed，3 skipped**（204 s；上一轮 474 / 3） |
| 新增快测 | 42：`test_llm_providers` 13、`test_llm_platform` 18、`test_lab` 11 |
| 慢测（本轮新增 2 + 与改动相关的既有 21） | **23 passed**：`test_lab` 2、`test_masd_adm` 6、`test_llm` / `test_llm_matrix` / `test_human_policy` / `test_web_rpc_server` / `test_info_leak` / `test_replay_consistency` / `test_collect` / `test_fork_bridge` / `test_belief_root` 共 15 |
| 浏览器端到端（Chromium） | 通过，控制台 0 报错 |
| 旧数据兼容 | D28 的 100 条监督记录读入后重新序列化，与原文件逐条相同 |

未跑：仓库 70 项慢测中其余 47 项（NPC、CFR 搜索、蒸馏矩阵等，与本次改动无交集）。

各组测试覆盖的内容见 `tests/README.md` 的 D29 段。几项值得单独说明：

- **协议核对的范围**。仿真服务检查了客户端发出的东西：OpenAI 兼容协议的 `Authorization: Bearer`、`messages`、
  `max_tokens` / `max_completion_tokens`、`response_format`；Anthropic 的 `x-api-key`、`anthropic-version`、顶层 `system`、
  跳过 thinking 块；Gemini 的 `x-goog-api-key`、`systemInstruction`、`contents` 角色映射、`responseMimeType`、
  思考 token 计入输出。它证明客户端按文档说话，不证明服务端今天仍按文档回答。
- **浏览器端到端做了什么**：人类执 1 号位对离线模型，走 8 步（含换牌、重掷的点选）→ 请求建议 → 向模型提问 →
  评价对方上一步 → 托管到终局 → 进回放（107 个决策）→ 以 0 号位视角纠正一步 → 策略对比（53 行）→ 导出 BC 语料
  → 新开 AI 对 AI 干预局并改选一步。
- **信息边界**的测试是双向的：对手真实手牌（来自全量状态）不出现在提示文本里；模型座位自己视图里的手牌名，
  不出现在人类座位能收到的任何事件里（已打出的牌除外）。

## 4. 审查中发现的问题

| 问题 | 位置 | 处理 |
|---|---|---|
| 选人 / 重掷 / 换牌 / 挑牌的候选项都被描述成 "declare end" | `agents/llm_assist.py::describe_candidate`（既有） | 已修并加回归测试。旧的 LLM 重排模式在这几类决策上给模型看的是错误的候选文本 |
| 模型客户端只有 OpenAI 兼容协议，无重试、无预算、无成本记录 | `common/llm.py`（既有） | 保留原类不动；新客户端与它同签名，旧调用方可直接换用 |
| 界面请求里显式的种子 0 被当成"未填"、悄悄换成自动种子 | `lab/server.py`（本轮新代码） | 被测试抓到，已改为拒绝 |
| 离线模型在追问后按追问消息数选项，可能"碰巧合法" | `common/llm_providers.py`（本轮新代码） | 被整局测试抓到，已修 |
| 干预界面把重掷的 144 个子集全部列成按钮 | `lab/static/index.html`（本轮新代码） | 截图检查发现；改为显示提议 + 点选骰子 / 手牌后改选 |

## 5. 没有验证的事项与限制

1. **真实接口**：没有密钥，未调用任何付费服务。各家近期的两类参数变动（`max_completion_tokens`、不接受
   `temperature`）做了自动适配，适配逻辑按文档里的报错措辞匹配，真实报错措辞不同时不会触发，需要在档案里显式设置。
2. **模型 id**：`configs/models.toml` 只预置了 `deepseek-chat` 与两个 Claude 档案；OpenAI / Gemini / GLM 是注释模板，
   需要你填当前的模型 id。预置的 id 也可能过期，以服务商文档为准。
3. **局面理解**：提示词的完整性有测试，但"模型读懂了没有"只能看真实模型的作答率、回退率与对局表现
   （`llm_arena` 的 `model_answer_rate`、`errors`）。提示词单次约 2,000–3,500 字（含牌面文字），带知识时更长，
   这直接决定成本；`detail=0` 可去掉牌面文字。
4. **知识效果**：未测量（见 §0）。另外策略单元只有 14/70 个有适用条件检测器，其余不会被选中；自定义资料按字面重合度检索。
5. **人工数据的质量标记不是强保证**："信息干净"只反映界面给了哪个视角，管不了标注者是否自己打过对面那一方。
6. **`--distill-target human` 是未经验证的偏好**。要把人工纠正当成经过检验的监督，先跑 `lab.export verify`；
   它继承 D28 证据生成的全部限制（仅行动决策且快照与决策重合、假设对手牌表公开），并且 D28 已经测得
   终局胜负 rollout 的检验力很低——多数纠正会得到"无结论"。
7. **规模**：实验台是单机工具，每局一个进程，没有鉴权，默认只绑本机；事件文件每局约 2 MB。
8. **牌组**：界面只列脚本池的 20 套；`verify` 也要求牌组在池内（rollout 需要对应的脚本专家）。

## 6. 复现

```bash
python -m pytest -m "not slow"                                   # 516 passed, 3 skipped
python -m pytest tests/test_lab.py -m slow                       # 反事实校验 + 浏览器端到端
python -m scripts.llm_smoke --list                               # 档案与密钥状态
python -m lab.server --port 8780                                 # 实验台
python -m scripts.llm_arena --deck natlan_battleship \
    --contestants "llm:mock:random" "llm:mock:random#kb=rules-strategy" "expert:<deck>" \
    --opponents superconduct_aggro --seeds 1 --tag smoke        # 离线跑通比较流程（无强度含义）
```
