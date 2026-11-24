# Benchmark：对局套件 + 决策场景集

> 入口 `bench/`，配置 `configs/bench/`。实测结果见 `reports/review/2026-11_benchmark.md`。
> 这是**模拟器内**的评测：它回答"在这个引擎里、对这些对手、用这些牌组有多强"。
> 纯策略的强度**认证**仍走 `scripts.eval_protocol`（`docs/EVAL_PROTOCOL.md`）；LLM 玩家不进强度验收（`AGENTS.md`）。

## 1. 两条轨道

| 轨道 | 测什么 | 一次评测的成本 | 入口 |
|---|---|---|---|
| **对局套件** | 整局胜率，按对手强度 / 牌组 / 规则版本分层；模型另报合法率、延迟、token、费用 | 每个受试者 × 每个格子一整局 | `python -m bench.run` |
| **决策场景集** | 单步决策：斩杀是否拿下、与脚本专家的一致率、读局面是否正确、是否臆测隐藏信息 | 每个场景一次决策 | `python -m bench.scenarios` |

对局套件有外部效度（真的打完一局），但每局只给 1 比特、方差大；场景集便宜、答案由引擎核实，但只覆盖能核实的那部分决策。两者一起报。

## 2. 对局套件

### 2.1 格子

套件文件（`configs/bench/<name>.toml`）由若干 `[[groups]]` 组成，每组是 **受试牌组 × 对手 × 种子 × 先后手** 的笛卡尔积，
带一个规则版本。一个 **格子（cell）** = `(组, 受试牌组, 对手, 版本, 种子, 座位)`。
**所有受试者打完全相同的格子**，所以任意两个受试者逐局配对。

| 轴 | 取值 | 说明 |
|---|---|---|
| 对手强度 | `L0-random`（`legal_random`）→ `L1-heuristic` → `L2-expert`（对应牌组的脚本专家） | 阶梯是相对的，**没有对人类标定** |
| 牌组 | 脚本池牌组（`pool`）；赛事真实牌表的 `test` 划分（`human`） | `human` 牌组没有脚本专家，也从未进过采集牌池——它是"没见过的牌组"轴 |
| 规则版本 | 牌表自己的版本（`heldout-native`）；同一批牌表放到引擎最新规则下（`heldout-latest`） | 两组牌表相同，差别只有规则版本 |
| 先后手 | 每个格子两个座位各一局 | |
| 种子 | `BENCH_SEED_BASE = 7,100,001` 起的保留区段 | 仓库的采集与训练用小种子，不与之重叠；永不使用种子 0 |

现有套件：

| 套件 | 格子 | 用途 |
|---|---|---|
| `lite` | 56（`--replicates 1` 时 28） | 每步要几秒的受试者（模型 API） |
| `core` | 480 | 以引擎速度出牌的受试者（脚本、神经网络） |
| `home` | 16 | 单牌组（`double_geo_navia`）对同一阶梯：给只在这套牌上训练过的策略一张同口径的表 |

每个套件旁边有 `<name>.lock.json`：展开后的全部格子与真人牌表的具体卡牌。运行时只读 lock，
所以别人的机器上没有赛事数据也能复现；`python -m bench.suite freeze <name>` 重新生成（需要 `GITCG_DATA_RELEASE`），`python -m bench.suite show <name>` 查看。
套件指纹写进每次运行的 `meta.json`，套件变了就拒绝续跑。

### 2.2 运行

```bash
# 参照组（免费）：脚本与启发式
python -m bench.run --suite lite --subjects heuristic legal_random "expert:<deck>" --tag lite_refs --workers 2

# 模型（要密钥；--max-calls / --max-cost 是全局硬上限）
python -m bench.run --suite lite --replicates 1 \
    --subjects "llm:glm-53-plan" "llm:glm-53-plan#kb=rules-strategy" \
    --tag lite_glm53 --workers 3 --max-calls 12000

python -m bench.run --suite lite --tag lite_glm53 --report-only     # 只重算报告
```

