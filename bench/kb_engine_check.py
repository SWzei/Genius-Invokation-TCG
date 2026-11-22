"""Engine checks for rule-layer KB edits (D34).

A rule-layer edit (``reps.kb_versions``, layer ``rules``) may only restate or tighten
facts; every fact a new rule card states is checked here against the engine itself,
on real positions replayed from a scenario set (the ``train`` split by default):

* ``energy``   -- fork, use a normal attack / elemental skill, read the character's
  energy: +1, never above its maximum (R03 §2 + R04 §2);
* ``first_next`` -- fork, declare the round over, play on (every later decision:
  declare end / first option) and see who acts first next round (R01 §4.2, R03 §3);
* ``tuning``   -- fork, tune a card: dice count unchanged, exactly one die changed,
  and the same seat acts next (quick action, R02 §5);
* ``charged``  -- at every action decision the engine's ``canCharged`` equals
  "dice count is even" (R04 §3);
* ``caps``     -- the engine's configured limits: dice 16, hand 10, summons 4, supports 4
  (R02 §1, R01 §5, R07 §1).

    python -m bench.kb_engine_check --set v2 --split train --max-sources 30 --out kb_engine_check_v11
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
from typing import Any, Callable, Mapping, Sequence

from common.paths import ensure_dir, reports_dir

EXPECTED_CAPS = {"max_dice": 16, "max_hands": 10, "max_summons": 4, "max_supports": 4}


class _Stop(Exception):
    pass


class _Probe:
    """Replay ``indices``; at the next decision play ``then`` (once, if given) and keep
    that decision's context in ``at``; every later decision goes to ``after``."""

    def __init__(self, indices: Sequence[int], counts: Sequence[int], *, then: int | None = None,
                 after: Callable[[Any, "_Probe"], int] | None = None, seat: int = 0) -> None:
        self.indices, self.counts = list(indices), list(counts)
        self.then, self.after, self.seat = then, after, seat
        self.cursor, self.played_then, self.at, self.mismatch = 0, False, None, None
        self.name = "engine-probe"

    def choose(self, built: Any) -> int:
        from agents.human import HumanQuit

        codes = [int(c) for c in built.context.legal_low_level_codes]
        if self.cursor < len(self.indices):
            index = self.indices[self.cursor]
            if len(codes) != self.counts[self.cursor] or not 0 <= index < len(codes):
                self.mismatch = f"decision {self.cursor}: recorded {self.counts[self.cursor]} options, now {len(codes)}"
                raise HumanQuit("replay mismatch")
            self.cursor += 1
            return codes[index]
        if self.then is not None and not self.played_then:
            self.played_then, self.at = True, built
            return codes[self.then]
        if self.after is None:
            raise HumanQuit("probe: no instruction")
        try:
            return codes[self.after(built, self)]
        except _Stop:
            raise HumanQuit("probe: observed") from None


def _run(source: Mapping[str, Any], seat: int, ordinal: int, then: int | None,
         after: Callable[[Any, _Probe], int]) -> tuple[_Probe, _Probe]:
    from bench.scenarios import _prefixes, _run as run_source

    mine, other = _prefixes(source, seat, ordinal)
    me = _Probe([d["index"] for d in mine], [d["n"] for d in mine], then=then, after=after, seat=seat)
    opp = _Probe([d["index"] for d in other], [d["n"] for d in other], after=after, seat=1 - seat)
    run_source(source, (me, opp) if seat == 0 else (opp, me))
    if me.mismatch or opp.mismatch:
        raise RuntimeError(me.mismatch or opp.mismatch)
    return me, opp


def _kind(spec: Any) -> str:
    return getattr(spec.kind, "value", str(spec.kind))


def _player(view: Any, seat: int) -> Any:
    return view.players[seat]


def _char(player: Any, char_id: int) -> Any:
    return next(c for c in player.characters if c.id == char_id)


