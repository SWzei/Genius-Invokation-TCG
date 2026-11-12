# howto — 采集与训练

> 详细实现见 `train/README.md`、`train/CONTINUAL_RESOLVING.md`、`docs/PLAYBOOK.md`。

## 采集（CPU 节点）

```bash
python -m train.collect --deck <deck> --all-opponents \
  --seed-start 0 --seed-count 20 --workers 8 \
  --tag <tag> --format compact --no-privileged-state
```

- 一行一局，`data/replays/<tag>/samples.jsonl`；manifest 指纹护栏、按 `task_index` 断点续跑。
- 新 compact 语料带 `token_definition_ids` / `option_definition_ids`（exact id）；旧 fp16 语料不能用于 id 特征训练。
- 采集种子避开 val 残差（`val_every=10` 时取模 10 余 1–9）。
- **不要用种子 0（D28）**：引擎随机种子为 0 时每次掷骰都是同一面；`train.collect` 遇到会告警（行为不改，旧语料可续跑）。
  新语料用 `--seed-start 1`，建 store 时相应传 `--seed-start`。
- **2026-11（D27）座位与特征档**：`--sides {0,1,both}`（默认 0 = 历史行为；引擎固定 0 号位为第 1 回合先手，
  只采 0 号位则模型从未见过「第 1 回合后手」）与 `--encoder-profile {v1,v1s,v2}`（默认 v1 = 历史特征，
  逐字节不变；v1s = 座位相对的回合/行动方标志；v2 = v1s + 对手公开骰子数）。两者都只在非默认时进入指纹，
  旧 replay 目录照常续跑。manifest 新增 `encoder_config`；store 从 manifest 读取并拒绝混用不同特征档。
- `neural:` teacher 的编码档必须与 `--encoder-profile` 一致（采集时自动校验）；
  v1 checkpoint 迁移：`--teacher-spec neural:<v1.pt>#t=1.0#seatrel=1 --encoder-profile v1s --sides both`。

## 建 store

```bash
python -m scripts.datafirst_bc_store --replays data/replays/<tag> \
  --store-cache data/store/<tag>.pt --val-every 10
```

- `meta` 记录 `encoder_config`（2026-11 起取自采集 manifest，旧目录按 v1）、`encoder_profile`、
  `definition_indices`、`definition_ids_present`。
- PG 轮次可用 `--val-every 0`：自博弈数据的 val 只用来看 `val_ce`，对 PG 没有选型意义，默认会丢掉 10% 的 on-policy 局。
- id 训练要求 `definition_ids_present == events`；否则 `datafirst_bc_train --id-buckets` 直接拒绝。

## 训练

```bash
python -m scripts.datafirst_bc_train --store-cache data/store/<tag>.pt \
  --arch cvpn --d-model 256 --epochs 15 --batch-size 256 \
  --save-best --select-metric val_ce \
  --out data/checkpoints/<tag>.pt --report reports/train/<tag>.json
```

- `--save-best` 保存 best（默认 `val_ce`）与 last；A2 的 best 是 ep70，不是 final。
- `--loss ce|pg`；`awr/q` 已有负结果，见 `docs/failures/002`。
- CPU 档 d256 ~150–300 样本/s；A800 用 `--device cuda --batch-size 512`。

## 评测

见 `docs/EVAL_PROTOCOL.md`；认证用 `scripts/eval_protocol.py`，配对种子、双方、纯策略。

## 决策级策略监督（MASD-ADM / VCSD）

反事实证据采集与 `--supervision` / `--distill-coef` 蒸馏训练见 [`masd-adm.md`](masd-adm.md)。
