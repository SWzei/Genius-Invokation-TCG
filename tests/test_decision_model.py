"""Decision models (D38, Gemini Decisions API): request shape and option mapping. Fast, offline.

No real API: a fake transport answers like the documented ``/v1beta/decisions`` endpoint
(``answers`` keyed by question name, ``choice`` + ``probabilities`` or ``noul``).
"""

from __future__ import annotations

import json

import pytest

from common.llm_providers import ProviderClient, get_profile
from envs.decks import deck_spec
from envs.match import run_match
from envs.policy import build_policy, expert_policy


def _transport(picks, seen):
    def send(url, headers, body, timeout):
        payload = json.loads(body)
        seen.append({"url": url, "headers": dict(headers), "body": payload})
        answers = {}
        for name, q in payload["questions"].items():
            if q["type"] == "choice":
                key = picks.get("choice", "o0")
                answers[name] = {"type": "choice", "choice": key, "confidence": 0.6,
                                 "probabilities": {k: (0.6 if k == key else 0.4 / (len(q["criteria"]) - 1))
                                                   for k in q["criteria"]}}
            else:
                yes = name in picks.get("yes", ())
                answers[name] = {"type": "noul", "noul": 0.9 if yes else 0.1, "confidence": 0.9}
        out = {"answers": answers, "usage": {"total_input_tokens": 1234, "total_output_tokens": 0}}
        return 200, {}, json.dumps(out).encode()
    return send


def test_decision_protocol_request_and_usage():
    seen = []
    client = ProviderClient(get_profile("gemini-decision-1"), api_key="k-test", transport=_transport({"choice": "o1"}, seen))
    questions = {"action": {"type": "choice", "instructions": "选", "criteria": {"o0": "a", "o1": "b"}}}
    result = client.complete([{"role": "system", "content": "S"}, {"role": "user", "content": "U"},
                              {"role": "decision", "content": json.dumps(questions)}])
    assert result.ok and json.loads(result.text)["action"]["choice"] == "o1"
    assert (result.prompt_tokens, result.completion_tokens) == (1234, 0)
    assert result.cost == pytest.approx(1234 * 0.10 / 1e6)
    sent = seen[-1]
    assert sent["url"].endswith("/v1beta/decisions") and sent["headers"]["x-goog-api-key"] == "k-test"
    assert sent["body"]["model"] == "gemini-decision-1" and sent["body"]["questions"] == questions
    assert sent["body"]["input"] == "S\n\nU"


class _Capture:
    name = "capture"

    def __init__(self, inner):
        self.inner, self.built = inner, []

    def choose(self, built):
        self.built.append(built)
        return self.inner.choose(built)


@pytest.fixture(scope="module")
def contexts():
    capture = _Capture(expert_policy("natlan_battleship"))
    run_match(deck_spec("natlan_battleship"), deck_spec("superconduct_aggro"), capture,
              expert_policy("superconduct_aggro"), seed=11)
    by_kind = {}
    for b in capture.built:
        kind = b.context.request_type.value
        if len(b.context.legal_low_level_codes) > 3:
            by_kind.setdefault(kind, b)
    return by_kind


def test_policy_maps_decisions_onto_legal_options(contexts):
    seen = []
    policy = build_policy("llm:gemini-decision-1#elements=1", seed=1, role="p0")
    policy.client = ProviderClient(get_profile("gemini-decision-1"), api_key="k",
                                   transport=_transport({"choice": "o2", "yes": ("q0", "q2")}, seen))
    action = contexts["action"]
    code = policy.choose(action)
    trace = policy.traces[-1]
    assert trace.source == "llm" and trace.final_index == 2 and code == action.context.legal_low_level_codes[2]
    sent = seen[-1]["body"]
    options = sent["questions"]["action"]["criteria"]
    assert list(options) == [f"o{i}" for i in range(len(options))] and len(options) >= 3
    assert "回复格式" not in sent["input"] and "合法选项" in sent["input"]          # reply format stripped
    swap = contexts["switch_hands"]
    policy.choose(swap)
    trace = policy.traces[-1]
    names = list(seen[-1]["body"]["questions"])
    assert names == [f"q{i}" for i in range(len(names))]
    spec = swap.context.legal_low_level_specs[trace.final_index]
    assert trace.source == "llm" and spec.switch_hand_slot_mask == 0b101          # q0 and q2 answered yes


def test_gemini_per_minute_quota_is_a_rate_limit_not_a_dead_balance():
    from common.llm_providers import classify_http_error

    per_minute = ("You exceeded your current quota, please check your plan and billing details. "
                  "* Quota exceeded for metric: generate_content_free_tier_requests, limit: 15. Please retry in 22.1s.")
    assert classify_http_error(429, "", per_minute) == "rate_limit"
    assert classify_http_error(429, "", "You exceeded your current quota: GenerateRequestsPerDayPerProjectPerModel") == "quota"
    assert classify_http_error(429, "insufficient_quota", "You exceeded your current quota") == "quota"


def test_gemini_list_wrapped_429_keeps_the_retry_hint():
    from common.llm_providers import ProviderClient, classify_http_error

    message = ("You exceeded your current quota, please check your plan and billing details. For more information "
               "on this error, head to: https://aistudio.google.com/docs/rate-limits. To monitor your current usage, "
               "head to: https://ai.dev/rate-limit. \n* Quota exceeded for metric: generativelanguage.googleapis.com/"
               "generate_content_free_tier_requests, limit: 15, model: gemini-3.5-flash-lite, description: Generate "
               "content requests per minute limit exceeded on Free Tier.\nPlease retry in 17.02s.")
    raw = json.dumps([{"error": {"code": 429, "message": message, "status": "RESOURCE_EXHAUSTED"}}]).encode()
    code, text = ProviderClient._error_parts(raw)
    assert code == "429" and "retry in 17.02s" in text
    assert classify_http_error(429, code, text) == "rate_limit"


def test_answer_file_dumps_missing_prompts_and_replays_answers(tmp_path, monkeypatch):
    from common.llm_providers import ANSWER_FILE_ENV, PROMPT_DUMP_ENV, prompt_key

    dump, answers = tmp_path / "dump.jsonl", tmp_path / "answers.json"
    monkeypatch.setenv(PROMPT_DUMP_ENV, str(dump))
    monkeypatch.setenv(ANSWER_FILE_ENV, str(answers))
    client = ProviderClient(get_profile("subagent-sonnet"))
    messages = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    first = client.complete(messages)
    assert not first.ok and first.error == "missing_answer"                    # no network, no key needed
    rows = [json.loads(line) for line in dump.read_text(encoding="utf-8").splitlines()]
    assert rows == [{"key": prompt_key(messages), "messages": messages}]
    answers.write_text(json.dumps({prompt_key(messages): '{"index": 1}'}), encoding="utf-8")
    second = client.complete(messages)
    assert second.ok and second.text == '{"index": 1}'
    assert len(dump.read_text(encoding="utf-8").splitlines()) == 1             # answered prompts are not dumped again
