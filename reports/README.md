# reports — 一次性实验证据

> **这里不是当前状态**。当前基线/排产见 [`docs/STATUS.md`](../docs/STATUS.md)；
> 有效方法见 [`docs/PLAYBOOK.md`](../docs/PLAYBOOK.md)；失败/重开见 [`docs/failures/`](../docs/failures/)。
> 报告只放聚合证据、命令、产物路径；原始逐局/逐事件数据在 `data/`（gitignore）。

## 当前最重要

| 文件 | 内容 | 状态 |
|---|---|---|
| [`review/2026-11_technical_review.md`](./review/2026-11_technical_review.md) | 2026-11 技术审查：H5 分组 bug、对手骰数、座位覆盖（D27）+ 座位探针结果 | valid |
| [`review/2026-11_masd_adm_compat.md`](./review/2026-11_masd_adm_compat.md) | MASD-ADM / VCSD 兼容层（D28）：接口、最小闭环、未证明性能收益 | valid |
| [`review/2026-11_lab_platform.md`](./review/2026-11_lab_platform.md) | 实验平台（D29）：模型接入、知识配置、人机实验闭环；真实 API 未调用 | valid |
| [`review/2026-11_platform_review.md`](./review/2026-11_platform_review.md) | Platform Review（D30）：对战平台 / 模拟器 / 自动化工具调研与接入实测 | valid |
| [`review/2026-11_benchmark.md`](./review/2026-11_benchmark.md) | Benchmark（D30）：评测设计、基线与 GLM-5.3 实测；模拟器内、小样本 | valid |
| [`review/2026-11_glm_validation.md`](./review/2026-11_glm_validation.md) | GLM Validation（D30）：真实接口测试记录、性能与成本 | valid |
| [`review/2026-11_d30_technical_summary.md`](./review/2026-11_d30_technical_summary.md) | Technical Summary（D30）：实际修改、验证结果、局限与后续建议 | valid |
| [`review/2026-11_deepseek_kb.md`](./review/2026-11_deepseek_kb.md) | DeepSeek-V4.1-Flash 接入与本地知识库基础能力评测（D31）：知识库体检、规则问答、知识配置的场景与整局实验、运行间噪声基线 | valid |
| [`review/2026-11_kb_training.md`](./review/2026-11_kb_training.md) | 知识接入的分阶段优化（D32）：train/dev/test 划分、S0–S5 各阶段记录、情境规则题与斩杀转化、test 与整局终评、失败与修复 | valid |
| [`review/2026-11_kb_d33_prereg.md`](./review/2026-11_kb_d33_prereg.md) | D33 预先登记：候选、留出题型、dev 选择规则、最终评估；之后只追加 | valid |
| [`review/2026-11_kb_d33.md`](./review/2026-11_kb_d33.md) | 针对性优化与防过拟合检验（D33）：dev 选择、v3 / `lite_fresh` 新数据终评、留出题型、充能上限缺失导致的害处、GLM 对照 | valid |
| [`review/2026-11_kb_d37_prereg.md`](./review/2026-11_kb_d37_prereg.md) | D37 预先登记：评测指标校准规则、派生事实与角色卡的核实与门禁、dev 与跨模型计划、预算；之后只追加 | valid |
| [`review/2026-11_kb_d37.md`](./review/2026-11_kb_d37.md) | 更公平的评测、派生事实、角色卡与跨模型对战（D37）：指标校准、预演核实与泄漏测试、dev 门禁、跨模型、花费 | valid |
| [`review/2026-11_kb_d36_prereg.md`](./review/2026-11_kb_d36_prereg.md) | D36 预先登记：多轮进化的候选、门禁、停止边界与 test 计划；之后只追加 | valid |
| [`review/2026-11_kb_d36.md`](./review/2026-11_kb_d36.md) | 多轮进化：带知识库的 DeepSeek 镜像对战（D36）：各轮改动、逐项门禁、最终 test、观测层对照、花费 | valid |
| [`review/2026-11_kb_d35_prereg.md`](./review/2026-11_kb_d35_prereg.md) | D35 预先登记：分歧点评测的判据与预算、技术修复的核对；之后只追加 | valid |
| [`review/2026-11_kb_d35.md`](./review/2026-11_kb_d35.md) | 技术问题排查、教师管线与分歧点评测（D35） | valid |
| [`review/2026-11_kb_d34_prereg.md`](./review/2026-11_kb_d34_prereg.md) | D34 预先登记：模型对战设计、分区、门禁、停止规则；之后只追加 | valid |
| [`review/2026-11_kb_d34.md`](./review/2026-11_kb_d34.md) | 模型对战驱动的知识库分层进化（D34）：A/A 校准、A/B 主指标、规则卡与引擎核对、教师分析、策略层门禁 | valid |
| [`review/2026-11_d30_summary.md`](./review/2026-11_d30_summary.md) | Technical Summary（D30）：改动、验证结果、局限与后续建议 | valid |
| [`bench/`](./bench/) | `bench.run` / `bench.scenarios` / `bench.compare` 生成的汇总（`do_not_edit`） | generated |
| [`EXPLOIT_LADDER.md`](./EXPLOIT_LADDER.md) | 逐 deck PG 剥削阶梯：dgeo 0.880 / ungeo 0.909 | valid |
| [`SPECIALISTS.md`](./SPECIALISTS.md) | 19 个 deck 的认证最优臂（自动生成） | generated |
| [`explore/p0_parity_20261027.md`](./explore/p0_parity_20261027.md) | P0 parity / exact id / 干净语料 / A2 复核 | valid |
| [`explore/literature_review.md`](./explore/literature_review.md) | 7 条文献线 + D25/D26 提案 | valid |
| [`explore/docs_audit.md`](./explore/docs_audit.md) | 63 份文档盘点 + 整理方案 | valid |
| [`explore/a2_id_screening.md`](./explore/a2_id_screening.md) | A2 原始数字（**结论无效**） | invalid |
| [`explore/eval_protocol.md`](./explore/eval_protocol.md) | 已迁到 `docs/EVAL_PROTOCOL.md` 的 stub | stub |

