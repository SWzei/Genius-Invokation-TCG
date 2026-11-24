"""An LLM as a full player (``Policy``), with optional knowledge augmentation.

``agents.llm_assist`` lets a model *re-rank* a scripted policy's choice at a few
decisions. This module lets a model *play*: at every decision it reads the acting
seat's view and the legal options (``reps.describe``), optionally a knowledge pack
(``reps.knowledge_pack``), and answers with a legal option.

Guarantees, independent of the model:

* **legality** -- the reply is mapped onto the engine's legal options and validated;
  anything else (unparseable, out of range, API failure, budget exhausted) falls
  back to a base policy, so a game never stalls and never plays an illegal action;
* **information boundary** -- the prompt is built only from ``player_view`` and the
  legal options; nothing from ``full_state`` is read;
* **traceability** -- every decision yields a :class:`DecisionTrace`: source
  (``llm`` / ``fallback`` / ``forced``), the reply and reason, latency, tokens,
  cost, error kind and the ids of the knowledge items shown.

Strength acceptance stays pure-policy (``AGENTS.md``): an LLM player is an
experiment subject, not a certified agent.

Spec strings (``envs.policy.build_policy``)::

    llm:<model-profile>[#kb=<knowledge-profile>,fallback=<policy spec>,budget=<calls/game>,
                         model=<id override>,detail=0|1,reply=choice_first|reason_first|checklist,elements=0|1,facts=0|1,cards=0|1]
    llm-assist:<model-profile>#base=<policy spec>[,budget=<calls/game>]
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence

from common.llm import extract_json_object
from reps.describe import DecisionDescriber, find_mask_option
from reps.schema import DecisionType

SYSTEM_PROMPT = (
    "你是《七圣召唤》（原神卡牌对战）的玩家，正在为“我方”做一次决策。\n"
    "你只能看到我方可见的信息：对方的手牌与骰子、双方牌库的内容和顺序都不可见，不要假设它们。\n"
    "卡牌、状态文本中的“我方/敌方”相对于该牌或状态的所有者。\n"
    "必须从给出的合法选项里选择，不要编造选项；合法选项列表就是当前规则允许的全部行动。\n"
    "只输出一个 JSON 对象，不要输出任何其他文字。"
)
_PROTOCOL = {
    "index": '回复格式：{"choice": <选项编号>, "reason": "<不超过 40 字的理由>"}',
    "reroll_dice": '回复格式：{"reroll": [<要重掷的骰子位置编号，可为空>], "reason": "<不超过 40 字的理由>"}',
    "switch_hands": '回复格式：{"swap": [<要替换的手牌位置编号，可为空>], "reason": "<不超过 40 字的理由>"}',
}
# reply=reason_first (D32): the justification is written before the choice, so the model
# states the relevant numbers and rules before committing (a question-level probe showed
# injected rules were used only when the model had to write such a justification first).
_PROTOCOL_REASON_FIRST = {
    "index": '回复格式：{"reason": "<不超过 60 字：先写出与决策相关的局面数字和规则，再说理由>", "choice": <选项编号>}',
    "reroll_dice": '回复格式：{"reason": "<不超过 60 字的理由>", "reroll": [<要重掷的骰子位置编号，可为空>]}',
    "switch_hands": '回复格式：{"reason": "<不超过 60 字的理由>", "swap": [<要替换的手牌位置编号，可为空>]}',
}
# reply=checklist (D33 candidate): reason first, walking a fixed decision checklist that
# came from the D32 training-split lethal misses (end-phase damage, opponent still acting,
# miscounted costs) before the choice.
_PROTOCOL_CHECKLIST = dict(_PROTOCOL_REASON_FIRST, index=(
    '回复格式：{"reason": "<不超过 80 字：依次确认①本行动轮能否直接击倒对方角色或赢下（含结束阶段的伤害）；'
    '②对方是否已宣布回合结束；③骰子与费用是否够；再说理由>", "choice": <选项编号>}'))
ALL_REQUESTS = ("action", "choose_active", "reroll_dice", "switch_hands", "select_card")


@dataclass
class LLMPolicyConfig:
    request_types: tuple[str, ...] = ALL_REQUESTS
    budget_per_game: int | None = None        # model calls per game for this seat
    max_options: int = 40                     # options listed for index-type decisions
    detail: bool = True                       # include card / status rules text
    max_tokens: int | None = None             # None = the profile's
    temperature: float | None = None
    retries_on_invalid: int = 1               # re-ask once when the reply is unusable
    reply: str = "choice_first"               # or "reason_first" / "checklist"

    def as_dict(self) -> dict[str, Any]:
        return {"request_types": list(self.request_types), "budget_per_game": self.budget_per_game,
                "max_options": self.max_options, "detail": self.detail,
                "retries_on_invalid": self.retries_on_invalid,
                **({"reply": self.reply} if self.reply != "choice_first" else {})}


@dataclass
class DecisionTrace:
    step_index: int
    request_type: str
    n_options: int
    source: str                      # llm | fallback | forced
    final_code: int
    final_index: int
    final_text: str = ""
    llm_index: int | None = None
    reason: str = ""
    error: str | None = None         # why the model's answer was not used
    raw: str | None = None
    profile: str = ""
    model: str = ""
    calls: int = 0
    latency_seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    cost: float | None = None
    prompt_chars: int = 0
    prompt_sha: str = ""
    knowledge: dict[str, Any] = field(default_factory=dict)
    first_reply_legal: bool | None = None   # the first reply mapped onto a legal option (None: not asked)
    first_error: str | None = None          # why the first reply was not usable
    prompt: str | None = None               # user prompt, kept only when the policy is asked to (D34 traces)

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index, "request_type": self.request_type,
            "n_options": self.n_options, "source": self.source, "final_code": self.final_code,
            "final_index": self.final_index, "final_text": self.final_text,
            "llm_index": self.llm_index, "reason": self.reason, "error": self.error,
            "raw": None if self.raw is None else self.raw[:2000], "profile": self.profile,
            "model": self.model, "calls": self.calls,
            "latency_seconds": round(self.latency_seconds, 3),
            "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens, "reasoning_tokens": self.reasoning_tokens,
            "cost": None if self.cost is None else round(self.cost, 6),
            "prompt_chars": self.prompt_chars, "prompt_sha": self.prompt_sha,
            "knowledge": self.knowledge,
            "first_reply_legal": self.first_reply_legal, "first_error": self.first_error,
            **({"prompt": self.prompt} if self.prompt is not None else {}),
        }


def build_messages(
    context: Any,
    describer: DecisionDescriber,
    *,
    knowledge_text: str = "",
    detail: bool = True,
    max_options: int = 40,
    reply: str = "choice_first",
) -> tuple[list[dict[str, str]], str, int]:
    """Prompt for one decision -> (messages, protocol key, options listed)."""
    protocol = {"reason_first": _PROTOCOL_REASON_FIRST, "checklist": _PROTOCOL_CHECKLIST}.get(reply, _PROTOCOL)
    request = context.request_type
    parts = [describer.state_text(context, detail=detail)]
    if getattr(describer, "cards", False):         # D37: same text all game long, so it goes first
        parts.insert(0, describer.cards_text(context))
    if detail:
        skills = describer.active_skills_text(context)
        if skills:
            parts.append("当前可用技能：\n" + skills)
    if knowledge_text:
        parts.append("以下是可参考的知识（规则事实与策略观点已分开标注）：\n" + knowledge_text)
    view = context.player_view
    me = view.players[int(context.acting_player)]
    if request == DecisionType.REROLL_DICE:
        state = describer.state(context)
        dice = " ".join(f"[{i}]{name}" for i, name in enumerate(state["me"]["dice"]))
        parts.append(f"现在可以重掷任意数量的骰子（一次）。我方骰子与位置编号：{dice}\n" + protocol["reroll_dice"])
        return _wrap(parts), "reroll_dice", len(me.dice)
    if request == DecisionType.SWITCH_HANDS:
        state = describer.state(context)
        hand = "\n".join(f"[{i}] {card['name']}（{card['kind'] or '牌'}，费用 {card['cost']}）"
                         for i, card in enumerate(state["me"]["hand"]))
        parts.append("现在可以把任意数量的起始手牌换回牌库并重抽等量的牌。手牌与位置编号：\n" + hand
                     + "\n" + protocol["switch_hands"])
        return _wrap(parts), "switch_hands", len(me.hand_cards)
    total = len(context.legal_low_level_specs)
    listed = min(total, max(1, int(max_options)))
    note = "" if listed == total else f"\n（共 {total} 个合法选项，仅列出前 {listed} 个）"
    if getattr(describer, "facts", False) and request == DecisionType.ACTION:
        facts = describer.facts_text(context, listed)
        if facts:
            parts.append("派生事实（由本方可见信息计算，已经引擎核对）：\n" + facts)
    parts.append("合法选项：\n" + describer.options_text(context, range(listed)) + note + "\n" + protocol["index"])
    return _wrap(parts), "index", listed


def _wrap(parts: Sequence[str]) -> list[dict[str, str]]:
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(parts)}]


def parse_reply(context: Any, protocol: str, listed: int, raw: str | None) -> tuple[int | None, str, str | None]:
    """Map a model reply onto a legal option -> (option index, reason, error)."""
    parsed = extract_json_object(raw)
    if parsed is None:
        return None, "", "unparseable"
    reason = str(parsed.get("reason") or "")[:200]
    if protocol == "index":
        try:
            index = int(parsed.get("choice"))
        except (TypeError, ValueError):
            return None, reason, "no_choice"
        if not 0 <= index < listed:
            return None, reason, "choice_out_of_range"
        return index, reason, None
    key = "reroll" if protocol == "reroll_dice" else "swap"
    positions = parsed.get(key)
    if positions is None:
        return None, reason, f"no_{key}"
    try:
        positions = [int(p) for p in positions]
    except (TypeError, ValueError):
        return None, reason, f"bad_{key}"
    index = find_mask_option(context, positions)
    if index is None:
        return None, reason, "positions_out_of_range"
    return index, reason, None


# --------------------------------------------------------------------------- #
# D38: decision models (Gemini Decisions API). The same prompt minus the reply format;
# the options become named criteria of a ``choice`` question, mulligan / reroll become
# one yes/no question per card / die. No text is generated.
# --------------------------------------------------------------------------- #
DECISION_INSTRUCTIONS = "根据上面的局面，从合法选项中选出“我方”此刻最好的一个行动。"


def decision_messages(context: Any, describer: DecisionDescriber, messages: Sequence[Mapping[str, str]],
                      protocol: str, listed: int, reply: str = "choice_first") -> list[dict[str, str]]:
    formats = {"reason_first": _PROTOCOL_REASON_FIRST, "checklist": _PROTOCOL_CHECKLIST}.get(reply, _PROTOCOL)
    system = SYSTEM_PROMPT.replace("只输出一个 JSON 对象，不要输出任何其他文字。", "").rstrip()
    user = str(messages[-1]["content"]).replace("\n" + formats[protocol], "")
    if protocol == "index":
        options = describer.options(context)
        questions: dict[str, Any] = {"action": {"type": "choice", "instructions": DECISION_INSTRUCTIONS,
                                                "criteria": {f"o{i}": options[i]["text"] for i in range(listed)}}}
    else:
        state = describer.state(context)
        if protocol == "reroll_dice":
            items = [(i, f"是否重掷位置 [{i}] 的骰子（{name}）？") for i, name in enumerate(state["me"]["dice"])]
        else:
            items = [(i, f"是否把位置 [{i}] 的起始手牌（{card['name']}）换回牌库重抽？")
                     for i, card in enumerate(state["me"]["hand"])]
        questions = {f"q{i}": {"type": "noul", "instructions": text} for i, text in items}
    return [{"role": "system", "content": system}, {"role": "user", "content": user},
            {"role": "decision", "content": json.dumps(questions, ensure_ascii=False)}]


def parse_decision(context: Any, protocol: str, listed: int, raw: str | None) -> tuple[int | None, str, str | None]:
    """Map Decisions API answers onto a legal option -> (option index, reason, error)."""
    try:
        answers = json.loads(raw or "")
    except ValueError:
        return None, "", "unparseable"
    if protocol == "index":
        answer = answers.get("action") or {}
        key = str(answer.get("choice", ""))
        if not key.startswith("o") or not key[1:].isdigit() or not 0 <= int(key[1:]) < listed:
            return None, "", "no_choice"
        return int(key[1:]), f"p={float(answer.get('confidence', 0)):.2f}", None
    positions = sorted(int(k[1:]) for k, a in answers.items()
                       if k.startswith("q") and k[1:].isdigit() and float(a.get("noul", 0)) > 0.5)
    index = find_mask_option(context, positions)
    if index is None:
        return None, "", "positions_out_of_range"
    return index, "yes=" + ",".join(map(str, positions)), None


class LLMPolicy:
    """A model profile playing through the ``Policy`` protocol."""

    def __init__(
        self,
        client: Any,
        fallback: Any,
        *,
        selector: Any = None,
        describer: DecisionDescriber | None = None,
        config: LLMPolicyConfig | None = None,
        on_trace: Callable[[DecisionTrace], None] | None = None,
        name: str | None = None,
    ) -> None:
        self.client = client
        self.fallback = fallback
        self.selector = selector
        self.describer = describer or DecisionDescriber()
        self.config = config or LLMPolicyConfig()
        self.on_trace = on_trace
        self.traces: list[DecisionTrace] = []
        self.calls = 0
        profile = getattr(client, "profile", None)
        self.profile_name = getattr(profile, "name", getattr(getattr(client, "config", None), "name", "llm"))
        self.name = name or f"llm:{self.profile_name}"

    # -- helpers ---------------------------------------------------------------- #
    def _fallback_code(self, built: Any) -> int:
        codes = [int(c) for c in built.context.legal_low_level_codes]
        try:
            code = int(self.fallback.choose(built))
        except Exception:
            code = -1
        return code if code in codes else codes[0]

    def _knowledge(self, context: Any) -> Any:
        if self.selector is None:
            return None
        query = self.describer.state_text(context, detail=False)
        return self.selector.select(context, query=query)

    def _budget_left(self) -> bool:
        if self.config.budget_per_game is not None and self.calls >= int(self.config.budget_per_game):
            return False
        budget_left = getattr(self.client, "budget_left", None)
        return budget_left() is None if callable(budget_left) else True

    def _complete(self, messages: list[dict[str, str]]) -> Any:
        self.calls += 1
        complete = getattr(self.client, "complete", None)
        if callable(complete):
            return complete(messages, max_tokens=self.config.max_tokens,
                            temperature=self.config.temperature, want_json=True, tag="decision")
        # ``common.llm`` style clients: text or None.
        from common.llm_providers import ChatResult

        text = self.client.chat(messages, max_tokens=self.config.max_tokens,
                                temperature=self.config.temperature, response_format_json=True)
        return ChatResult(text, error=None if text else "network", attempts=1)

    def _finish(self, trace: DecisionTrace, built: Any) -> int:
        try:
            option = self.describer.option(
                built.context, built.context.legal_low_level_specs[trace.final_index], trace.final_index)
            trace.final_text = option["text"]
        except Exception:
            trace.final_text = ""
        self.traces.append(trace)
        if self.on_trace is not None:
            self.on_trace(trace)
        return trace.final_code

    # -- Policy ----------------------------------------------------------------- #
    def choose(self, built: Any) -> int:
        context = built.context
        codes = [int(c) for c in context.legal_low_level_codes]
        request = context.request_type.value

        def trace_for(source: str, code: int, **extra: Any) -> DecisionTrace:
            return DecisionTrace(step_index=int(context.step_index), request_type=request,
                                 n_options=len(codes), source=source, final_code=int(code),
                                 final_index=codes.index(int(code)), profile=self.profile_name, **extra)

        if len(codes) == 1:
            return self._finish(trace_for("forced", codes[0]), built)
        if request not in self.config.request_types:
            return self._finish(trace_for("fallback", self._fallback_code(built), error="request_type_not_enabled"), built)
        if not getattr(self.client, "available", True):
            return self._finish(trace_for("fallback", self._fallback_code(built), error="no_key"), built)
        if not self._budget_left():
            return self._finish(trace_for("fallback", self._fallback_code(built), error="budget"), built)

        pack = self._knowledge(context)
        messages, protocol, listed = build_messages(
            context, self.describer, knowledge_text=pack.text if pack is not None else "",
            detail=self.config.detail, max_options=self.config.max_options, reply=self.config.reply)
        decision = getattr(getattr(self.client, "profile", None), "protocol", "") == "decision"
        if decision:
            messages = decision_messages(context, self.describer, messages, protocol, listed, self.config.reply)
        prompt_text = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        trace = DecisionTrace(
            step_index=int(context.step_index), request_type=request, n_options=len(codes),
            source="fallback", final_code=codes[0], final_index=0, profile=self.profile_name,
            prompt_chars=sum(len(m["content"]) for m in messages),
            prompt_sha=hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16],
            knowledge=pack.as_dict() if pack is not None else {},
        )
        if getattr(self, "keep_prompts", False):
            trace.prompt = messages[1 if decision else -1]["content"]
        index: int | None = None
        attempts_left = 1 + max(0, int(self.config.retries_on_invalid))
        while attempts_left > 0 and index is None:
            attempts_left -= 1
            result = self._complete(messages)
            trace.calls += 1
            trace.latency_seconds += float(result.latency_seconds)
            trace.prompt_tokens += int(result.prompt_tokens)
            trace.completion_tokens += int(result.completion_tokens)
            trace.cached_tokens += int(getattr(result, "cached_tokens", 0) or 0)
            trace.reasoning_tokens += int(getattr(result, "reasoning_tokens", 0) or 0)
            trace.model = result.model or trace.model
            if result.cost is not None:
                trace.cost = (trace.cost or 0.0) + float(result.cost)
            trace.raw = result.text
            if not result.ok:
                trace.error = f"api:{result.error}"
                if trace.first_reply_legal is None:
                    trace.first_reply_legal, trace.first_error = False, trace.error
                # An empty answer (the model spent its whole output budget on hidden
                # reasoning -- seen on real services) is worth one more try; a
                # transport-level failure is not: do not burn another call.
                if result.error == "empty_content" and attempts_left > 0 and self._budget_left():
                    continue
                break
            index, trace.reason, error = (parse_decision if decision else parse_reply)(context, protocol, listed,
                                                                                     result.text)
            trace.error = error
            if trace.first_reply_legal is None:
                trace.first_reply_legal, trace.first_error = index is not None, error
            if index is None and attempts_left > 0 and self._budget_left() and not decision:
                messages = messages + [
                    {"role": "assistant", "content": result.text or ""},
                    {"role": "user", "content": f"上一条回复无法使用（{error}）。请严格按要求只输出一个 JSON 对象。"},
                ]
            elif index is None:
                break
        if index is not None:
            trace.source, trace.llm_index = "llm", int(index)
            trace.final_index, trace.final_code = int(index), codes[int(index)]
        else:
            code = self._fallback_code(built)
            trace.final_code, trace.final_index = code, codes.index(code)
        return self._finish(trace, built)

    # -- discussion --------------------------------------------------------------- #
    def discuss(self, built: Any, question: str, history: Sequence[dict[str, str]] = ()) -> Any:
        """Answer a free-form question about this decision (same view, same knowledge)."""
        return discuss(self.client, built, question, describer=self.describer,
                       selector=self.selector, history=history)

    def summary(self) -> dict[str, Any]:
        by_source: dict[str, int] = {}
        errors: dict[str, int] = {}
        for trace in self.traces:
            by_source[trace.source] = by_source.get(trace.source, 0) + 1
            if trace.error:
                errors[trace.error] = errors.get(trace.error, 0) + 1
        decided = sum(v for k, v in by_source.items() if k != "forced")
        usage = getattr(self.client, "usage", None)
        asked = [t for t in self.traces if t.first_reply_legal is not None]
        by_request: dict[str, dict[str, int]] = {}
        for trace in asked:
            row = by_request.setdefault(trace.request_type, {"asked": 0, "first_legal": 0, "used": 0})
            row["asked"] += 1
            row["first_legal"] += int(bool(trace.first_reply_legal))
            row["used"] += int(trace.source == "llm")
        latencies = sorted(t.latency_seconds for t in asked)

        def pct(q: float) -> float | None:
            return round(latencies[min(len(latencies) - 1, int(q * len(latencies)))], 3) if latencies else None

        return {
            "profile": self.profile_name, "decisions": len(self.traces), "by_source": by_source,
            "llm_rate": round(by_source.get("llm", 0) / decided, 4) if decided else None,
            "errors": errors, "calls": self.calls,
            "usage": usage.as_dict() if usage is not None else {},
            # Legality of the model's *own* answers (the executed action is always
            # legal: unusable replies fall back). ``asked`` = decisions sent to the model.
            "asked": len(asked),
            "first_reply_legal": sum(1 for t in asked if t.first_reply_legal),
            "first_errors": _count(t.first_error for t in asked if t.first_error),
            "by_request": by_request,
            "decision_seconds": {"p50": pct(0.5), "p90": pct(0.9), "max": pct(1.0),
                                 "sum": round(sum(latencies), 2)},
        }


def _count(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[str(value)] = out.get(str(value), 0) + 1
    return out


DISCUSS_SYSTEM = (
    "你是《七圣召唤》的陪练教练，正在和玩家讨论一个具体局面。\n"
    "你只能依据给出的我方可见信息、合法选项与标注了来源的知识作答；对方手牌、骰子与牌库不可见，不要臆测其内容。\n"
    "区分“规则事实”和“策略观点”：前者可以直接引用，后者要说明是经验性判断。回答简洁，必要时引用选项编号。"
)


def discuss(
    client: Any,
    built: Any,
    question: str,
    *,
    describer: DecisionDescriber | None = None,
    selector: Any = None,
    history: Sequence[dict[str, str]] = (),
    max_tokens: int = 700,
) -> Any:
    """Free-form strategy discussion about one decision -> (``ChatResult``, knowledge used)."""
    describer = describer or DecisionDescriber()
    context = built.context
    pack = selector.select(context, query=question) if selector is not None else None
    body = [describer.state_text(context, detail=True),
            "合法选项：\n" + describer.options_text(context)]
    if pack is not None and pack.text:
        body.append("可参考的知识：\n" + pack.text)
    messages = [{"role": "system", "content": DISCUSS_SYSTEM},
                {"role": "user", "content": "\n\n".join(body)}]
    messages += [{"role": str(m["role"]), "content": str(m["content"])} for m in history]
    messages.append({"role": "user", "content": str(question)})
    result = client.complete(messages, max_tokens=max_tokens, want_json=False, tag="discuss")
    return result, (pack.as_dict() if pack is not None else {})


# --------------------------------------------------------------------------- #
# spec parsing
# --------------------------------------------------------------------------- #
def parse_llm_spec(spec: str) -> tuple[str, dict[str, str]]:
    """``<profile>[#k=v,k=v]`` -> (profile, options)."""
    head, _, tail = spec.partition("#")
    options: dict[str, str] = {}
    for part in tail.split(","):
        if not part.strip():
            continue
        key, sep, value = part.partition("=")
        if not sep:
            raise KeyError(f"malformed llm spec option {part!r} in {spec!r}")
        options[key.strip()] = value.strip()
    return head.strip(), options


def build_llm_policy(spec: str, *, seed: int, role: str, call_log: str | None = None) -> LLMPolicy:
    """Build an :class:`LLMPolicy` from the text after ``llm:``."""
    from common.llm_providers import build_client, get_profile
    from common.seeding import derive_seed
    from envs.policy import build_policy
    from reps.knowledge_pack import KnowledgeSelector, get_knowledge_profile

    profile_name, options = parse_llm_spec(spec)
    profile = get_profile(profile_name)
    if "model" in options:
        profile = replace(profile, model=options["model"])
    client = build_client(profile, call_log=call_log, seed=derive_seed(seed, role, "llm", profile_name))
    fallback = build_policy(options.get("fallback", "heuristic"), seed=seed, role=role)
    knowledge = get_knowledge_profile(options.get("kb"))
    selector = KnowledgeSelector(knowledge) if knowledge.enabled else None
    config = LLMPolicyConfig(
        budget_per_game=int(options["budget"]) if "budget" in options else None,
        detail=options.get("detail", "1") not in ("0", "false", "no"),
        reply=options.get("reply", "choice_first"),
    )
    if config.reply not in ("choice_first", "reason_first", "checklist"):
        raise KeyError(f"llm spec option reply must be choice_first, reason_first or checklist, got {config.reply!r}")
    elements = options.get("elements", "0") not in ("0", "false", "no")
    facts = options.get("facts", "0") not in ("0", "false", "no")          # D37: derived facts
    cards = options.get("cards", "0") not in ("0", "false", "no")          # D37: per-game character cards
    name = (f"llm:{profile_name}" + (f"+kb:{knowledge.name}" if selector is not None else "")
            + (f"+{config.reply}" if config.reply != "choice_first" else "") + ("+elements" if elements else "")
            + ("+facts" if facts else "") + ("+cards" if cards else ""))
    from reps.describe import DecisionDescriber

    describer = (DecisionDescriber(elements=elements, facts=facts, cards=cards)
                 if (elements or facts or cards) else None)
    return LLMPolicy(client, fallback, selector=selector, describer=describer, config=config, name=name)


def build_llm_assist_from_spec(spec: str, *, seed: int, role: str) -> Any:
    """``llm-assist:<profile>#base=<spec>[,budget=N]`` -> ``agents.llm_assist.LLMAssistPolicy``."""
    from agents.llm_assist import AssistConfig, LLMAssistPolicy
    from common.llm_providers import build_client
    from envs.policy import _asset_catalog, build_policy

    profile_name, options = parse_llm_spec(spec)
    if "base" not in options:
        raise KeyError("llm-assist spec needs '#base=<policy spec>'")
    client = build_client(profile_name)
    base = build_policy(options["base"], seed=seed, role=role)
    config = AssistConfig(budget_per_game=int(options.get("budget", 8)), model=None)
    return LLMAssistPolicy(base, client, assets=_asset_catalog(), config=config)
