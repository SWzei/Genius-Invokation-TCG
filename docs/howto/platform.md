# 对战平台接入：让仓库里的策略坐进平台房间

> 代码 `envs/platform_room.py`，命令行 `scripts/platform_play.py`。调研与实测见 `reports/review/2026-11_platform_review.md`。
> 用途：与**真人**在 genius-invokation 对战平台（<https://play.piovium.org>，或自己搭的实例）的房间里对局，并留下完整记录。

## 1. 它是什么

平台服务端（上游 `packages/server`）对每个座位发的 `Notification` / `Request` 就是本地引擎回调里的那两种 protobuf。
`play_seat` 把事件流接到现成的 `envs.match.PolicyPlayer` 上，所以任何策略 spec（`heuristic`、`expert:<deck>`、
`neural:<ckpt>`、`llm:<档案>#kb=…`）都能直接上桌，观测仍然只来自服务端发给该座位的内容。

```
平台服务端 ──SSE: notification / rpc──▶ RoomClient ─▶ PolicyPlayer ─▶ 策略
           ◀──POST actionResponse──────────────────────┘
```

只用标准库，不创建账号（游客身份），除你指定的服务器外不向任何地方发送数据。

## 2. 用法

```bash
python -m scripts.platform_play info --server https://play.piovium.org        # 只读：版本、规则档

# 约战：建一个私有房间，把房间号发给对手（对手在浏览器打开 <server>/rooms/<id>）
python -m scripts.platform_play host --server https://play.piovium.org \
    --deck natlan_battleship --policy "llm:glm-53-plan" \
    --seed 20261115 --action-time 60 --tag vs_alice

# 加入别人建好的房间
python -m scripts.platform_play join --server <url> --room 12345 --deck unyielding_geo --policy "expert:<deck>"

# 自测：一条命令起两个座位，对自己搭的服务端打一整局
python -m scripts.platform_play selfplay --server http://127.0.0.1:3411 \
    --deck0 natlan_battleship --deck1 unyielding_geo --policy0 heuristic --policy1 "expert:<deck>" --seed 7
```

产物在 `data/platform/<tag>/room<id>-<playerId>/`：

| 文件 | 内容 |
|---|---|
| `result.json` | 胜负、回合、决策数、每步作答用时、最小剩余计时、超时 / 回退 / 重连次数、模型用量 |
| `transcript.jsonl` | 逐事件：收到的请求类型与 id、作答、用时 |
| `game_log.json` | 服务端的完整状态日志（座位本人可取） |

## 3. 约束（代码里已强制）

- 非本机服务器上玩家名自动加 `[BOT] ` 前缀；房间默认私有（`--public` 才公开）。
- **不要让机器人与没有同意的人对局。** 约战前说明对面是 AI、用的模型、每步可能思考数秒到数十秒。
- 计时：平台每步 25–300 秒。模型玩家用 `--action-time 45` 以上（GLM-5.3 实测单步最慢 32.6 秒）；
  超时由服务端代打，游客连续 3 次超时判负。
- 牌组目前取脚本池名字（`envs.decks`）；规则档用 `--profile official/v7.2.0` 这类名字（`info` 可列出）。

## 4. 自己搭服务端（用于测试）

上游仓库 `piovium/genius-invokation`，需要 Node ≥ 26.12 与 pnpm 12：

```bash
pnpm install --frozen-lockfile && pnpm build server...
cd packages/server
export JWT_SECRET=<任意> PORT=3411 PGLITE_DATA_DIR=<目录>      # 不设 DATABASE_URL 且非 production 时用内置 PGlite
node scripts/migrate.ts && node --experimental-vm-modules --enable-source-maps --import ./scripts/ts_preload.js src/main.ts
```

上游入口默认监听 IPv6 通配地址；在没有 IPv6 的机器上（本次的云端容器即是）需要把 `main.ts` 里的监听地址改成 `127.0.0.1`。

然后 `GITCG_PLATFORM_TEST_SERVER=http://127.0.0.1:3411 python -m pytest tests/test_platform_room.py -m slow`。
没有服务端时，慢测用仓库内的仿真房间（按上游协议实现）跑整局。

## 5. 已知限制

- `gitcg 0.21.0` 之后上游新增了 `select_option` 请求；客户端手工解码并按服务端的超时默认值（选项 0）作答、计数。
  升级 `gitcg` 后应改为交给策略决定。
- 线上服务只做过只读请求；整局测试都在本机实例上。线上网络抖动下的表现没有测过。
- 平台没有天梯与匹配：真人样本只能靠约战，量小，不能外推为"天梯水平"。
