"""Digest model-vs-model *train* games for the teacher (D34; never run on dev / test).

For every pair of a traced run (``bench.run --trace``) it lines up the two games: the
same seed, decks and seats, the knowledge player in one seat each time. Until one
side's choice differs, both games are the same position by position, so the *first
divergence* is a position where the two players saw the same state and chose
differently -- the cleanest place to see what the knowledge changed. After it, each
game is summarised decision by decision for the knowledge side (choice, reason, the
knowledge items it was shown).

    python -m bench.mirror_digest --tag d34_ab_v10_train --out data/bench/d34_ab_v10_train/digest.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from common.paths import data_dir

SPLITS_ALLOWED = ("mirror-train",)


def _load_traces(tag: str, subject: str) -> dict[str, dict[str, Any]]:
    slug = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:10]
    out = {}
    for path in sorted((data_dir("bench", tag) / "traces" / slug).glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        out[f"{payload['cell']['seed']}|{payload['cell']['side']}"] = payload
    return out


def _seat_sequences(game: Mapping[str, Any]) -> dict[int, list[dict[str, Any]]]:
    """Decisions by seat, from the subject's and rival's traces of one game."""
    side = int(game["cell"]["side"])
    return {side: game["subject_traces"], 1 - side: game["rival_traces"]}


def first_divergence(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any] | None:
    """``a``: knowledge player at seat 0; ``b``: knowledge player at seat 1 (same seed, decks)."""
    sa, sb = _seat_sequences(a), _seat_sequences(b)
    merged = []
    for seat in (0, 1):
        for i, (x, y) in enumerate(zip(sa[seat], sb[seat])):
            merged.append((min(x["step_index"], y["step_index"]), seat, i, x, y))
    for _, seat, i, x, y in sorted(merged, key=lambda t: (t[0], t[1])):
        if x["final_text"] != y["final_text"]:
            kb_is_a = seat == 0                     # in game a the knowledge player holds seat 0
            kb, plain = (x, y) if kb_is_a else (y, x)
            return {"seat": seat, "decision": i, "kb": kb, "plain": plain}
    return None


def _ids(trace: Mapping[str, Any]) -> list[str]:
    knowledge = trace.get("knowledge") or {}
    return [str(i["id"]) for i in knowledge.get("items", [])] or list(knowledge.get("ids", []) or [])


def _short(text: str | None, n: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def _state_head(prompt: str | None, n: int = 900) -> str:
    if not prompt:
        return ""
    head = prompt.split("以下是可参考的知识", 1)[0]
    return _short(head, n)


def digest(tag: str, *, max_decisions: int = 60) -> str:
    meta = json.loads((data_dir("bench", tag) / "meta.json").read_text(encoding="utf-8"))
    subject = meta["subjects"][0]
    traces = _load_traces(tag, subject)
    seeds = sorted({k.split("|")[0] for k in traces})
    lines = [f"# 训练对局摘要：{tag}", "", f"受试者（知识方）`{subject}`；对手 `{meta.get('rival')}`。", ""]
    for seed in seeds:
        a, b = traces.get(f"{seed}|0"), traces.get(f"{seed}|1")
        if a is None or b is None:
            continue
        if not str(a["cell"].get("group", "")).startswith(SPLITS_ALLOWED):
            raise SystemExit("digest is for train games only")
        score = (a["score"] or 0) + (b["score"] or 0)
        lines += [f"## 种子 {seed}：知识方对分 {score:g}（座位 0 局 {a['score']}，座位 1 局 {b['score']}）；"
                  f"座位 0 牌组 {a['cell']['deck']}，座位 1 牌组 {a['cell']['opponent_deck']}", ""]
        div = first_divergence(a, b)
        if div is None:
            lines += ["两局完全相同。", ""]
        else:
            kb, plain = div["kb"], div["plain"]
            lines += [f"**首次分歧**（座位 {div['seat']}，该座位第 {div['decision']} 个决策，{kb['request_type']}）",
                      f"- 局面：{_state_head(kb.get('prompt'))}",
                      f"- 知识方：{kb['final_text']} ——理由：{_short(kb.get('reason'), 200)}；给到的知识：{', '.join(_ids(kb))}",
                      f"- 无知识方：{plain['final_text']} ——理由：{_short(plain.get('reason'), 200)}", ""]
        for game, label in ((a, "座位 0"), (b, "座位 1")):
            kbt = game["subject_traces"]
            lines.append(f"### 知识方在{label}（{'胜' if game['score'] == 1 else '负' if game['score'] == 0 else '平'}，{game['rounds']} 回合）")
            for t in kbt[:max_decisions]:
                if t["source"] == "forced":
                    continue
                ids = ",".join(_ids(t))
                lines.append(f"- #{t['step_index']} {t['request_type']}: {_short(t['final_text'], 60)} | {_short(t.get('reason'), 110)} | {ids}")
            lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-decisions", type=int, default=60)
    args = parser.parse_args(argv)
    text = digest(args.tag, max_decisions=args.max_decisions)
    Path(args.out).write_text(text, encoding="utf-8")
    print(f"{args.out}: {len(text)} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