def _skill_kind(definition_id: int) -> str:
    from reps.describe import _cached_assets

    return _cached_assets().get(int(definition_id)).kind


# ------------------------------------------------------------------ checks


def check_energy(source: Mapping[str, Any], seat: int, ordinal: int, built: Any) -> list[dict[str, Any]]:
    view = built.context.player_view
    me = _player(view, seat)
    active = next((c for c in me.characters if c.is_active and not c.defeated), None)
    if active is None or active.max_energy <= 0:
        return []
    out = []
    for index, spec in enumerate(built.context.legal_low_level_specs):
        if _kind(spec) != "action_use_skill":
            continue
        kind = _skill_kind(spec.subject_definition_id)
        if kind not in ("普通攻击", "元素战技"):
            continue
        seen: dict[str, Any] = {}

        def capture(b: Any, probe: _Probe) -> int:
            seen["view"], seen["seat"] = b.context.player_view, probe.seat
            raise _Stop

        try:
            _run(source, seat, ordinal, index, capture)
        except RuntimeError:
            continue
        if "view" not in seen:
            continue                                # game over
        after = _char(_player(seen["view"], seat), active.id)
        if after.defeated:
            continue
        expected = min(active.energy + 1, active.max_energy)
        out.append({"check": "energy", "skill_kind": kind, "character": active.definition_id,
                    "before": active.energy, "max": active.max_energy, "after": after.energy,
                    "expected": expected, "capped_case": active.energy >= active.max_energy,
                    "never_above_max": after.energy <= after.max_energy, "ok": after.energy == expected})
        break                                       # one skill per position
    return out


def _end_policy(record: dict[str, Any], round0: int) -> Callable[[Any, _Probe], int]:
    def choose(b: Any, probe: _Probe) -> int:
        ctx = b.context
        rt = getattr(ctx.request_type, "value", str(ctx.request_type))
        if rt == "action" and int(ctx.player_view.round_number) > round0:
            record["first"] = probe.seat
            raise _Stop
        for i, spec in enumerate(ctx.legal_low_level_specs):
            if _kind(spec) == "action_declare_end":
                return i
        return 0
    return choose


def check_first_next(source: Mapping[str, Any], seat: int, ordinal: int, built: Any) -> list[dict[str, Any]]:
    ctx = built.context
    index = next((i for i, s in enumerate(ctx.legal_low_level_specs) if _kind(s) == "action_declare_end"), None)
    if index is None:
        return []
    opp_ended = bool(_player(ctx.player_view, 1 - seat).declared_end)
    record: dict[str, Any] = {}
    try:
        _run(source, seat, ordinal, index, _end_policy(record, int(ctx.player_view.round_number)))
    except RuntimeError:
        return []
    if "first" not in record:
        return []                                   # the game ended first
    expected = (1 - seat) if opp_ended else seat    # whoever declared first starts next round
    return [{"check": "first_next", "opponent_declared_first": opp_ended, "first": record["first"],
             "expected": expected, "ok": record["first"] == expected}]


def check_tuning(source: Mapping[str, Any], seat: int, ordinal: int, built: Any) -> list[dict[str, Any]]:
    ctx = built.context
    index = next((i for i, s in enumerate(ctx.legal_low_level_specs) if _kind(s) == "action_elemental_tuning"), None)
    if index is None:
        return []
    before = list(_player(ctx.player_view, seat).dice)
    seen: dict[str, Any] = {}

    def capture(b: Any, probe: _Probe) -> int:
        seen["view"], seen["seat"] = b.context.player_view, probe.seat
        raise _Stop

    try:
        _run(source, seat, ordinal, index, capture)
    except RuntimeError:
        return []
    if "view" not in seen:
        return []
    after = list(_player(seen["view"], seat).dice) if seen["seat"] == seat else None
    changed = None
    if after is not None:
        diff = collections.Counter(before) - collections.Counter(after)
        changed = sum(diff.values())
    ok = seen["seat"] == seat and after is not None and len(after) == len(before) and changed == 1
    return [{"check": "tuning", "same_seat_next": seen["seat"] == seat, "dice_before": len(before),
             "dice_after": None if after is None else len(after), "dice_changed": changed, "ok": ok}]


