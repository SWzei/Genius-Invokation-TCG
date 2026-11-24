"""Situational rule questions: does the knowledge injected *at a decision* let the model
apply the rules to the position in front of it?

Each item is a real action decision from a scenario source game (so it carries the
source's train / dev / test split) plus one multiple-choice question about that
position. The answer is computed by this module from the acting player's visible state
and the KB's rule tables -- never by a model:

``charged``    is a normal attack now a charged attack? (dice count parity, R04 §3)
``reaction``   what happens if the opponent's active character takes X damage now?
               (attachment table R06 §2 + reaction effects R06 §3.1)
``turn``       after one combat action, who acts next? (R01 §4.2, R03 §3)
``end``        what happens if we declare the round end now? (R03 §3, R01 §4.3)
``summon``     can one more, differently named summon be created? (R07 §1)

The knowledge shown with a question is what the knowledge profile selects **for the
decision** (the question text is not part of the retrieval query), so this measures
whether decision-time selection brings the rule that the situation needs.

    python -m bench.kb_situ build  --sets v1:all v2 --name situ_v1
    python -m bench.kb_situ render --name situ_v1 --profiles kbt-s0 kbt-s1 --tag kbt_situ
    python -m bench.kb_situ eval   --name situ_v1 --tag kbt_situ_r1 --render kbt_situ --model deepseek-flash \\
        --kb none kbt-s0 kbt-s1 --split dev
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.paths import REPO_ROOT, data_dir, ensure_dir, reports_dir
from common.pool import recycled_map

BANK_DIR = REPO_ROOT / "configs" / "bench" / "kb_situ"
ELEMENTS = ("冰", "水", "火", "雷", "风", "岩", "草")
LETTERS = "ABCD"

# R06 §2 (attachment table): (current attachment, damage element) -> (reaction or None, attachment after)
_REACT = {
    ("冰", "水"): "冻结", ("冰", "火"): "融化", ("冰", "雷"): "超导", ("冰", "风"): "扩散", ("冰", "岩"): "结晶",
    ("水", "冰"): "冻结", ("水", "火"): "蒸发", ("水", "雷"): "感电", ("水", "风"): "扩散", ("水", "岩"): "结晶",
    ("水", "草"): "绽放",
    ("火", "冰"): "融化", ("火", "水"): "蒸发", ("火", "雷"): "超载", ("火", "风"): "扩散", ("火", "岩"): "结晶",
    ("火", "草"): "燃烧",
    ("雷", "冰"): "超导", ("雷", "水"): "感电", ("雷", "火"): "超载", ("雷", "风"): "扩散", ("雷", "岩"): "结晶",
    ("雷", "草"): "原激化",
    ("草", "水"): "绽放", ("草", "火"): "燃烧", ("草", "雷"): "原激化",
    # 冰+草: anything that reacts with 冰 reacts with 冰 first, 草 stays
    ("冰+草", "水"): "冻结", ("冰+草", "火"): "融化", ("冰+草", "雷"): "超导", ("冰+草", "风"): "扩散",
    ("冰+草", "岩"): "结晶",
}
# R06 §3.1: damage bonus of each reaction
BONUS = {"融化": 2, "蒸发": 2, "超载": 2, "超导": 1, "感电": 1, "冻结": 1, "扩散": 0, "结晶": 1,
         "燃烧": 1, "绽放": 1, "原激化": 1}


def reaction_outcome(aura: str, element: str) -> str:
    """The answer text for ``element`` damage on a character with attachment ``aura``."""
    reaction = _REACT.get((aura, element))
    if reaction:
        return f"触发{reaction}反应，本次伤害 +{BONUS[reaction]}"
    if aura == "无":
        return "不发生反应，也不附着元素" if element in ("风", "岩") else f"不发生反应，目标附着{element}元素"
    if aura == element or (aura == "冰+草" and element in ("冰", "草")):
        return "不发生反应，附着不变"
    if {aura, element} == {"冰", "草"}:
        return "不发生反应，冰与草共存"
    if aura == "草" and element in ("风", "岩"):
        return "不发生反应，草元素保留"
    raise ValueError(f"no rule for {aura} + {element}")


def _reaction_distractors(correct: str, rng: random.Random) -> list[str]:
    pool = [f"触发{r}反应，本次伤害 +{b}" for r, b in BONUS.items()]
    pool += [f"触发{r}反应，本次伤害 +{b + 1}" for r, b in BONUS.items() if b < 2]
    pool += ["不发生反应，也不附着元素", "不发生反应，附着不变", "不发生反应，冰与草共存", "不发生反应，草元素保留"]
    pool += [f"不发生反应，目标附着{e}元素" for e in ("冰", "水", "火", "雷", "草")]
    if correct.startswith("触发"):
        name = correct[2:correct.index("反应")]
        near = [p for p in pool if p.startswith(f"触发{name}反应") and p != correct]
        others = [p for p in pool if p != correct and p not in near]
        near = near[:1]
        return near + rng.sample(others, 3 - len(near))
    return rng.sample([p for p in pool if p != correct], 3)


def refs_of(ref: str) -> list[str]:
    """``"R06 §2 / §3.1"`` -> ``["R06 §2", "R06 §3.1"]``."""
    out, doc = [], ""
    for part in (p.strip() for p in ref.split("/")):
        if part.startswith("§"):
            part = f"{doc} {part}"
        doc = part.split()[0]
        out.append(part)
    return out


def _options(correct: str, distractors: Sequence[str], rng: random.Random) -> tuple[dict[str, str], str]:
    options = [correct, *distractors]
    assert len(set(options)) == 4, options
    rng.shuffle(options)
    return {LETTERS[i]: o for i, o in enumerate(options)}, LETTERS[options.index(correct)]


QUESTION_VERSIONS = ("d32", "d33")


def questions_for(view: Mapping[str, Any], seat: int, rng: random.Random,
                  version: str = "d32") -> list[dict[str, Any]]:
    """All question items for one position (``view`` from ``DecisionDescriber.view``).

    ``d33`` (fresh banks only): no ``charged`` item below 3 dice (a normal attack cannot
    be paid there, so the question is moot), plus the held-out types of
    :func:`heldout_questions` -- types that no knowledge-access change was designed for."""
    if version not in QUESTION_VERSIONS:
        raise ValueError(f"question version must be one of {QUESTION_VERSIONS}")
    me = view["me"]
    out = []
    dice = len(me["dice"])
    if version == "d32" or dice >= 3:
        out.append(_charged(dice, rng))
    out += _designed_rest(view, rng)
    if version == "d33":
        out += [dict(q, heldout=True) for q in heldout_questions(view, rng)]
    return out


def _charged(dice: int, rng: random.Random) -> dict[str, Any]:
    opts, ans = _options("是，视为重击" if dice % 2 == 0 else "否，不视为重击",
                         ["否，不视为重击" if dice % 2 == 0 else "是，视为重击",
                          "只有对方出战角色处于冻结时才视为重击", "只有我方出战角色充能已满时才视为重击"], rng)
    return {"qtype": "charged", "ref": "R04 §3", "facts": {"dice": dice},
            "question": "按基础规则（不考虑卡牌、角色、状态的特殊效果），我方若在这次行动中直接使用普通攻击，它是否视为重击？",
            "options": opts, "answer": ans}


def _designed_rest(view: Mapping[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    me, opp = view["me"], view["opponent"]
    out: list[dict[str, Any]] = []
    active = next((c for c in opp["characters"] if c["active"] and not c["defeated"]), None)
    if active is not None and active["aura"] in ("无", "冰", "水", "火", "雷", "草", "冰+草"):
        aura, first = active["aura"], None
        if aura == "无":
            # nothing attached: ask about a second hit after a first attaching one (R06 §1 + §2)
            first = rng.choice(("冰", "水", "火", "雷", "草"))
            aura = first
        reacting = [e for e in ELEMENTS if (aura, e) in _REACT]
        element = rng.choice(reacting) if reacting and rng.random() < 0.75 else rng.choice(ELEMENTS)
        correct = reaction_outcome(aura, element)
        opts, ans = _options(correct, _reaction_distractors(correct, rng), rng)
        hit = (f"现在先受到 1 次{first}元素伤害，紧接着再受到 1 次{element}元素伤害，第二次伤害时" if first
               else f"现在受到 1 次{element}元素伤害，")
        out.append({"qtype": "reaction", "ref": "R06 §2 / §3.1",
                    "facts": {"aura": active["aura"], "first": first, "element": element},
                    "question": (f"按附着转移表与反应效果表（不考虑角色、卡牌、状态的额外效果），若对方出战角色"
                                 f"「{active['name']}」{hit}会发生什么？"),
                    "options": opts, "answer": ans})
    ended = bool(opp["declared_end"])
    opts, ans = _options("仍由我方继续行动" if ended else "轮到对方行动",
                         ["轮到对方行动" if ended else "仍由我方继续行动", "双方同时行动", "直接进入结束阶段"], rng)
    out.append({"qtype": "turn", "ref": "R03 §3", "facts": {"opponent_declared_end": ended},
                "question": "我方现在执行一次战斗行动（例如使用技能）之后，下一次由谁行动？",
                "options": opts, "answer": ans})
    if ended:
        correct = "进入结束阶段：先结算召唤物攻击等结束阶段效果，再双方各抓 2 张牌"
        wrong = ["对方还能再行动一次，之后才进入结束阶段", "先双方各抓 2 张牌，再结算召唤物攻击等结束阶段效果",
                 "直接开始下一回合，本回合的结束阶段效果不结算"]
    else:
        correct = "对方继续行动，直到对方也宣布回合结束"
        wrong = ["立即进入结束阶段", "本回合直接结束，双方各抓 2 张牌", "对方只能再行动一次，然后进入结束阶段"]
    opts, ans = _options(correct, wrong, rng)
    out.append({"qtype": "end", "ref": "R03 §3 / R01 §4.3", "facts": {"opponent_declared_end": ended},
                "question": "若我方现在宣布回合结束，接下来会发生什么？", "options": opts, "answer": ans})
    summons = len(me["summons"])
    room = max(0, 4 - summons)
    wrong = [f"{n} 个" for n in (room + 1, room + 2, room - 1) if n >= 0] + ["不限数量"]
    opts, ans = _options(f"{room} 个", wrong[:3], rng)
    out.append({"qtype": "summon", "ref": "R07 §1", "facts": {"summons": summons},
                "question": "按基础规则，我方召唤物区现在最多还能再容纳几个（与现有召唤物都不同名的）新召唤物？",
                "options": opts, "answer": ans})
    return out


def _numeric_options(correct: int, candidates: Sequence[int], rng: random.Random, fmt: str = "{} 个",
                     floor: int = 0) -> tuple[dict[str, str], str]:
    wrong: list[int] = []
    for v in [*candidates, correct + 1, correct - 1, correct + 2, correct - 2, correct + 3]:
        if v >= floor and v != correct and v not in wrong:
            wrong.append(v)
    return _options(fmt.format(correct), [fmt.format(v) for v in wrong[:3]], rng)


def heldout_questions(view: Mapping[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    """D33 held-out types: answered from the KB rules and the visible position like the
    designed ones, but chosen *after* the D32 triggers and never used to design anything.
    ``first_next`` R01 §4.2; ``energy`` R03 §2; ``hand_limit`` R01 §5; ``dice_cap`` R02 §1;
    ``tuning`` R02 §5."""
    me, opp = view["me"], view["opponent"]
    out: list[dict[str, Any]] = []
    ended = bool(opp["declared_end"])
    opts, ans = _options("对方先手" if ended else "我方先手",
                         ["我方先手" if ended else "对方先手", "由下回合投掷结果决定", "与本回合的先手方相同"], rng)
    out.append({"qtype": "first_next", "ref": "R01 §4.2", "facts": {"opponent_declared_end": ended},
                "question": "若我方现在宣布回合结束，下一回合由哪一方先行动？", "options": opts, "answer": ans})
    active = next((c for c in me["characters"] if c["active"] and not c["defeated"]), None)
    if active is not None and int(active["max_energy"]) > 0:
        e, m = int(active["energy"]), int(active["max_energy"])
        after = min(e + 1, m)
        opts, ans = _numeric_options(after, [e, e + 2, 0, m + 1, max(0, e - 1)], rng, fmt=f"{{}}/{m}")
        out.append({"qtype": "energy", "ref": "R03 §2", "facts": {"energy": e, "max_energy": m},
                    "question": (f"按基础规则（不考虑卡牌、角色、状态的特殊效果），我方出战角色「{active['name']}」"
                                 "现在使用一次元素战技后，它的充能是多少？"), "options": opts, "answer": ans})
    hand = int(me.get("hand_count", len(me.get("hand") or [])))
    k = max(1, 10 - hand + rng.choice((1, 2))) if rng.random() < 0.5 else rng.choice((1, 2, 3))
    total = min(hand + k, 10)
    opts, ans = _numeric_options(total, [hand + k, 10 if total != 10 else 9, hand, 11, hand + k - 1], rng, fmt="{} 张")
    out.append({"qtype": "hand_limit", "ref": "R01 §5", "facts": {"hand": hand, "draw": k},
                "question": f"若我方接下来连续抓 {k} 张牌（牌堆足够，不考虑其它效果），抓完后我方手牌是多少张？",
                "options": opts, "answer": ans})
    dice = len(me["dice"])
    k = max(1, 16 - dice + rng.choice((1, 2, 3))) if rng.random() < 0.5 else rng.choice((1, 2, 3))
    total = min(dice + k, 16)
    opts, ans = _numeric_options(total, [dice + k, 16 if total != 16 else 15, 8, dice, 17], rng)
    out.append({"qtype": "dice_cap", "ref": "R02 §1", "facts": {"dice": dice, "gain": k},
                "question": f"若某效果现在让我方再获得 {k} 个元素骰（不考虑其它效果），之后我方共有多少个元素骰？",
                "options": opts, "answer": ans})
    if hand > 0:
        opts, ans = _options("舍弃该牌，1 个元素骰变为出战角色的元素类型；之后仍由我方继续行动",
                             ["舍弃该牌，1 个元素骰变为万能元素；之后仍由我方继续行动",
                              "舍弃该牌，1 个元素骰变为出战角色的元素类型；之后轮到对方行动",
                              "舍弃该牌，额外获得 1 个出战角色元素类型的骰子；之后仍由我方继续行动"], rng)
        out.append({"qtype": "tuning", "ref": "R02 §5", "facts": {"hand": hand},
                    "question": "若我方现在用 1 张可调和的手牌进行元素调和，结果是什么？", "options": opts, "answer": ans})
    return out


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def _build_task(task: Mapping[str, Any]) -> dict[str, Any]:
    from bench.scenarios import context_at
    from reps.describe import DecisionDescriber

    source, seat, ordinal = task["source"], int(task["seat"]), int(task["ordinal"])
    try:
        built = context_at(source, seat, ordinal)
        view = DecisionDescriber().view(built.context.player_view, seat)
    except Exception as exc:                      # pragma: no cover - reported, not raised
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}
    rng = random.Random(int(task["rng_seed"]))
    return {"items": questions_for(view, seat, rng, task.get("version", "d32")), "round": int(view.get("round", 0) or 0)}


def build_bank(name: str, set_specs: Sequence[str], workers: int = 2, version: str = "d32") -> dict[str, Any]:
    """One action decision per source game (random seat); ``set_specs``: ``name`` or ``name:all``.
    Sources keep their scenario-set split; a set without splits (v1) is ``train``.
    ``version`` selects the question set (:data:`QUESTION_VERSIONS`)."""
    if version not in QUESTION_VERSIONS:
        raise ValueError(f"question version must be one of {QUESTION_VERSIONS}")
    from bench.scenarios import load_set
    from common.seeding import derive_seed

    tasks, meta = [], []
    for spec in set_specs:
        set_name = spec.split(":")[0]
        scenario_set = load_set(set_name)
        for i, source in enumerate(scenario_set["sources"]):
            rng = random.Random(derive_seed(int(source["seed"]), "kb-situ"))
            seat = rng.choice((0, 1))
            mine = [d for d in source["trace"] if d["seat"] == seat]
            pool = [k for k, d in enumerate(mine) if d["request"] == "action" and d["n"] >= 2]
            if not pool:
                continue
            ordinal = rng.choice(pool)
            tasks.append({"source": source, "seat": seat, "ordinal": ordinal,
                          "rng_seed": derive_seed(int(source["seed"]), "kb-situ-q"), "version": version})
            meta.append({"set": set_name, "source": i, "seat": seat, "ordinal": ordinal,
                         "split": source.get("split", "train")})
    results = list(recycled_map(_build_task, tasks, workers=workers, tasks_per_child=8))
    contexts, items, errors = [], [], 0
    for m, r in zip(meta, results):
        if r.get("error"):
            errors += 1
            continue
        ctx_id = f"{m['set']}#{m['source']}"
        contexts.append({"id": ctx_id, **m})
        for q in r["items"]:
            items.append({"id": f"{ctx_id}:{q['qtype']}", "context": ctx_id, "split": m["split"], **q})
    payload = {"name": name, "created": _dt.datetime.now().isoformat(timespec="seconds"),
               "from_sets": list(set_specs), **({"question_version": version} if version != "d32" else {}),
               "contexts": contexts, "context_errors": errors,
               "counts": dict(Counter(i["qtype"] for i in items)),
               "splits": dict(Counter(i["split"] for i in items)), "items": items}
    BANK_DIR.mkdir(parents=True, exist_ok=True)
    (BANK_DIR / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")
    return {k: v for k, v in payload.items() if k not in ("contexts", "items")}


def load_bank(name: str) -> dict[str, Any]:
    path = Path(name) if name.endswith(".json") else BANK_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# render: state text + the knowledge each profile selects at that decision
# --------------------------------------------------------------------------- #
def _profile_key(name: str) -> str:
    from reps.knowledge_pack import get_knowledge_profile

    blob = json.dumps(get_knowledge_profile(name).as_dict(), sort_keys=True, ensure_ascii=False)
    extra = ""
    profile = get_knowledge_profile(name)
    for path in (profile.unit_frequency_file, *profile.custom):
        if path:
            p = Path(path) if Path(path).is_absolute() else REPO_ROOT / path
            extra += hashlib.sha256(p.read_bytes()).hexdigest()[:12] if p.is_file() else ""
    return f"{name}@{hashlib.sha256((blob + extra).encode()).hexdigest()[:12]}"


def _render_task(task: Mapping[str, Any]) -> dict[str, Any]:
    from bench.scenarios import context_at, load_set
    from reps.describe import DecisionDescriber
    from reps.knowledge_pack import KnowledgeSelector, get_knowledge_profile

    scenario_set = load_set(task["set"])
    source = scenario_set["sources"][int(task["source"])]
    built = context_at(source, int(task["seat"]), int(task["ordinal"]))
    describer = DecisionDescriber(elements=bool(task.get("elements")))
    out = {"id": task["id"], "state": describer.state_text(built.context, detail=False), "packs": {}}
    for name, key in task["profiles"].items():
        pack = KnowledgeSelector(get_knowledge_profile(name)).select(built.context)
        out["packs"][key] = {"text": pack.text, "ids": [i.id for i in pack.items]}
    return out


def render(name: str, profiles: Sequence[str], tag: str, workers: int = 2, *, elements: bool = False) -> dict[str, Any]:
    """``elements`` (D35): state text names each character's element (as ``llm:...#elements=1``).
    A render cache holds one state text per position, so use a separate ``tag`` for it."""
    bank = load_bank(name)
    keys = {p: _profile_key(p) for p in profiles}
    run = Path(ensure_dir(data_dir("bench", tag)))
    marker = run / "render_options.json"
    options = {"elements": bool(elements)}
    if marker.exists() and json.loads(marker.read_text(encoding="utf-8")) != options:
        raise SystemExit(f"{run}: render cache was made with other options; use another --tag")
    marker.write_text(json.dumps(options), encoding="utf-8")
    path = run / "render.jsonl"
    have: dict[str, set] = defaultdict(set)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            have[row["id"]].update(row["packs"])
    tasks = []
    for ctx in bank["contexts"]:
        missing = {p: k for p, k in keys.items() if k not in have[ctx["id"]]}
        if missing or ctx["id"] not in have:
            tasks.append({**ctx, "profiles": missing, "elements": bool(elements)})
    with path.open("a", encoding="utf-8") as fh:
        for row in recycled_map(_render_task, tasks, workers=workers, tasks_per_child=8):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"contexts": len(bank["contexts"]), "rendered": len(tasks), "profiles": keys}


def _load_render(tag: str) -> dict[str, dict[str, Any]]:
    path = data_dir("bench", tag) / "render.jsonl"
    merged: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        slot = merged.setdefault(row["id"], {"state": row["state"], "packs": {}})
        slot["packs"].update(row["packs"])
    return merged


# --------------------------------------------------------------------------- #
# eval
# --------------------------------------------------------------------------- #
SYSTEM = ("你是七圣召唤（Genius Invokation TCG）牌手的助手。下面给出我方视角的当前局面"
          "（以及参考知识，若有），回答一道单选题。只输出 JSON：{\"answer\": \"A\"}，answer 取 A/B/C/D 之一。")
# answer mode "reason": a short justification is written *before* the answer (diagnostic:
# does the model use the injected rule when it has to state the relevant facts first?)
SYSTEM_REASON = ("你是七圣召唤（Genius Invokation TCG）牌手的助手。下面给出我方视角的当前局面"
                 "（以及参考知识，若有），回答一道单选题。只输出 JSON："
                 "{\"reason\": \"不超过 60 字的依据（写出用到的局面数字与规则）\", \"answer\": \"A\"}，"
                 "answer 取 A/B/C/D 之一。")


def build_messages(item: Mapping[str, Any], state: str, knowledge: str, *, mode: str = "answer") -> list[dict[str, str]]:
    parts = ["【局面】", state]
    if knowledge:
        parts += ["", "【参考知识】", knowledge]
    parts += ["", f"【题目】{item['question']}"] + [f"{k}. {item['options'][k]}" for k in LETTERS]
    system = SYSTEM_REASON if mode == "reason" else SYSTEM
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(parts)}]


def evaluate(name: str, render_tag: str, tag: str, model: str, kbs: Sequence[str], *, split: str | None,
             workers: int = 6, max_calls: int = 6000, mode: str = "answer") -> dict[str, Any]:
    from bench.kb_qa import parse_answer
    from common.llm_providers import build_client

    bank = load_bank(name)
    rendered = _load_render(render_tag)
    keys = {k: (None if k == "none" else _profile_key(k)) for k in kbs}
    items = [i for i in bank["items"] if split in (None, "all") or i["split"] == split]
    out_dir = Path(ensure_dir(data_dir("bench", tag)))
    rows_path = out_dir / "situ.jsonl"
    done = set()
    if rows_path.exists():
        for line in rows_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("mode", "answer") != mode:
                raise SystemExit(f"{rows_path} holds answer mode {row.get('mode', 'answer')!r}; use another --tag")
            if row.get("ok"):
                done.add((row["kb"], row["id"]))
    tasks = []
    for kb in kbs:
        for item in items:
            if (kb, item["id"]) in done:
                continue
            ctx = rendered.get(item["context"])
            if ctx is None or (keys[kb] is not None and keys[kb] not in ctx["packs"]):
                raise SystemExit(f"context {item['context']} not rendered for {kb}; run `render` first")
            tasks.append((kb, item, ctx))
    if len(tasks) > max_calls:
        raise SystemExit(f"{len(tasks)} calls planned > --max-calls {max_calls}")
    client = build_client(model, call_log=out_dir / "calls.jsonl")
    print(f"[kb_situ] {len(tasks)} calls ({len(done)} already done)", flush=True)

    def run(task):
        kb, item, ctx = task
        pack = ctx["packs"][keys[kb]] if keys[kb] else {"text": "", "ids": []}
        result = client.complete(build_messages(item, ctx["state"], pack["text"], mode=mode), want_json=True,
                                 tag=f"situ:{kb}:{mode}")
        answer = parse_answer(result.text)
        return {"kb": kb, "model": model, "mode": mode, "id": item["id"], "qtype": item["qtype"], "split": item["split"],
                "answer": answer, "gold": item["answer"], "correct": answer == item["answer"],
                "ok": result.ok, "error": result.error, "knowledge_ids": pack["ids"],
                **({"text": (result.text or "")[:300]} if mode == "reason" else {}),
                "has_ref": any(r in pack["ids"] for r in refs_of(item["ref"])),
                "prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens,
                "cost": result.cost, "latency_seconds": round(result.latency_seconds, 3)}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool, rows_path.open("a", encoding="utf-8") as fh:
        for i, row in enumerate(pool.map(run, tasks), 1):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 100 == 0:
                print(f"[kb_situ] {i}/{len(tasks)}", flush=True)
    return {"calls": len(tasks)}


def summarise(name: str, tags: Sequence[str], kbs: Sequence[str], split: str | None,
              subset: str | None = None) -> dict[str, Any]:
    """``subset``: ``designed`` (the D32 types) or ``heldout`` (D33 held-out types); None = all."""
    from bench.kb_train import _sign_p, _wilson

    bank = load_bank(name)
    items = {i["id"]: i for i in bank["items"] if (split in (None, "all") or i["split"] == split)
             and (subset is None or bool(i.get("heldout")) == (subset == "heldout"))}
    score: dict[str, dict[str, list[int]]] = {k: defaultdict(list) for k in kbs}
    has_ref: dict[str, Counter] = {k: Counter() for k in kbs}
    for tag in tags:
        path = data_dir("bench", tag) / "situ.jsonl"
        if not path.exists():
            continue
        latest = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["id"] in items and row["kb"] in score and row.get("ok"):
                latest[(row["kb"], row["id"])] = row
        for (kb, iid), row in latest.items():
            score[kb][iid].append(1 if row["correct"] else 0)
            has_ref[kb][row["qtype"]] += 1 if row.get("has_ref") else 0
    table = []
    for kb in kbs:
        obs = [v for vals in score[kb].values() for v in vals]
        by_type = defaultdict(list)
        for iid, vals in score[kb].items():
            by_type[items[iid]["qtype"]].extend(vals)
        table.append({"kb": kb, "items": len(score[kb]), "observations": len(obs),
                      "accuracy": round(sum(obs) / len(obs), 6) if obs else None, "ci95": _wilson(sum(obs), len(obs)),
                      "by_type": {t: f"{sum(v)}/{len(v)}" for t, v in sorted(by_type.items())},
                      "ref_in_knowledge": {t: f"{has_ref[kb][t]}/{len(v)}" for t, v in sorted(by_type.items())}})
    comparisons = []
    for a_i, a in enumerate(kbs):
        for b in kbs[:a_i]:
            sa = {i: sum(v) / len(v) for i, v in score[a].items() if v}
            sb = {i: sum(v) / len(v) for i, v in score[b].items() if v}
            common = sorted(set(sa) & set(sb))
            if not common:
                continue
            diffs = [sa[i] - sb[i] for i in common]
            better, worse = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
            m = sum(diffs) / len(diffs)
            sd = (sum((d - m) ** 2 for d in diffs) / max(1, len(diffs) - 1)) ** 0.5
            se = sd / len(diffs) ** 0.5
            comparisons.append({"a": a, "b": b, "n": len(common), "delta": round(m, 4),
                                "ci95": [round(m - 1.96 * se, 4), round(m + 1.96 * se, 4)],
                                "better": better, "worse": worse, "p": round(_sign_p(better, worse), 4)})
    return {"bank": name, "split": split, **({"subset": subset} if subset else {}), "runs": list(tags), "items": len(items),
            "item_types": dict(Counter(i["qtype"] for i in items.values())), "table": table,
            "comparisons": comparisons, "generated": _dt.datetime.now().isoformat(timespec="seconds")}


def render_markdown(report: Mapping[str, Any], title: str) -> str:
    lines = [f"# {title}", "", f"题库 `{report['bank']}`，划分 `{report['split']}`"
             + (f"，子集 `{report['subset']}`" if report.get("subset") else "") + f"（{report['items']} 题："
             + "、".join(f"{k} {v}" for k, v in report["item_types"].items()) + f"），轮次 {', '.join(report['runs'])}；"
             f"生成于 {report['generated']}。", "",
             "| 知识配置 | 观测数 | 正确率 [95% CI] | 按题型（正确 / 观测） | 注入知识含该题所需规则节（按题型计次） |",
             "|---|---|---|---|---|"]
    for e in report["table"]:
        acc = "—" if e["accuracy"] is None else f"{e['accuracy']:.3f} [{e['ci95'][0]:.2f}, {e['ci95'][1]:.2f}]"
        lines.append(f"| `{e['kb']}` | {e['observations']} | {acc} | "
                     + "；".join(f"{t} {v}" for t, v in e["by_type"].items()) + " | "
                     + ("；".join(f"{t} {v}" for t, v in sorted(e["ref_in_knowledge"].items())) or "—") + " |")
    lines += ["", "## 逐题配对（每题取各轮均值）", "", "| A | B | 题数 | A − B [95% CI] | A 更好 / 更差 | p |",
              "|---|---|---|---|---|---|"]
    for c in report["comparisons"]:
        lines.append(f"| `{c['a']}` | `{c['b']}` | {c['n']} | {c['delta']:+.3f} [{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}] | "
                     f"{c['better']} / {c['worse']} | {c['p']:.3f} |")
    lines += ["", "口径：答案由程序按知识库规则表与可见状态算出；知识按决策局面选取（不看题目）。"]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--sets", nargs="+", required=True)
    b.add_argument("--name", required=True)
    b.add_argument("--workers", type=int, default=2)
    b.add_argument("--version", default="d32", choices=list(QUESTION_VERSIONS),
                   help="d33: held-out question types, no charged item below 3 dice (fresh banks only)")
    r = sub.add_parser("render")
    r.add_argument("--name", required=True)
    r.add_argument("--profiles", nargs="+", required=True)
    r.add_argument("--tag", required=True)
    r.add_argument("--workers", type=int, default=2)
    r.add_argument("--elements", action="store_true", help="state text names character elements (D35)")
    e = sub.add_parser("eval")
    e.add_argument("--name", required=True)
    e.add_argument("--render", required=True, help="tag of the render cache")
    e.add_argument("--tag", required=True)
    e.add_argument("--model", required=True)
    e.add_argument("--kb", nargs="+", required=True, help="knowledge profiles, or none")
    e.add_argument("--split", default=None, choices=["train", "dev", "test", "all"])
    e.add_argument("--workers", type=int, default=6)
    e.add_argument("--max-calls", type=int, default=6000)
    e.add_argument("--mode", default="answer", choices=["answer", "reason"],
                   help="reason: a short justification before the answer (use a separate --tag)")
    s = sub.add_parser("report")
    s.add_argument("--name", required=True)
    s.add_argument("--runs", nargs="+", required=True)
    s.add_argument("--kb", nargs="+", required=True)
    s.add_argument("--split", default=None, choices=["train", "dev", "test", "all"])
    s.add_argument("--tag", required=True)
    s.add_argument("--title", default="情境规则题")
    s.add_argument("--subset", default=None, choices=["designed", "heldout"])
    args = parser.parse_args(argv)
    if args.cmd == "build":
        print(json.dumps(build_bank(args.name, args.sets, args.workers, args.version), ensure_ascii=False))
    elif args.cmd == "render":
        print(json.dumps(render(args.name, args.profiles, args.tag, args.workers, elements=args.elements),
                         ensure_ascii=False))
    elif args.cmd == "eval":
        print(json.dumps(evaluate(args.name, args.render, args.tag, args.model, args.kb, split=args.split,
                                  workers=args.workers, max_calls=args.max_calls, mode=args.mode)))
    else:
        report = summarise(args.name, args.runs, args.kb, args.split, args.subset)
        report["tag"] = args.tag
        out = Path(ensure_dir(reports_dir() / "bench"))
        (out / f"{args.tag}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / f"{args.tag}.md").write_text(render_markdown(report, args.title), encoding="utf-8")
        print(f"[kb_situ] report: reports/bench/{args.tag}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