- 每局一个子进程（行动编码表是进程级的）；模型对局主要在等网络，可以并行。
- 逐局追加到 `data/bench/<tag>/games.jsonl`，重跑同一命令只补缺的 `(受试者, 格子)`；同一 `--tag` 可以后加受试者。
- 模型调用另记 `calls.jsonl`（不含提示词与密钥）。
- `'<deck>'` 展开为格子的受试牌组；`expert:<deck>` 只在有脚本专家的牌组上有格子可打。

### 2.3 报告（`reports/bench/<tag>.json` + `.md`）

| 指标 | 定义 |
|---|---|
| 胜率 | 胜 1、平 0.5、负 0；Wilson 95% 区间；按对手强度、组、牌组类别、规则版本分层 |
| 配对差 | 与参照受试者在**相同格子**上的分差均值，正态近似 95% 区间；同时给 更好 / 更差 / 相同 的局数与**精确符号检验** p 值 |
| 首答合法率 | 模型第一次回复就能映射到合法选项的比例（执行的行动永远合法：不可用的回复会追问一次，再不行回退） |
| 作答率 | 最终由模型自己决定的决策比例 |
| 延迟 | 每次调用均值；每个决策的 p50 / p90 / 最大值 |
| token 与费用 | 每决策、每局；费用按档案里填的单价估算 |
| 运行健康 | 引擎回退、无效局（出错 / 超时）、**降级局** |

**降级局**：模型作答率低于 90% 的局说明"打这局的主要不是模型"，保留在原始数据里但不计入该受试者的胜率，并单独计数。
出现致命接口错误（密钥无效、余额不足、模型不存在）时该受试者立即停止，不会让回退策略替它把剩下的局打完。

## 3. 决策场景集

场景存的是"怎么走到这一步"（牌组、种子、规则版本、双方到此为止每步选的选项序号）。引擎是确定性的，
重放这些序号就得到完全相同的决策上下文——模型看到的提示词与真实对局里由同一段代码、从行动方视角生成。

| 类别 | 标签怎么来 | 计分 | 注意 |
|---|---|---|---|
| `lethal` 斩杀 | 把该决策的**每个**合法选项都在引擎里实际打出去；之后无人再做决策且己方获胜的选项即"获胜集" | 选中获胜集中的任一项 | 随机水平 = 获胜集大小 / 选项数（逐题）；源对局由脚本专家打，所以专家自己的得分部分是自证的 |
| `agreement` 一致 | 抽样的脚本专家行动决策；标签是专家当时打的那一步 | 与专家相同 | **这是"像不像脚本"，不是决策质量**，不叫准确率 |
| `quiz` 读局面 | 答案取自结构化视图：出战角色、血量、骰子数、手牌数、回合数 | 完全正确 | 另含一道隐藏信息题："X 是否在对方手牌中"（X 确实在）。**唯一正确答案是"无法得知"** |

```bash
python -m bench.scenarios build --name v1 --games 40 --workers 2          # 生成（已入库：configs/bench/scenarios/v1.json）
python -m bench.scenarios eval --name v1 --subjects heuristic legal_random "llm:glm-53-plan" --tag scen_v1
```

- 场景种子在 `BENCH_SEED_BASE + 500,000` 起的另一段保留区间，与对局套件不重叠。
- 结果追加到 `data/bench/<tag>/scenarios.jsonl`，可续跑；汇总到 `reports/bench/<tag>.json` + `.md`。
- `quiz` 只对模型受试者有意义。

## 4. 防泄漏与防偏差

| 风险 | 做法 |
|---|---|
| 评测对局被用于训练 | 保留种子区段；真人牌表只取 `test` 划分 |
| 隐藏信息进入提示词 | 提示词只由行动方视图生成（`reps.describe`）；`quiz` 的隐藏信息题直接检验模型是否臆测 |
| 先后手、发牌运气 | 每个格子两座位各一局；所有受试者同种子，逐局配对 |
| 模型挂了、回退策略替打 | 降级局剔除并计数；致命错误即停 |
| 小样本上读出"提升" | 一律给区间；配对比较给精确符号检验；报告末尾写明口径 |
| 生成者偏差 | 斩杀场景的生成者（脚本专家）单独标注；`agreement` 不当质量指标 |
| 套件被悄悄改动 | 指纹 + lock 文件，续跑时校验 |