def check_charged(source: Mapping[str, Any], seat: int, ordinal: int, built: Any) -> list[dict[str, Any]]:
    # The engine's flag lives in the full state; the seat's notification view does not carry it
    # (the agents never see it -- this is a checker, not an observation).
    if built.context.full_state is None:
        return []
    me = _player(built.context.full_state, seat)
    dice = len(me.dice)
    return [{"check": "charged", "dice": dice, "can_charged": bool(me.can_charged),
             "ok": bool(me.can_charged) == (dice % 2 == 0)}]


def check_visibility(source: Mapping[str, Any], seat: int, ordinal: int, built: Any) -> list[dict[str, Any]]:
    """R10 §2: what the seat's own observation (``notification.state``) shows of each side."""
    view = built.context.player_view
    me, opp = _player(view, seat), _player(view, 1 - seat)
    opp_hand_hidden = all(int(c.definition_id) == 0 for c in opp.hand_cards)
    own_hand_known = all(int(c.definition_id) != 0 for c in me.hand_cards)
    opp_dice_faces_hidden = len(opp.dice) == 0
    opp_dice_count_shown = int(getattr(opp, "dice_count", -1)) >= 0
    opp_pile_order_hidden = all(int(c.definition_id) == 0 for c in opp.pile_cards)
    own_pile_order_hidden = all(int(c.definition_id) == 0 for c in me.pile_cards)
    board_shown = all(c.max_health > 0 for c in opp.characters)
    ok = (opp_hand_hidden and own_hand_known and opp_dice_faces_hidden and opp_dice_count_shown
          and opp_pile_order_hidden and own_pile_order_hidden and board_shown)
    return [{"check": "visibility", "opp_hand_hidden": opp_hand_hidden, "own_hand_known": own_hand_known,
             "opp_dice_faces_hidden": opp_dice_faces_hidden, "opp_dice_count_shown": opp_dice_count_shown,
             "opp_pile_order_hidden": opp_pile_order_hidden, "own_pile_order_hidden": own_pile_order_hidden,
             "board_shown": board_shown, "ok": ok}]


def engine_caps() -> dict[str, Any]:
    import gitcg.low_level as ll
    from gitcg import State

    from bench.suite import resolve_deck
    from envs.match import _build_create_param

    deck = resolve_deck("natlan_battleship")
    state = State(create_param=_build_create_param(deck, deck, seed=1, version=None))
    attrs = {"max_dice": ll.ATTR_STATE_CONFIG_MAX_DICE_COUNT, "max_hands": ll.ATTR_STATE_CONFIG_MAX_HANDS_COUNT,
             "max_summons": ll.ATTR_STATE_CONFIG_MAX_SUMMONS_COUNT,
             "max_supports": ll.ATTR_STATE_CONFIG_MAX_SUPPORTS_COUNT}
    got = {k: int(ll.state_get_attr(state._state_handle, v)) for k, v in attrs.items()}
    return {"check": "caps", "engine": got, "expected": EXPECTED_CAPS, "ok": got == EXPECTED_CAPS}


CHECKS = {"energy": check_energy, "first_next": check_first_next, "tuning": check_tuning, "charged": check_charged,
          "visibility": check_visibility}


