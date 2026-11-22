# 规则层修改的引擎核对（D34）

场景集 `v2` 的 `train` 部分，24 局源对局；生成于 2026-11-22T13:15:24。
每项在真实局面上分叉执行，或读取引擎状态 / 配置。

| 核对项 | 规则卡中的说法 | 观测数 | 与说法一致 |
|---|---|---|---|
| 充能 | 普通攻击、元素战技后 +1，不超过上限 | 81 | 66（其中已满时 13/23；超过上限 10 次） |
| 下回合先手 | 先宣布结束的一方下回合先手 | 141 | 141 |
| 元素调和 | 骰子数不变、恰好 1 个骰子改变、仍由我方行动 | 105 | 103 |
| 重击 | 行动前骰子数为偶数时普通攻击视为重击（引擎 `canCharged`） | 144 | 144 |
| 信息划分 | 对方手牌内容、骰子元素面、双方牌堆顺序不可见；骰子数量、场面可见（本方观测 `notification.state`） | 144 | 144 |
| 上限 | 骰子 16、手牌 10、召唤物 4、支援 4 | 引擎配置 | 一致 |

## 不一致的观测

| 核对项 | 详情 |
|---|---|
| energy | {"source": 0, "seat": 0, "ordinal": 16, "skill_kind": "普通攻击", "character": 1315, "before": 3, "max": 3, "after": 4, "expected": 3, "capped_case": true, "never_above_max": false} |
| energy | {"source": 0, "seat": 0, "ordinal": 42, "skill_kind": "普通攻击", "character": 1315, "before": 6, "max": 3, "after": 6, "expected": 3, "capped_case": true, "never_above_max": false} |
| energy | {"source": 4, "seat": 0, "ordinal": 17, "skill_kind": "普通攻击", "character": 1315, "before": 3, "max": 3, "after": 4, "expected": 3, "capped_case": true, "never_above_max": false} |
| energy | {"source": 6, "seat": 0, "ordinal": 26, "skill_kind": "普通攻击", "character": 1116, "before": 0, "max": 7, "after": 0, "expected": 1, "capped_case": false, "never_above_max": true} |
| energy | {"source": 7, "seat": 0, "ordinal": 17, "skill_kind": "普通攻击", "character": 1315, "before": 5, "max": 3, "after": 6, "expected": 3, "capped_case": true, "never_above_max": false} |
| energy | {"source": 8, "seat": 1, "ordinal": 17, "skill_kind": "普通攻击", "character": 1315, "before": 3, "max": 3, "after": 4, "expected": 3, "capped_case": true, "never_above_max": false} |
| energy | {"source": 9, "seat": 0, "ordinal": 25, "skill_kind": "普通攻击", "character": 1315, "before": 5, "max": 3, "after": 6, "expected": 3, "capped_case": true, "never_above_max": false} |
| energy | {"source": 12, "seat": 1, "ordinal": 47, "skill_kind": "普通攻击", "character": 1116, "before": 0, "max": 7, "after": 0, "expected": 1, "capped_case": false, "never_above_max": true} |
| energy | {"source": 14, "seat": 1, "ordinal": 38, "skill_kind": "普通攻击", "character": 1315, "before": 6, "max": 3, "after": 6, "expected": 3, "capped_case": true, "never_above_max": false} |
| energy | {"source": 15, "seat": 1, "ordinal": 19, "skill_kind": "普通攻击", "character": 1116, "before": 3, "max": 7, "after": 3, "expected": 4, "capped_case": false, "never_above_max": true} |
| tuning | {"source": 15, "seat": 1, "ordinal": 19, "same_seat_next": true, "dice_before": 8, "dice_after": 9, "dice_changed": 1} |
| tuning | {"source": 15, "seat": 1, "ordinal": 35, "same_seat_next": true, "dice_before": 2, "dice_after": 3, "dice_changed": 1} |
| energy | {"source": 16, "seat": 0, "ordinal": 34, "skill_kind": "普通攻击", "character": 1315, "before": 6, "max": 3, "after": 6, "expected": 3, "capped_case": true, "never_above_max": false} |
| energy | {"source": 16, "seat": 0, "ordinal": 49, "skill_kind": "普通攻击", "character": 1315, "before": 6, "max": 3, "after": 6, "expected": 3, "capped_case": true, "never_above_max": false} |
| energy | {"source": 20, "seat": 1, "ordinal": 22, "skill_kind": "普通攻击", "character": 6605, "before": 4, "max": 7, "after": 2, "expected": 5, "capped_case": false, "never_above_max": true} |
| energy | {"source": 21, "seat": 1, "ordinal": 39, "skill_kind": "普通攻击", "character": 1315, "before": 6, "max": 3, "after": 6, "expected": 3, "capped_case": true, "never_above_max": false} |
| energy | {"source": 22, "seat": 0, "ordinal": 26, "skill_kind": "普通攻击", "character": 1116, "before": 0, "max": 7, "after": 0, "expected": 1, "capped_case": false, "never_above_max": true} |