## 5. 这套评测**不能**说明什么

- **不是真人竞技水平**。对手阶梯最高是脚本专家，没有对人类标定；引擎是社区实现，与官方客户端有已登记的差异。
  真人评测的做法见 `docs/howto/platform.md`。
- **不是强度认证**。`lite` 一轮 28 格，整体胜率的 Wilson 半宽约 ±0.15–0.18；两个受试者差 0.1 在这个样本量下分不出来。
- 场景集的 `lethal` 只覆盖"这一步就能赢"的局面，不覆盖需要多步规划的决策。

## 6. 知识库评测（2026-11-21 起）

对局与场景测的是"加了知识以后打得怎样"。知识库本身另有两件工具，分开回答"知识库里有什么、能不能被找到、被用到了什么"。

| 工具 | 测什么 | 调用模型 | 入口 |
|---|---|---|---|
| 注入体检 | 真实对局的每个决策点上，各知识配置实际选中哪些规则节 / 策略单元、多长、有无版本告警 | 否 | `python -m bench.kb_probe` |
| 规则问答 | 56 道单选题（答案逐字出自规则章节）；闭卷 / 现有检索 / BM25 检索 / 给定标准章节 四种条件 | 是 | `python -m bench.kb_qa` |

```bash
python -m bench.kb_probe --suite lite --profiles rules rules-strategy rules-strategy-full --tag kb_probe_lite
python -m bench.kb_qa check                       # 题库校验：逐字证据、选项、编号
python -m bench.kb_qa retrieval                   # 检索命中率（不调用模型）
python -m bench.kb_qa eval --profiles deepseek-flash --tag kbqa_ds
```

- 题库 `configs/bench/kb_qa/rules_v1.json`：每题记录标准章节与逐字证据，`check` 逐题核对证据出现在该章节原文里。
  **标准答案 = 知识库原文**，所以它测的是知识库对模型是否可用，不是知识库与官方客户端是否一致（那由知识库自己的交叉核验负责）。
- 问答按 `(模型档案, 条件, 题号)` 续跑；与闭卷的配对比较用精确 McNemar 检验。
- 知识配置 `rules-strategy-full`（`configs/knowledge.toml`）把策略单元按"结论 + 关键变量 + 局限"呈现，
  其余同 `rules-strategy`；用来区分"知识库内容有没有用"与"当前简短呈现有没有用"。`strategy_detail` 默认仍是 `brief`。

## 7. 知识接入的分阶段优化（D32，2026-11-21 起）

D31 的结论是"知识库内容可用，但接入层没让它在决策时起作用"。D32 用一套固定的数据纪律逐阶段改接入层，每一阶段都留档。

### 7.1 数据划分

- 场景集 v2（`configs/bench/scenarios/v2.json`，160 局源对局、219 道斩杀题）的每个源对局按种子固定分到
  `train` / `dev` / `test`（约 40 / 30 / 30，`bench.scenarios.split_of`），同一局的所有题同属一份。v1 没有划分，整体当 `train`。
- **错误分析、频次统计等一切拟合只在 `train` 上做；阶段之间只在 `dev` 上比；`test` 与 `lite` 整局只在选定最终阶段后各跑一次。**
- 生成可续跑：每局源对局完成即写入 `data/bench/scen_build_<name>.jsonl`，中断后重跑同一命令从断点继续。

### 7.2 斩杀的三种计分

| 字段 | 含义 | 用法 |
|---|---|---|
| `correct` | 这一步就选了立即获胜的选项（D30 原口径） | 会把"先打一张免费牌再斩杀"判错 |
| `kept` | 这一步赢了，或者走完这一步、在对方行动之前的下一个己方决策上仍有立即获胜的选项 | `bench.scenarios keep` 可为旧运行补算 |
| `converted` | 让受试者继续打完本轮（最多 `--max-steps` 个己方决策），在对方行动前赢下 | `--convert`，D32 的斩杀主指标；用单独的 `--tag` |

### 7.3 情境规则题（`bench.kb_situ`）

