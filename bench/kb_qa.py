"""Knowledge-base QA: can a model answer rules questions, and does the local KB help?

The bank (``configs/bench/kb_qa/<name>.json``) holds multiple-choice questions whose
answer is stated in one KB rule section; every item carries a verbatim ``evidence``
string that must occur in that section (``validate``). Gold = the KB's own text, so
this measures the *usability* of the KB, not whether the KB matches the official
client (the KB's own cross-checks cover that).

Each question is asked under several **conditions**, so the effects separate:

``closed``  question only: what the model already knows.
``search``  top-k sections from ``KnowledgeBase.search`` (the KB's built-in retriever,
            whitespace terms) for the question text -- what the current code path finds.
``bm25``    top-k sections from a character-bigram BM25 index over heading + text: a
            plain retriever that works on Chinese without word segmentation.
``oracle``  the gold section itself: the upper bound of what the KB text can do.

Retrieval quality is reported separately (hit@k of the gold section, no model calls).

    python -m bench.kb_qa check  --bank rules_v1
    python -m bench.kb_qa retrieval --bank rules_v1
    python -m bench.kb_qa eval --bank rules_v1 --profiles deepseek-flash --tag kbqa_v1
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from common.paths import REPO_ROOT, data_dir, ensure_dir, reports_dir

CONDITIONS = ("closed", "search", "bm25", "oracle")
BANK_DIR = REPO_ROOT / "configs" / "bench" / "kb_qa"
SECTION_CHARS = 1600          # per retrieved section shown to the model
TOP_K = 3

SYSTEM = (
    "你是七圣召唤（Genius Invokation TCG）规则助手。回答一道单选题。"
    "如果提供了资料，资料来自本地知识库的规则章节，可能与题目无关；资料与你的记忆冲突时以资料为准。"
    "只输出 JSON：{\"answer\": \"A\"}，answer 取 A/B/C/D 之一。"
)


# --------------------------------------------------------------------------- #
# bank
# --------------------------------------------------------------------------- #
def load_bank(name: str) -> dict[str, Any]:
    path = Path(name) if name.endswith(".json") else BANK_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def validate(bank: Mapping[str, Any], kb) -> list[str]:
    """Problems with the bank against ``kb`` (empty list = valid)."""
    problems = []
    seen = set()
    for item in bank["items"]:
        qid = item["id"]
        if qid in seen:
            problems.append(f"{qid}: duplicate id")
        seen.add(qid)
        if item["ref"] not in kb.rules:
            problems.append(f"{qid}: unknown section {item['ref']!r}")
        elif item["evidence"] not in kb.rules[item["ref"]].text:
            problems.append(f"{qid}: evidence not found verbatim in {item['ref']}")
        if set(item["options"]) != {"A", "B", "C", "D"} or item["answer"] not in item["options"]:
            problems.append(f"{qid}: options must be A-D and contain the answer")
        if len(set(item["options"].values())) != 4:
            problems.append(f"{qid}: duplicate option text")
    return problems


# --------------------------------------------------------------------------- #
# retrievers
# --------------------------------------------------------------------------- #
_CJK_OR_WORD = re.compile(r"[一-鿿]|[A-Za-z0-9]+")


def _bigrams(text: str) -> list[str]:
    """Character bigrams over CJK runs plus ASCII words; punctuation and markup dropped."""
    tokens = _CJK_OR_WORD.findall(text)
    grams: list[str] = []
    for a, b in zip(tokens, tokens[1:]):
        if len(a) == 1 and len(b) == 1 and "一" <= a <= "鿿" and "一" <= b <= "鿿":
            grams.append(a + b)
    grams.extend(t.lower() for t in tokens if len(t) > 1)
    return grams


class BM25:
    """Okapi BM25 over KB rule sections (heading + text), character bigrams."""

    def __init__(self, sections: Sequence[Any], k1: float = 1.5, b: float = 0.75) -> None:
        self.refs = [s.ref for s in sections]
        self.docs = [Counter(_bigrams(f"{s.heading} {s.heading} {s.text}")) for s in sections]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = sum(self.lengths) / max(1, len(self.lengths))
        df: Counter = Counter()
        for doc in self.docs:
            df.update(doc.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.k1, self.b = k1, b

    def rank(self, query: str, k: int = TOP_K) -> list[str]:
        terms = Counter(_bigrams(query))
        scores = []
        for i, doc in enumerate(self.docs):
            score = 0.0
            for term in terms:
                tf = doc.get(term, 0)
                if tf:
                    norm = tf + self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avg)
                    score += self.idf[term] * tf * (self.k1 + 1) / norm
            if score > 0:
                scores.append((-score, i))
        return [self.refs[i] for _s, i in sorted(scores)[:k]]


def retrieve(condition: str, item: Mapping[str, Any], kb, bm25: BM25 | None, k: int = TOP_K) -> list[str]:
    if condition == "closed":
        return []
    if condition == "oracle":
        return [item["ref"]]
    if condition == "search":
        return [x.ref for x in kb.search(item["question"], limit=k * 4) if hasattr(x, "ref")][:k]
    if condition == "bm25":
        assert bm25 is not None
        return bm25.rank(item["question"], k)
    raise ValueError(f"unknown condition {condition!r}")


def retrieval_table(bank: Mapping[str, Any], kb, ks: Sequence[int] = (1, 3, 5)) -> dict[str, Any]:
    """hit@k of the gold section for the two real retrievers (no model calls)."""
    bm25 = BM25(list(kb.rules.values()))
    out: dict[str, Any] = {}
    for name in ("search", "bm25"):
        ranked = {}
        for item in bank["items"]:
            if name == "search":
                ranked[item["id"]] = [x.ref for x in kb.search(item["question"], limit=50) if hasattr(x, "ref")]
            else:
                ranked[item["id"]] = bm25.rank(item["question"], 50)
        n = len(ranked)
        out[name] = {
            "empty": sum(1 for r in ranked.values() if not r),
            **{f"hit@{k}": round(sum(1 for item in bank["items"] if item["ref"] in ranked[item["id"]][:k]) / n, 4)
               for k in ks},
            "n": n,
        }
    return out


# --------------------------------------------------------------------------- #
# prompting and scoring
# --------------------------------------------------------------------------- #
def build_messages(item: Mapping[str, Any], refs: Sequence[str], kb) -> list[dict[str, str]]:
    lines = []
    if refs:
        lines.append("【资料】")
        for ref in refs:
            section = kb.rules[ref]
            text = section.text if len(section.text) <= SECTION_CHARS else section.text[:SECTION_CHARS] + "…"
            lines.append(f"〔{ref} {section.heading}〕\n{text}")
        lines.append("")
    lines.append(f"【题目】{item['question']}")
    for letter in "ABCD":
        lines.append(f"{letter}. {item['options'][letter]}")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines)}]


_LETTER = re.compile(r"\b([ABCD])\b")


def parse_answer(text: str | None) -> str | None:
    if not text:
        return None
    try:
        value = json.loads(text)
        if isinstance(value, dict) and str(value.get("answer", "")).strip().upper() in ("A", "B", "C", "D"):
            return str(value["answer"]).strip().upper()
    except ValueError:
        pass
    match = _LETTER.search(text.upper())
    return match.group(1) if match else None


def _ask(client, item, condition, refs, kb, profile_name) -> dict[str, Any]:
    started = time.time()
    result = client.complete(build_messages(item, refs, kb), want_json=True, tag=f"kbqa:{condition}")
    answer = parse_answer(result.text)
    return {
        "profile": profile_name, "condition": condition, "id": item["id"], "ref": item["ref"],
        "retrieved": list(refs), "gold_retrieved": item["ref"] in refs,
        "answer": answer, "correct": answer == item["answer"], "gold": item["answer"],
        "ok": result.ok, "error": result.error, "latency_seconds": round(time.time() - started, 3),
        "prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens,
        "reasoning_tokens": result.reasoning_tokens, "cached_tokens": result.cached_tokens,
        "cost": result.cost,
    }


def evaluate(bank_name: str, profiles: Sequence[str], *, tag: str, conditions: Sequence[str] = CONDITIONS,
             workers: int = 4, max_calls: int = 2000) -> dict[str, Any]:
    from common.llm_providers import build_client
    from reps.knowledge import KnowledgeBase

    bank = load_bank(bank_name)
    kb = KnowledgeBase.load()
    problems = validate(bank, kb)
    if problems:
        raise SystemExit("bank invalid:\n  " + "\n  ".join(problems))
    bm25 = BM25(list(kb.rules.values()))
    out_dir = Path(ensure_dir(data_dir("bench", tag)))
    rows_path = out_dir / "kb_qa.jsonl"
    done = set()
    if rows_path.exists():
        for line in rows_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("ok"):
                done.add((row["profile"], row["condition"], row["id"]))
    tasks = [(p, c, item) for p in profiles for c in conditions for item in bank["items"]
             if (p, c, item["id"]) not in done]
    if len(tasks) > max_calls:
        raise SystemExit(f"{len(tasks)} calls planned > --max-calls {max_calls}")
    clients = {p: build_client(p, call_log=out_dir / "calls.jsonl") for p in profiles}
    print(f"[kb_qa] {len(tasks)} calls ({len(done)} already done)", flush=True)

    def run(task):
        profile, condition, item = task
        return _ask(clients[profile], item, condition, retrieve(condition, item, kb, bm25), kb, profile)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool, rows_path.open("a", encoding="utf-8") as fh:
        for i, row in enumerate(pool.map(run, tasks), 1):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            if not row["ok"]:
                print(f"[kb_qa] {row['profile']} {row['condition']} {row['id']}: {row['error']}", flush=True)
            if i % 50 == 0:
                print(f"[kb_qa] {i}/{len(tasks)}", flush=True)
    return write_report(bank_name, tag)


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round((c - h) / d, 3), round((c + h) / d, 3))


def _mcnemar(b: int, c: int) -> float:
    """Exact two-sided McNemar (binomial on discordant pairs)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def summarise(rows: Iterable[Mapping[str, Any]], bank: Mapping[str, Any]) -> dict[str, Any]:
    latest: dict[tuple, Mapping[str, Any]] = {}
    for row in rows:
        latest[(row["profile"], row["condition"], row["id"])] = row
    by_pc: dict[tuple, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for (profile, condition, qid), row in latest.items():
        by_pc[(profile, condition)][qid] = row
    ids = [item["id"] for item in bank["items"]]
    chapter = {item["id"]: item["ref"].split()[0] for item in bank["items"]}
    table = []
    for (profile, condition), rows_by_id in sorted(by_pc.items(), key=lambda kv: (kv[0][0], CONDITIONS.index(kv[0][1]))):
        answered = [rows_by_id[q] for q in ids if q in rows_by_id]
        k = sum(1 for r in answered if r["correct"])
        n = len(answered)
        entry = {
            "profile": profile, "condition": condition, "n": n, "correct": k,
            "accuracy": round(k / n, 4) if n else None, "ci95": _wilson(k, n),
            "unparsed": sum(1 for r in answered if r["ok"] and r["answer"] is None),
            "errors": sum(1 for r in answered if not r["ok"]),
            "gold_in_context": sum(1 for r in answered if r["gold_retrieved"]),
            "acc_when_gold_in_context": None, "acc_when_gold_missing": None,
            "tokens_in_mean": round(sum(r["prompt_tokens"] for r in answered) / max(1, n), 1),
            "tokens_out_mean": round(sum(r["completion_tokens"] for r in answered) / max(1, n), 1),
            "latency_mean": round(sum(r["latency_seconds"] for r in answered) / max(1, n), 2),
            "by_chapter": {},
        }
        hit = [r for r in answered if r["gold_retrieved"]]
        miss = [r for r in answered if not r["gold_retrieved"]]
        if condition not in ("closed", "oracle"):
            entry["acc_when_gold_in_context"] = round(sum(r["correct"] for r in hit) / len(hit), 4) if hit else None
            entry["acc_when_gold_missing"] = round(sum(r["correct"] for r in miss) / len(miss), 4) if miss else None
        per = defaultdict(list)
        for r in answered:
            per[chapter[r["id"]]].append(r["correct"])
        entry["by_chapter"] = {ch: f"{sum(v)}/{len(v)}" for ch, v in sorted(per.items())}
        table.append(entry)
    # paired comparisons against closed-book, per profile
    pairs = []
    profiles = sorted({p for p, _c in by_pc})
    for profile in profiles:
        base = by_pc.get((profile, "closed"), {})
        for condition in CONDITIONS[1:]:
            other = by_pc.get((profile, condition), {})
            common = [q for q in ids if q in base and q in other]
            if not common:
                continue
            gained = sum(1 for q in common if other[q]["correct"] and not base[q]["correct"])
            lost = sum(1 for q in common if base[q]["correct"] and not other[q]["correct"])
            pairs.append({"profile": profile, "vs": "closed", "condition": condition, "n": len(common),
                          "gained": gained, "lost": lost, "p_mcnemar": round(_mcnemar(gained, lost), 4)})
    # items wrong even with the gold section in context
    stubborn = defaultdict(list)
    for (profile, condition), rows_by_id in by_pc.items():
        if condition == "oracle":
            for q, r in rows_by_id.items():
                if not r["correct"]:
                    stubborn[profile].append({"id": q, "answer": r["answer"], "gold": r["gold"]})
    return {"bank": bank["name"], "items": len(ids), "table": table, "paired": pairs,
            "oracle_misses": dict(stubborn)}


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [f"# KB QA `{report['tag']}`（题库 {report['bank']}，{report['items']} 题）", "",
             f"生成于 {report['generated']}；原始数据 `{report['raw']}`。", "",
             "## 检索质量（不调用模型）", "",
             "| 检索器 | 空结果 | hit@1 | hit@3 | hit@5 |", "|---|---|---|---|---|"]
    for name, r in report["retrieval"].items():
        lines.append(f"| {name} | {r['empty']}/{r['n']} | {r['hit@1']:.3f} | {r['hit@3']:.3f} | {r['hit@5']:.3f} |")
    lines += ["", "## 正确率", "",
              "| 模型档案 | 条件 | 正确 | 正确率 [95% CI] | 标准章节在资料中 | 命中时 / 未命中时正确率 | 无法解析 | 出错 | 输入 token | 输出 token | 延迟 s |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in report["table"]:
        cond = "—" if e["acc_when_gold_in_context"] is None and e["acc_when_gold_missing"] is None else \
            f"{e['acc_when_gold_in_context']} / {e['acc_when_gold_missing']}"
        lines.append(f"| {e['profile']} | {e['condition']} | {e['correct']}/{e['n']} | {e['accuracy']:.3f} "
                     f"[{e['ci95'][0]:.2f}, {e['ci95'][1]:.2f}] | {e['gold_in_context']} | {cond} | "
                     f"{e['unparsed']} | {e['errors']} | {e['tokens_in_mean']} | {e['tokens_out_mean']} | {e['latency_mean']} |")
    lines += ["", "## 与闭卷配对（精确 McNemar）", "", "| 模型档案 | 条件 | 题数 | 闭卷错→对 | 闭卷对→错 | p |", "|---|---|---|---|---|---|"]
    for p in report["paired"]:
        lines.append(f"| {p['profile']} | {p['condition']} | {p['n']} | {p['gained']} | {p['lost']} | {p['p_mcnemar']} |")
    lines += ["", "## 分章（正确 / 题数）", "", "| 模型档案 | 条件 | " + " | ".join(
        sorted({ch for e in report["table"] for ch in e["by_chapter"]})) + " |"]
    chapters = sorted({ch for e in report["table"] for ch in e["by_chapter"]})
    lines.append("|---|---|" + "---|" * len(chapters))
    for e in report["table"]:
        lines.append(f"| {e['profile']} | {e['condition']} | " + " | ".join(e["by_chapter"].get(ch, "—") for ch in chapters) + " |")
    if report["oracle_misses"]:
        lines += ["", "## 给了标准章节仍答错的题", ""]
        for profile, misses in report["oracle_misses"].items():
            lines.append(f"- {profile}：" + "、".join(f"{m['id']}（答 {m['answer']}，应 {m['gold']}）" for m in misses))
    lines += ["", "口径：标准答案 = 知识库规则章节原文（每题的逐字证据由 `bench.kb_qa check` 校验）；"
              "测的是知识库对模型是否可用，不是知识库与官方客户端是否一致。"]
    return "\n".join(lines) + "\n"


def write_report(bank_name: str, tag: str) -> dict[str, Any]:
    from bench.report import display_path
    from reps.knowledge import KnowledgeBase

    bank = load_bank(bank_name)
    kb = KnowledgeBase.load()
    rows_path = data_dir("bench", tag) / "kb_qa.jsonl"
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = summarise(rows, bank)
    report.update({"tag": tag, "generated": _dt.datetime.now().isoformat(timespec="seconds"),
                   "raw": display_path(rows_path), "kb_version": kb.version,
                   "retrieval": retrieval_table(bank, kb)})
    out = Path(ensure_dir(reports_dir() / "bench"))
    (out / f"{tag}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / f"{tag}.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("check", "retrieval"):
        p = sub.add_parser(name)
        p.add_argument("--bank", default="rules_v1")
    p = sub.add_parser("eval")
    p.add_argument("--bank", default="rules_v1")
    p.add_argument("--profiles", nargs="+", required=True, help="model profiles (configs/models.toml)")
    p.add_argument("--conditions", nargs="+", default=list(CONDITIONS), choices=CONDITIONS)
    p.add_argument("--tag", required=True)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--max-calls", type=int, default=2000)
    p = sub.add_parser("report")
    p.add_argument("--bank", default="rules_v1")
    p.add_argument("--tag", required=True)
    args = parser.parse_args(argv)
    from reps.knowledge import KnowledgeBase

    if args.cmd == "check":
        problems = validate(load_bank(args.bank), KnowledgeBase.load())
        print("ok" if not problems else "\n".join(problems))
        return 1 if problems else 0
    if args.cmd == "retrieval":
        print(json.dumps(retrieval_table(load_bank(args.bank), KnowledgeBase.load()), ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "eval":
        evaluate(args.bank, args.profiles, tag=args.tag, conditions=args.conditions,
                 workers=args.workers, max_calls=args.max_calls)
    else:
        write_report(args.bank, args.tag)
    print(f"[kb_qa] report: reports/bench/{args.tag}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
