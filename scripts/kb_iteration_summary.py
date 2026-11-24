"""KB iteration (D31-D37) on fixed item sets: every stage vs no knowledge, same items, same rounds.

Reads existing data only (no model calls). Stages are the knowledge / access configurations that were
proposed in turn (D32 S0-S5, D33 C2, D34 rule cards, D36 rounds, D37 facts + cards); each row is paired
against the no-knowledge arm (or the incumbent) of the same run, so items and rounds match.

    python -m scripts.kb_iteration_summary --out kb_iteration_stages
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from collections import defaultdict
from typing import Any, Sequence

from bench.metrics import sign_p_one_sided
from common.paths import REPO_ROOT

DATA = REPO_ROOT / "data" / "bench"
DS = "llm:deepseek-flash"


def situ(tags: Sequence[str], mode: str) -> list[dict[str, dict[str, bool]]]:
    runs = []
    for tag in tags:
        d: dict[str, dict[str, bool]] = defaultdict(dict)
        for line in (DATA / tag / "situ.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["model"] == "deepseek-flash" and (r.get("mode") or "answer") == mode and r.get("ok"):
                d[r["kb"]][r["id"]] = bool(r["correct"])
        runs.append(d)
    return runs


def lethal(tags: Sequence[str]) -> list[dict[str, dict[str, bool]]]:
    runs = []
    for tag in tags:
        d: dict[str, dict[str, bool]] = defaultdict(dict)
        for line in (DATA / tag / "scenarios.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("kind") == "lethal":
                value = r.get("correct", r.get("converted"))
                if value is not None:
                    d[r["subject"]][r["id"]] = bool(value)
        runs.append(d)
    return runs


def compare(runs: Sequence[dict[str, dict[str, bool]]], base: str, arm: str) -> dict[str, Any]:
    ids = set.intersection(*[set(r.get(base, {})) & set(r.get(arm, {})) for r in runs])
    if not ids:
        return {"n": 0}
    mean = lambda k, i: sum(r[k][i] for r in runs) / len(runs)          # noqa: E731
    better = sum(mean(arm, i) > mean(base, i) for i in ids)
    worse = sum(mean(arm, i) < mean(base, i) for i in ids)
    acc_arm = sum(mean(arm, i) for i in ids) / len(ids)
    acc_base = sum(mean(base, i) for i in ids) / len(ids)
    return {"n": len(ids), "rounds": len(runs), "base": round(acc_base, 3), "arm": round(acc_arm, 3),
            "delta": round(acc_arm - acc_base, 3), "better": better, "worse": worse,
            "p_one": round(sign_p_one_sided(better, worse), 4)}


# (set, stage, run tags, mode / kind, baseline arm, stage arm)
STAGES = [
    ("情境题 dev 245，先写依据", "S0 原接入（D32 起点）", ("kbt_situ_dev_reason_r1", "kbt_situ_dev_reason_r2"), "reason", "none", "kbt-s0"),
    ("情境题 dev 245，先写依据", "S5 = S4 按局面触发规则节 + 先写依据（采纳）", ("kbt_situ_dev_reason_r1", "kbt_situ_dev_reason_r2"), "reason", "none", "kbt-s4"),
    ("情境题 dev 245，先写依据", "D33 C1 只留规则（被拒）", ("kbt_situ_dev_reason_r1", "kbt_situ_dev_reason_r2"), "reason", "none", "kbt3-lean"),
    ("情境题 dev 245，先写依据", "D33 C2 `kbt3-trig`（采纳）", ("kbt_situ_dev_reason_r1", "kbt_situ_dev_reason_r2"), "reason", "none", "kbt3-trig"),
    ("情境题 dev 245，直接作答", "S0 原接入", ("kbt_situ_dev_r1", "kbt_situ_dev_r2"), "answer", "none", "kbt-s0"),
    ("情境题 dev 245，直接作答", "S1 BM25 检索（被拒）", ("kbt_situ_dev_r1", "kbt_situ_dev_r2"), "answer", "none", "kbt-s1"),
    ("情境题 dev 245，直接作答", "S2 剪策略单元（被拒）", ("kbt_situ_dev_r1", "kbt_situ_dev_r2"), "answer", "none", "kbt-s2"),
    ("情境题 dev 245，直接作答", "S3 斩杀定向资料（被拒）", ("kbt_situ_dev_r1", "kbt_situ_dev_r2"), "answer", "none", "kbt-s3"),
    ("情境题 dev 245，直接作答", "S4 按局面触发规则节（采纳）", ("kbt_situ_dev_r1", "kbt_situ_dev_r2"), "answer", "none", "kbt-s4"),
    ("情境题 test 260，先写依据（只跑一次）", "S0 原接入", ("kbt_situ_test_reason_r1", "kbt_situ_test_reason_r2"), "reason", "none", "kbt-s0"),
    ("情境题 test 260，先写依据（只跑一次）", "S5（D32 最终）", ("kbt_situ_test_reason_r1", "kbt_situ_test_reason_r2"), "reason", "none", "kbt-s4"),
    ("情境题 test 260，直接作答（只跑一次）", "S0 原接入", ("kbt_situ_test_r1", "kbt_situ_test_r2"), "answer", "none", "kbt-s0"),
    ("情境题 test 260，直接作答（只跑一次）", "S4", ("kbt_situ_test_r1", "kbt_situ_test_r2"), "answer", "none", "kbt-s4"),
    ("情境题 v3 新数据 1151，先写依据（只跑一次）", "D33 C2 `kbt3-trig`", ("kbt3_v3_situ_reason_r1", "kbt3_v3_situ_reason_r2"), "reason", "none", "kbt3-trig"),
    ("情境题 dev 245，对 C2（1 轮）", "D34 规则卡 v1.1（被拒）", ("kbt4_situ_dev_reason_r1",), "reason", "kbt3-trig", "kbt4-v11"),
    ("情境题 dev 245，对 C2（1 轮）", "D34 规则卡 v1.2（被拒）", ("kbt4_situ_dev_reason_r1",), "reason", "kbt3-trig", "kbt4-v12"),
]
R = ",reply=reason_first"
LETHAL = [
    ("斩杀 dev 64（2 轮）", "S0 原接入", ("kbt_dev_r1", "kbt_dev_r2"), DS, f"{DS}#kb=kbt-s0"),
    ("斩杀 dev 64（2 轮）", "只改回复格式、无知识", ("kbt_dev_r1", "kbt_dev_r2"), DS, f"{DS}#reply=reason_first"),
    ("斩杀 dev 64（2 轮）", "S4 无先写依据", ("kbt_dev_r1", "kbt_dev_r2"), DS, f"{DS}#kb=kbt-s4"),
    ("斩杀 dev 64（2 轮）", "S5 = S4 + 先写依据（采纳）", ("kbt_dev_r1", "kbt_dev_r2"), DS, f"{DS}#kb=kbt-s4{R}"),
    ("斩杀 dev 64（2 轮）", "D33 C2 `kbt3-trig`（采纳）", ("kbt_dev_r1", "kbt_dev_r2"), DS, f"{DS}#kb=kbt3-trig{R}"),
    ("斩杀 test 70（只跑一次，2 轮）", "S0 原接入", ("kbt_test_r1", "kbt_test_r2"), DS, f"{DS}#kb=kbt-s0"),
    ("斩杀 test 70（只跑一次，2 轮）", "S5（D32 最终）", ("kbt_test_r1", "kbt_test_r2"), DS, f"{DS}#kb=kbt-s4{R}"),
    ("斩杀 v3 新数据 141（续打转化，2 轮）", "D33 C2 `kbt3-trig`", ("kbt3_v3_lethal_r1", "kbt3_v3_lethal_r2"), DS, f"{DS}#kb=kbt3-trig{R}"),
    ("斩杀 dev 64，对 C2（1 轮）", "D34 策略层 v1.0-s1（被拒）", ("kbt4_lethal_dev_r1",), f"{DS}#kb=kbt3-trig{R}", f"{DS}#kb=kbt4-s1{R}"),
    ("斩杀 dev 64，对 C2（1 轮）", "D36 观测层 `elements=1`（采纳）", ("kbt5_lethal_dev_r1",), f"{DS}#kb=kbt3-trig{R}", f"{DS}#kb=kbt3-trig{R},elements=1"),
    ("斩杀 dev 64，对 C2（1 轮）", "D36 R1 v1.0-s2（被拒）", ("kbt5_lethal_dev_r1",), f"{DS}#kb=kbt3-trig{R}", f"{DS}#kb=kbt6-r1{R},elements=1"),
    ("斩杀 dev 64，对 C2（1 轮）", "D36 R2（被拒）", ("kbt5_lethal_dev_r1",), f"{DS}#kb=kbt3-trig{R}", f"{DS}#kb=kbt6-r2{R},elements=1"),
    ("斩杀 dev 64，对 C2（1 轮）", "D36 R3 v1.0-s3（被拒）", ("kbt5_lethal_dev_r1",), f"{DS}#kb=kbt3-trig{R}", f"{DS}#kb=kbt6-r3{R},elements=1"),
    ("斩杀 dev 64，对 C2（1 轮）", "D37 派生事实 + 角色卡（未采纳）", ("kbt5_lethal_dev_r1",), f"{DS}#kb=kbt3-trig{R}", f"{DS}#kb=kbt3-trig{R},elements=1,facts=1,cards=1"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    rows = []
    for item_set, stage, tags, mode, base, arm in STAGES:
        rows.append({"set": item_set, "stage": stage, "base": base, "arm": arm, **compare(situ(tags, mode), base, arm)})
    for item_set, stage, tags, base, arm in LETHAL:
        rows.append({"set": item_set, "stage": stage, "base": base, "arm": arm, **compare(lethal(tags), base, arm)})
    out = REPO_ROOT / "reports" / "bench"
    (out / f"{args.out}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    lines = ["# 知识库迭代：固定题集上的逐阶段结果（DeepSeek-V4.1-Flash）", "",
             f"生成于 {_dt.datetime.now().isoformat(timespec='seconds')}，`python -m scripts.kb_iteration_summary --out {args.out}`。只读已有数据。", "",
             "每行与同一次运行里的基线（不带知识库，或当时采用的版本）按题配对：同一批题、同样轮数，每题取各轮均值。单侧符号检验，H1：该阶段更好。", "",
             "| 题集 | 阶段 | 题数 | 基线 | 该阶段 | 差 | 好 / 差 | 单侧 p |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if not r["n"]:
            continue
        lines.append(f"| {r['set']} | {r['stage']} | {r['n']} | {r['base']:.3f} | {r['arm']:.3f} | {r['delta']:+.3f} | "
                     f"{r['better']} / {r['worse']} | {r['p_one']:.4f} |")
    lines += ["", "基线：情境题与斩杀的前几组是不带知识库；标\"对 C2\"的组是当时采用的 `kbt3-trig`。"
              "斩杀 dev / test 计\"第一步是否在致胜路线上\"，v3 计\"续打本轮并在对方行动前获胜\"。模拟器内结果，不进强度验收。"]
    (out / f"{args.out}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