斩杀转化在 v1 上已有 0.92（无知识），接近天花板，对知识接入不敏感。情境规则题从真实对局的决策点取局面，
问一道必须结合**当前局面**与**规则表**才能答的单选题，标准答案由程序从可见状态和知识库规则表算出：

| 题型 | 依据 | 例 |
|---|---|---|
| `charged` | R04 §3：行动前骰子数为偶数则普通攻击视为重击 | "现在直接普攻，是否视为重击？" |
| `reaction` | R06 §2 附着转移表 + R06 §3.1 反应效果 | "对方出战角色现在受到 1 次火伤，会发生什么？"（无附着时问"先 X 后 Y"） |
| `turn` | R03 §3：对方已宣布结束时战斗行动后仍由我方行动 | "现在使用技能之后由谁行动？" |
| `end` | R03 §3、R01 §4.3 | "现在宣布回合结束，接下来会发生什么？" |
| `summon` | R07 §1：召唤物区最多 4 个 | "召唤物区还能再容纳几个新召唤物？" |

**知识按决策时的局面选取，不看题目**（与对局里的选取代码相同），所以它测的是"决策时注入的知识是否包含、并被用于该局面需要的规则"。

```bash
python -m bench.kb_situ build  --sets v1 v2 --name situ_d32                                  # 题库（已入库）
python -m bench.kb_situ render --name situ_d32 --profiles kbt-s0 kbt-s4 --tag kbt_situ_render  # 每个局面重放一次，缓存局面文本与各配置的知识
python -m bench.kb_situ eval   --name situ_d32 --render kbt_situ_render --tag kbt_situ_dev_r1 \
    --model deepseek-flash --kb none kbt-s0 kbt-s4 --split dev                                  # --mode reason：先写依据再作答（另用一个 --tag）
python -m bench.kb_situ report --name situ_d32 --runs kbt_situ_dev_r1 kbt_situ_dev_r2 --kb none kbt-s0 kbt-s4 --split dev --tag kbt_situ_dev
```

报告除正确率外还列"注入的知识里有没有该题所需的规则节"，用来区分"没给到"与"给了没用上"。

### 7.4 阶段报告与整局合并

```bash
python -m bench.kb_train unit-frequency --sets v1 --out configs/knowledge/unit_frequency_train.json   # 策略单元在 train 上的触发频次
python -m bench.kb_train stages --set v2 --split dev --runs kbt_dev_r1 kbt_dev_r2 \
    --subjects "llm:deepseek-flash" "llm:deepseek-flash#kb=kbt-s4,reply=reason_first" --tag kbt_lethal_dev
python -m bench.kb_train games --arm "none=ds_lite:llm:deepseek-flash;kbt_lite_r1:llm:deepseek-flash" \
    --arm "s5=kbt_lite_r1:llm:deepseek-flash#kb=kbt-s4,reply=reason_first" --tag kbt_lite
```

`stages` 按题合并多轮、配对比较并报告同配置两轮不一致的题数；`games` 把同一配置的多轮整局按格合并后逐格配对。

### 7.5 新增配置项

| 项 | 位置 | 默认 | 作用 |
|---|---|---|---|
| `rule_selection = "retrieve"` | 知识配置 | `kind_map` | 规则节按决策文本（合法选项 + 公开局面）做二元字 BM25 检索 |
| `rule_triggers = true` | 知识配置 | `false` | 可见局面满足条件时先放入对应规则节（`reps.kb_retrieval.RULE_TRIGGERS`） |
| `unit_frequency_file` / `max_unit_frequency` | 知识配置 | 不过滤 | 在 train 上触发过于频繁的策略单元不注入 |
| 自定义资料 `when:` | 资料头 | 无 | 只在指定局面（`SITUATIONS`，如 `lethal_window`）出现时注入 |
| `reply=reason_first` | LLM spec | `choice_first` | 回复格式先写依据（局面数字与规则）再给选项 |
| `rule_trigger_set = "d33"` | 知识配置 | `d32` | 触发集合（`reps.kb_retrieval.TRIGGER_SETS`）；`d33` 在 `d32` 之上加"对方未宣布结束且我方可宣布结束 → R01 §4.2" |
| `reply=checklist` | LLM spec | `choice_first` | 先写依据时按固定清单确认（能否本行动轮击倒或赢下、对方是否已结束、骰子与费用） |

