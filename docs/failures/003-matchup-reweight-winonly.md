---
title: "003 — matchup 重加权 / 胜局筛选"
kind: failure
status: negative  # 胜局筛选；H5 部分见文末 2026-11 更正（invalid）
freshness: 2026-10-27
machines: [local]
authority: evidence
related: ["reports/explore/plan_strength_2day_kaggle.md", "reports/explore/lit/f06_targeted_data.md"]
---

# 003 — matchup 重加权 / 胜局筛选

## 假设

按 matchup 给样本加权（deficit/balance）或只保留胜局，能修补 floor / 提升强度。

## 设置

- H5：`--matchup-weight deficit`，权重来自 `store.value`（teacher 对局胜负），均值归一化。
- 胜局筛选：只保留 trainee 赢的局做 BC。
- 评测：同 deck 专家基线、配对种子、纯策略。

## 结果

- H5 在 SA 上 −9.1pp，dvalin 上 −3.4pp；多数 matchup 权重只在 0.84–1.22。
- 胜局筛选 −0.14；`%BC`/return-conditioned 同样不适用。
- 证据：`reports/explore/plan_strength_2day_kaggle.md` §Day2b、`reports/train/bc_scale_datafirst.md`。

## 归因

- **权重方向错**：`store.value` 是 teacher 的胜负，不是 student-vs-expert 的可修 gap；deficit 会抬高“老师也输”的 matchup，正好放大最不可学的标签。
- **没有新信息**：只改旧语料的损失权重，不增加目标 matchup 的状态/对手行为覆盖。
- **组内样本太少**：每 matchup 约 20 局，deficit 估计噪声大；再归一化后只微调 0.84–1.22。
- **胜局由对手/种子决定**：同一策略对不同对手的胜负不是策略质量信号。

## 重开条件

- 只在**采集层**做混合：target 25–35% + uniform/anchor 65–75%；单 matchup ≤25%。
- 目标只选 `expert Wilson low ≥45%` 且 `student point <45%` 的可修 matchup；teacher-limited 不补。
- 用 fresh seeds 选 target，另用不重叠 seeds 报分。
- 证据：`docs/PLAYBOOK.md` §1/§2、`reports/explore/lit/f06_targeted_data.md` E1。

## 不要重演

- 不要用 `--matchup-weight deficit` 原实现。
- 不要用整局回报做过滤/条件化。
- 不要只采失败 matchup。

## 2026-11 更正：H5 的实验实现无效（不改上文原文）

- `scripts/train_bc_scale.matchup_weights_for_store` 按 `key[:-1]` 分组；真实 store 的键是
  `(deck, opponent, seed, step)`，所以分组单位是**局**而不是 matchup。每局只有一个回报值，`deficit`
  实际上等于「输局权重 ×1.45、胜局 ×1.0 再归一化」；`balance` 等于按局均衡。
- 旁证：上文「多数 matchup 权重只在 0.84–1.22」正是该 bug 的两点分布（输局约 40% 时
  1.45/1.18≈1.23、1/1.18≈0.85），而不是 matchup 粒度的连续权重。
- 单测之所以没抓到：fixture 把同一 matchup 的所有样本都放在 seed 0。
- 修复与回归：`matchup_of_key()`；`tests/test_matchup_weights.py` 新增真实布局用例（旧实现 2 例失败）。
- 结论修订：H5 的 −9.1pp/−3.4pp 测的是「输局加权 BC」，不是 matchup 重加权；**matchup 重加权本身未被检验**。
  上文「归因」中关于 teacher 胜负方向、样本稀少、无新信息的论证仍然成立，因此重开条件不变：
  优先采集层混合，而不是 loss 层权重。证据：`reports/review/2026-11_technical_review.md` §3.1。