## 分类

- **训练/数据**：`train/*.json`、`train/*.md`、`datafirst_bc.md`、`train/bc_scale_datafirst.md`。
- **搜索/自博弈**：`search/*.md`、`train/a3_m3_cpu_screening.md`、`EXPLOIT_LADDER.md`。
- **评测**：`explore/*.json`、`arena/*.json`、`eval_protocol_smoke.json`。
- **NPC PvE**：`npc/pve_v1_gate.md`（当前）；B2/B3 冒烟聚合 `npc/npc_pve_smoke_v1.json` 保留为证据。
- **Web**：`web/`（当前协议/状态）；C0 起步报告已删除，内容并入 `web/README.md`。
- **LLM**：`llm/*.json`。
- **引擎/基准**：`engine/*.json`、`benchmarks/*.json`、`LOCAL_BASELINE.md`。
- **文献/审计**：`explore/lit/`、`explore/literature_review.md`、`explore/docs_audit.md`。

## 规则

1. **报告是证据，不是状态**：不要把“下一步”写进报告；状态进 `docs/STATUS.md`。
2. **数字带口径**：deck / policy / seeds / n / gate / date；禁止只写 pooled。
3. **生成文档勿手改**：`SPECIALISTS.md` 等由 `python -m scripts.specialist_table` 生成。
4. **失效不删除**：顶部加 `status: invalid|superseded|archived` + 原因 + 链接；原文保留。
5. **路径保留**：移动 canonical 文档时在原位置留 stub（如 `explore/eval_protocol.md`），避免断链。

## 常用命令

```bash
python -m eval.arena --smoke --seeds 3 --workers 12
python -m scripts.eval_protocol --sample-sizes
python -m scripts.specialist_table                 # 生成 SPECIALISTS.md
python -m scripts.compare_eval_runs <tag_a> <tag_b>
```