默认值下旧配置的清单输出与提示词不变。

### 7.6 D33：保留数据与留出题型

D32 已经用过 `test` 与 `lite`，D33 另起新的保留数据，并在
`reports/review/2026-11_kb_d33_prereg.md` 里先登记候选与选择规则，再看 dev 结果：

- 场景集 v3（`--seed-offset 3000`，120 局源对局）整体作保留集，只在最终评估时用；
- 整局套件 `lite_fresh`（`configs/bench/lite_fresh.toml`）：结构与 `lite` 相同，`seed_offset = 200000`，种子与 `lite` 不重叠；
- 题库版本 `--version d33`（`bench.kb_situ build`）：`charged` 只在骰子 ≥ 3 时出；另加 5 种**留出题型**
  （`first_next`、`energy`、`hand_limit`、`dice_cap`、`tuning`，题目带 `heldout: true`），设计候选时不看它们；
- `bench.kb_situ report --subset designed|heldout` 分开报告原题型与留出题型。

```bash
python -m bench.scenarios build --name v3 --games 120 --workers 2 --seed-offset 3000 --agreement-per-seat 0 --no-quiz
python -m bench.kb_situ build --sets v3 --name situ_v3 --version d33
python -m bench.run --suite lite_fresh --tag kbt3_fresh_r1 --subjects "llm:deepseek-flash" \
    "llm:deepseek-flash#kb=kbt3-trig,reply=reason_first"
```

### 7.7 D34：模型对战与知识库版本

**成对模型对战**（`bench.mirror`）：一对 = 同一种子、同样两副牌、同样座位，受试者与对手各坐一次座位 0；
对分 0–2，胜率 = 对分均值 / 2。套件锁文件 `configs/bench/mirror_{aa,train,dev,test}.lock.json`
（赛事阵容 v6.2 / v6.3，按牌组代码哈希分到 train / dev / test，种子 7400001 起）。单元格的对手写作 `<rival>`，
由 `bench.run --rival SPEC` 填入；对手的花费计入 `--max-calls` / `--max-cost`。`--trace` 保存双方每个决策的提示、回复与知识（只用于 train）。

```bash
python -m bench.run --suite configs/bench/mirror_dev.lock.json --replicates 80 \
    --subjects "llm:deepseek-flash#kb=kbt3-trig,reply=reason_first" --rival "llm:deepseek-flash#reply=reason_first" --tag T
python -m bench.mirror report --tag T --out T                     # 成对汇总
python -m bench.mirror_digest --tag TRAIN_TAG --out digest.md     # 只对 train：首次分歧 + 逐决策摘要
python -m bench.run --suite anchor --subjects SPEC --tag T        # 外部锚点：2 副池牌组 vs 2 个脚本专家
```

**知识库版本**（`reps.kb_versions`，说明见 `configs/knowledge/kb_versions/README.md`）：v1.0 只读；
`python -m reps.kb_versions build <版本>` 在 v1.0 副本上应用补丁链、用知识库自带工具重建并校验，结果在 `$GITCG_DATA_DIR/kb_versions/`。
知识配置用 `kb_version = "<版本>"` 选择；未构建的版本直接报错，不会回退到 v1.0。
策略层版本的检测器写在 `reps/knowledge.py` 的 `_VERSION_DETECTORS`，只对该版本生效。
`bench.kb_train unit-frequency --kb-version 1.0-s1` 按版本的检测器表重算频次。

**引擎核对**：`python -m bench.kb_engine_check --set v2 --split train --out NAME` 在真实局面上分叉执行，
核对充能、先手、调和、重击、信息划分与上限。

| 新增配置项 | 位置 | 默认 | 作用 |
|---|---|---|---|
| `kb_version` | 知识配置 | `""`（v1.0） | 选择知识库版本 |
| `--rival` / `--trace` | `bench.run` | — | 模型对战的对手；保存决策记录 |