def run_checks(set_name: str, split: str, max_sources: int, per_source: int) -> dict[str, Any]:
    from bench.scenarios import context_at, load_set

    scenario_set = load_set(set_name)
    sources = [s for s in scenario_set["sources"] if split == "all" or s.get("split", "train") == split]
    rows: list[dict[str, Any]] = []
    for s_index, source in enumerate(sources[:max_sources]):
        actions = [(d["seat"], k) for seat in (0, 1)
                   for k, d in enumerate([x for x in source["trace"] if x["seat"] == seat])
                   if d.get("request") == "action"]
        step = max(1, len(actions) // max(1, per_source))
        for seat, ordinal in actions[::step][:per_source]:
            try:
                built = context_at(source, seat, ordinal, full_state=True)
            except RuntimeError:
                continue
            for name, fn in CHECKS.items():
                for row in fn(source, seat, ordinal, built):
                    rows.append({"source": s_index, "seat": seat, "ordinal": ordinal, **row})
    caps = engine_caps()
    summary: dict[str, Any] = {}
    for name in CHECKS:
        mine = [r for r in rows if r["check"] == name]
        summary[name] = {"n": len(mine), "agree": sum(r["ok"] for r in mine)}
    energy = [r for r in rows if r["check"] == "energy"]
    summary["energy"].update({
        "capped_cases": sum(r["capped_case"] for r in energy),
        "capped_agree": sum(r["ok"] for r in energy if r["capped_case"]),
        "ever_above_max": sum(not r["never_above_max"] for r in energy)})
    summary["caps"] = caps
    return {"generated": _dt.datetime.now().isoformat(timespec="seconds"), "set": set_name, "split": split,
            "sources": min(len(sources), max_sources), "summary": summary,
            "disagreements": [r for r in rows if not r["ok"]], "rows": len(rows)}


def render_markdown(report: Mapping[str, Any]) -> str:
    s = report["summary"]
    e = s["energy"]
    lines = ["# 规则层修改的引擎核对（D34）", "",
             f"场景集 `{report['set']}` 的 `{report['split']}` 部分，{report['sources']} 局源对局；生成于 {report['generated']}。",
             "每项在真实局面上分叉执行，或读取引擎状态 / 配置。", "",
             "| 核对项 | 规则卡中的说法 | 观测数 | 与说法一致 |", "|---|---|---|---|",
             f"| 充能 | 普通攻击、元素战技后 +1，不超过上限 | {e['n']} | {e['agree']}（其中已满时 {e['capped_agree']}/{e['capped_cases']}；超过上限 {e['ever_above_max']} 次） |",
             f"| 下回合先手 | 先宣布结束的一方下回合先手 | {s['first_next']['n']} | {s['first_next']['agree']} |",
             f"| 元素调和 | 骰子数不变、恰好 1 个骰子改变、仍由我方行动 | {s['tuning']['n']} | {s['tuning']['agree']} |",
             f"| 重击 | 行动前骰子数为偶数时普通攻击视为重击（引擎 `canCharged`） | {s['charged']['n']} | {s['charged']['agree']} |",
             f"| 信息划分 | 对方手牌内容、骰子元素面、双方牌堆顺序不可见；骰子数量、场面可见（本方观测 `notification.state`） | {s['visibility']['n']} | {s['visibility']['agree']} |",
             f"| 上限 | 骰子 16、手牌 10、召唤物 4、支援 4 | 引擎配置 | {'一致' if s['caps']['ok'] else '不一致：' + json.dumps(s['caps']['engine'])} |",
             ""]
    if report["disagreements"]:
        lines += ["## 不一致的观测", "", "| 核对项 | 详情 |", "|---|---|"]
        for r in report["disagreements"][:40]:
            lines.append(f"| {r['check']} | {json.dumps({k: v for k, v in r.items() if k not in ('check', 'ok')}, ensure_ascii=False)} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", default="v2")
    parser.add_argument("--split", default="train")
    parser.add_argument("--max-sources", type=int, default=30)
    parser.add_argument("--per-source", type=int, default=6, help="action decisions sampled per source game")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    report = run_checks(args.set, args.split, args.max_sources, args.per_source)
    out = ensure_dir(reports_dir("bench"))
    (out / f"{args.out}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / f"{args.out}.md").write_text(render_markdown(report), encoding="utf-8")
    print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