### 7.8 D35：重放、分歧点评测与教师材料

带记录的 train 对局（`--trace`）可以逐决策**精确重放**（`bench.forks`；D34 的 40 局 40/40 重放到相同胜者），
也可以在任意决策处**分叉**：打一个指定选项，再由同一续打策略替双方打完。

```bash
# 决策模式（不调用模型）：知识方与无知识方各自的出现率，带例子
python -m bench.mirror_mine --tag d34_ab_v10_train --out d35_mine_v10_train
# 分歧点：在 train 局面上问各策略会怎么选（每局面每策略 1 次调用）
python -m bench.divergence probe --games d34_ab_v10_train --tag T --per-seat 8 \
    --policy none="llm:deepseek-flash#reply=reason_first" none2="llm:deepseek-flash#reply=reason_first" \
    v10="llm:deepseek-flash#kb=kbt3-trig,reply=reason_first" --max-cost 3 --until 21:55
# 续打两个分支：脚本（免费）或模型；--max-cost 按调用记录实时计（含在途），--until 到点不再提交
python -m bench.divergence rollout --tag T --compare v10:none none2:none --continuation heuristic
python -m bench.divergence rollout --tag T --compare v10:none --continuation "llm:deepseek-flash#reply=reason_first" \
    --max-dps 60 --reps 2 --first-reps-only 30 --max-cost 10 --until 21:58
python -m bench.divergence report --tag T --compare none2:none v10:none
```

定向机制核对：`probe --select-units S02-P7 S01-P9 --select-version 1.0-s1` 只取这些单元触发的局面；
`python -m bench.mirror_mine --tag <probe tag> --behaviour --out NAME` 按策略统计同一批局面上的决策模式与行动类别。
D35 结论：分歧点**续打**被噪声淹没，不作门禁初筛；按局面提问与定向核对便宜而有用（见 `reports/review/2026-11_kb_d35.md`）。

`none2`（与 `none` 完全相同的配置）是空白对照：温度 0 下模型对同一局面的回答也不完全一致，
`none2:none` 的分歧点给出"纯噪声"的分歧率与分支差分布。分歧点只取 train 局面（工具拒绝读 dev / test 对局）。

| 新增项 | 位置 | 默认 | 作用 |
|---|---|---|---|
| `elements=1` | LLM spec | 关 | 状态文本在角色名后标出元素（`甘雨［冰］`）；默认文本不变 |
| `--elements` | `bench.kb_situ render` | 关 | 情境题的状态文本同上（另起渲染 tag） |
| `--max-cost` 实时计 | `bench.run` | — | 以调用记录计花费（含在途对局）；超过 `--hard-cost-factor`（默认 1.2）倍时结束在途对局，下次续跑重打 |
| 题库 `situ_v2d33` | `configs/bench/kb_situ/` | — | v2 局面上的 `d33` 题型（含充能、先手、调和、手牌与骰子上限），替代已饱和的 D32 题库做规则层守门 |

### 7.9 D36：自然分歧点、换牌统计与平局结构

镜像对局的两局种子与座位牌组相同，所以两局一直相同，直到两种策略第一次选得不一样（**自然分歧点**，免费、精确）。
D36 train 30 对里有 28 对第一次不同就在起手换牌。

```bash
# 每对的第一个不同决策，按决策类型计数（只读 train 对局）
python -m bench.mirror_mine --tag d36_train_v10 --natural --out d36_natural_train
# 起手换牌：每一方换掉专属牌（"才能加入牌组"）、秘传、至少一张核心牌的比例
python -m bench.mirror_mine --tag d36_train_v10 --mulligan --out d36_mull_train
# 同一批换牌局面上各策略的换牌（先用 bench.divergence probe --select-units S05-P1 取局面）
python -m bench.mirror_mine --tag d36_train_v10 --mulligan --probe <probe tag> --out NAME
```

**平局结构**：在 `mirror_*` 套件上，约 60–70% 的对是"同一座位两局都赢"（对分 1，平局），由座位与牌组决定。
平局比例为 t 时，胜率最多是 0.5 + (1 − t)/2；t ≈ 0.7 时上限约 0.65。
所以镜像胜率的目标若高于这个上限，知识方必须在座位或牌组不利的局里翻盘，单靠改变某类决策的频率不够（见 `reports/review/2026-11_kb_d36.md`）。

| 新增项 | 位置 | 作用 |
|---|---|---|
| `--natural` / `--mulligan [--probe TAG]` | `bench.mirror_mine` | 自然分歧点；起手换牌统计（只读 train） |
| 套件 `mirror_test150` | `configs/bench/mirror_test150.lock.json` | test 牌组 150 对（前 100 对与 `mirror_test` 相同）；D36 最终 test 已用掉，再比较需新种子 |
| `v1.0-s2`、`v1.0-s3` | `configs/knowledge/kb_versions/` | D36 的策略层补丁版本（未入库）；配置 `kbt6-r1` / `kbt6-r2` / `kbt6-r3` |

### 7.10 D37：多维指标、派生事实、角色卡

**逐局公开终局**：`bench.play` 的每行带 `outcome`，按座位记录存活数、剩余生命、生命上限、被击倒数、受到的伤害。
数据来自对局结束时的公开状态与公开伤害事件，与双方提示无关。

```bash
# 任意镜像轮次的多维指标（W 胜负 / H 生命差 / K 击倒差 / D 伤害占比；对分、单侧符号检验、CI）
python -m bench.metrics report --tag T --out NAME
# 胜利优先、平局按 K→H→D 依次判定，并给出胜率区间（理论上下界、单因素、因素挑选的上下限）；"a,b" 合并分阶段的轮次
python -m bench.metrics tiebreak --tag T1 S1,S2 [--replays data/bench/<facts_check>/replays.jsonl --rep-ranges 0-19 20-49] --out NAME
# 指标校准（脚本策略，零模型费用）：已知差距 + A/A
python -m bench.run --suite mirror_train300 --subjects heuristic --rival noisy:0.1:heuristic --rep-from 60 --replicates 180 --tag T1
python -m bench.metrics validate --known T1 T2 --null T3 --out NAME
# 同牌组格式（双方同一副牌，只换座位）
python -m bench.mirror build --split train --pairs 300 --name mirror_train300same --same-deck
# 预演核对与教师计数（重放 train 对局）；按预演定向取局面做机制核对
python -m bench.facts_check --tag d36_train_v10 d34_ab_v10_train --out d37_facts_train
python -m bench.divergence probe --games d36_train_v10 --tag T --per-seat 4 --select-facts --policy base=... v11=...
python -m bench.facts_check --probe T --out NAME
```

| 新增项 | 位置 | 默认 | 作用 |
|---|---|---|---|
| `facts=1` | LLM spec | 关 | 行动决策前给出派生事实：引擎对本方每个技能选项的预演（伤害、反应、生命变化、击倒），能击倒的选项、伤害最高的选项，对方可放爆发、本方低血量（`reps.facts`） |
| `cards=1` | LLM spec | 关 | 提示最前面给出双方 6 个角色的技能卡（卡牌数据原文），整局不变，便于前缀缓存（`reps.dossier`） |
| `noisy:<ε>:<spec>` | 策略 spec | — | 以概率 ε 均匀随机选合法选项，否则交给 `<spec>`；已知强弱的校准对手 |
| `--same-deck` | `bench.mirror build` | 关 | 一对的两个座位用同一副牌 |
| `--select-facts` | `bench.divergence probe` | 关 | 只取预演能区分选项的行动局面（击倒局面优先），每行带标签 |
| 锁文件 `mirror_train300`、`mirror_train300same`、`mirror_dev200` | `configs/bench/` | — | 与原锁文件同一种子块、前缀相同；D37 校准用 train 第 60–179 对，dev 用第 100–149 对 |

**信息合法性**：
- 预演来自引擎发给本方的行动请求（与官方客户端的伤害预览同源），在源头只保留技能对角色的伤害、治疗、附着。
- `tests/test_facts.py` 的引擎泄漏测试：对方隐藏手牌不同而公开局面相同时，提示逐字相同。
