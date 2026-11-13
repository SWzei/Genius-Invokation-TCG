"""Model profiles and the provider client (PLAN D29). No engine, no real API.

The three wire protocols are exercised against a local HTTP server that speaks the
documented request / response shapes of OpenAI-compatible chat completions,
Anthropic Messages and Gemini ``generateContent`` and checks what the client sent
(auth header, parameter names, system prompt placement). This verifies the
client's side of each protocol; it is not a call to the real services
(``scripts.llm_smoke`` does that with your keys).
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from common.llm_providers import (
    Budget,
    ProfileError,
    ProviderClient,
    build_client,
    get_profile,
    load_profiles,
    profile_from_mapping,
    profile_status,
    redact_secrets,
)

KEY = "sk-test-0123456789abcdef"
MESSAGES = [{"role": "system", "content": "只输出 JSON"}, {"role": "user", "content": "合法选项：\n[0] a\n[1] b"}]


class _Fake(BaseHTTPRequestHandler):
    requests: list[dict] = []
    counters: dict[str, int] = {}

    def log_message(self, *args):  # silence
        pass

    def _reply(self, status, payload, headers=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        record = {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}
        type(self).requests.append(record)
        model = body.get("model") or self.path.split("/models/")[-1].split(":")[0]
        seen = type(self).counters[model] = type(self).counters.get(model, 0) + 1
        if self.path.endswith("/chat/completions"):
            if record["headers"].get("authorization") != f"Bearer {KEY}":
                return self._reply(401, {"error": {"message": f"Incorrect API key provided: {KEY}", "type": "invalid_request_error"}})
            if model == "rate-then-ok" and seen == 1:
                return self._reply(429, {"error": {"message": "Rate limit reached"}}, {"Retry-After": "0"})
            if model == "needs-mct" and "max_tokens" in body:
                return self._reply(400, {"error": {"message": "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."}})
            if model == "no-temp" and "temperature" in body:
                return self._reply(400, {"error": {"message": "Unsupported value: 'temperature' does not support 0 with this model. Only the default (1) value is supported."}})
            if model == "boom":
                return self._reply(500, {"error": {"message": "internal"}})
            if model == "garbage":
                return self._reply(200, b"<html>gateway</html>")
            if model == "empty":
                return self._reply(200, {"choices": [{"message": {"content": None, "reasoning_content": "thinking..."}, "finish_reason": "length"}],
                                         "usage": {"prompt_tokens": 9, "completion_tokens": 64}})
            if model == "slow":
                time.sleep(1.0)
            return self._reply(200, {"choices": [{"message": {"role": "assistant", "content": '{"choice": 1, "reason": "ok"}'}, "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": 120, "completion_tokens": 12}})
        if self.path.endswith("/messages"):
            if record["headers"].get("x-api-key") != KEY or "anthropic-version" not in record["headers"]:
                return self._reply(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
            if model == "overloaded-then-ok" and seen == 1:
                return self._reply(529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
            return self._reply(200, {"type": "message", "role": "assistant", "stop_reason": "end_turn",
                                     "content": [{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": '{"choice": 0, "reason": "claude"}'}],
                                     "usage": {"input_tokens": 200, "output_tokens": 20}})
        if ":generateContent" in self.path:
            if record["headers"].get("x-goog-api-key") != KEY:
                return self._reply(403, {"error": {"code": 403, "message": "API key not valid", "status": "PERMISSION_DENIED"}})
            if model == "blocked":
                return self._reply(200, {"promptFeedback": {"blockReason": "SAFETY"}, "usageMetadata": {"promptTokenCount": 7}})
            return self._reply(200, {"candidates": [{"content": {"role": "model", "parts": [{"text": "plan", "thought": True}, {"text": '{"choice": 1}'}]}, "finishReason": "STOP"}],
                                     "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 5, "thoughtsTokenCount": 30}})
        return self._reply(404, {"error": "unknown path"})


@pytest.fixture(scope="module")
def fake():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(autouse=True)
def _reset():
    _Fake.requests.clear()
    _Fake.counters.clear()


def _client(base, provider, model, **extra):
    profile = profile_from_mapping("t", {"provider": provider, "model": model, "base_url": base,
                                         "api_key_env": "T_KEY", "retry_backoff": 0.0, **extra})
    return ProviderClient(profile, api_key=KEY, sleep=lambda s: None)


# --------------------------------------------------------------------------- #
# profiles and keys
# --------------------------------------------------------------------------- #
def test_presets_cover_the_mainstream_providers():
    expected = {"openai": ("openai", "OPENAI_API_KEY"), "anthropic": ("anthropic", "ANTHROPIC_API_KEY"),
                "claude": ("anthropic", "ANTHROPIC_API_KEY"), "gemini": ("openai", "GEMINI_API_KEY"),
                "gemini-native": ("gemini", "GEMINI_API_KEY"), "deepseek": ("openai", "DEEPSEEK_API_KEY"),
                "glm": ("openai", "ZAI_API_KEY"), "zhipu": ("openai", "ZAI_API_KEY")}
    for provider, (protocol, env) in expected.items():
        profile = profile_from_mapping("p", {"provider": provider, "model": "m"})
        assert profile.protocol == protocol and profile.api_key_env[0] == env and profile.base_url.startswith("https://")
    assert profile_from_mapping("g", {"provider": "glm", "model": "m"}).temperature_min == 0.01
    with pytest.raises(ProfileError):
        profile_from_mapping("x", {"provider": "openai-compatible", "model": "m"})      # needs base_url
    with pytest.raises(ProfileError):
        profile_from_mapping("x", {"provider": "openai"})                                # needs model
    with pytest.raises(ProfileError):
        profile_from_mapping("x", {"provider": "nope", "model": "m"})


def test_config_files_layer_and_never_hold_keys(tmp_path, monkeypatch):
    base = tmp_path / "models.toml"
    base.write_text('[profiles.a]\nprovider = "deepseek"\nmodel = "m1"\n[profiles.a.budget]\nmax_calls = 3\n'
                    '[profiles.b]\nprovider = "anthropic"\nmodel = "m2"\ntemperature = "none"\n', encoding="utf-8")
    local = tmp_path / "local.toml"
    local.write_text('[profiles.a]\nprovider = "deepseek"\nmodel = "m1-local"\nprice_in = 1.0\nprice_out = 2.0\n', encoding="utf-8")
    profiles = load_profiles([base, local])
    assert profiles["a"].model == "m1-local" and profiles["b"].temperature is None
    assert load_profiles([base])["a"].budget.max_calls == 3
    assert "mock" in profiles                                             # always available offline
    bad = tmp_path / "bad.toml"
    bad.write_text('[profiles.c]\nprovider = "openai"\nmodel = "m"\napi_key = "sk-123456789"\n', encoding="utf-8")
    with pytest.raises(ProfileError, match="do not put a key"):
        load_profiles([bad])

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr("common.llm_providers._read_env_file", lambda path: {})
    status = profile_status(profiles["a"])
    assert status["usable"] is False and status["key_present"] is False
    monkeypatch.setenv("DEEPSEEK_API_KEY", KEY)
    status = profile_status(profiles["a"])
    assert status["usable"] is True and KEY not in json.dumps(status)
    assert get_profile("mock:random").model == "random"
    with pytest.raises(ProfileError):
        get_profile("missing", profiles)


def test_repo_config_files_parse():
    from reps.knowledge_pack import load_knowledge_profiles

    profiles = load_profiles()
    assert {"mock", "deepseek-chat", "claude-haiku"} <= set(profiles)
    assert {"none", "rules", "strategy", "rules-strategy"} <= set(load_knowledge_profiles())


# --------------------------------------------------------------------------- #
# wire protocols
# --------------------------------------------------------------------------- #
def test_openai_compatible_protocol(fake):
    client = _client(fake + "/v1", "openai-compatible", "ok", temperature=0.2, max_tokens=77,
                     price_in=2.0, price_out=10.0, extra_body={"reasoning_effort": "low"})
    result = client.complete(MESSAGES, want_json=True)
    assert result.ok and json.loads(result.text)["choice"] == 1
    assert (result.prompt_tokens, result.completion_tokens, result.attempts) == (120, 12, 1)
    assert result.cost == pytest.approx((120 * 2.0 + 12 * 10.0) / 1e6)
    sent = _Fake.requests[-1]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["body"]["messages"] == MESSAGES and sent["body"]["max_tokens"] == 77
    assert sent["body"]["temperature"] == 0.2 and sent["body"]["response_format"] == {"type": "json_object"}
    assert sent["body"]["reasoning_effort"] == "low"
    # the legacy call signature used by agents.llm_assist / coach
    assert client.chat(MESSAGES, max_tokens=5, temperature=0.0, response_format_json=False, model="ignored")
    assert "response_format" not in _Fake.requests[-1]["body"] and _Fake.requests[-1]["body"]["max_tokens"] == 5


def test_anthropic_messages_protocol(fake):
    client = _client(fake, "anthropic", "claude-x", max_tokens=300)
    result = client.complete(MESSAGES, want_json=True)
    assert result.ok and json.loads(result.text) == {"choice": 0, "reason": "claude"}     # thinking block skipped
    assert (result.prompt_tokens, result.completion_tokens, result.finish_reason) == (200, 20, "end_turn")
    sent = _Fake.requests[-1]
    assert sent["path"] == "/messages" and sent["headers"]["anthropic-version"] == "2023-06-01"
    assert sent["body"]["system"] == "只输出 JSON"                                         # system is top-level
    assert sent["body"]["messages"] == [MESSAGES[1]] and sent["body"]["max_tokens"] == 300
    assert "response_format" not in sent["body"] and "authorization" not in sent["headers"]


def test_gemini_generate_content_protocol(fake):
    client = _client(fake, "gemini-native", "gemini-x", temperature="none")
    result = client.complete(MESSAGES + [{"role": "assistant", "content": "x"}, {"role": "user", "content": "y"}],
                             want_json=True)
    assert result.ok and result.text == '{"choice": 1}'                                    # thought part skipped
    assert (result.prompt_tokens, result.completion_tokens) == (50, 35)                    # thoughts are billed output
    sent = _Fake.requests[-1]
    assert sent["path"] == "/models/gemini-x:generateContent"
    assert sent["body"]["systemInstruction"] == {"parts": [{"text": "只输出 JSON"}]}
    assert [c["role"] for c in sent["body"]["contents"]] == ["user", "model", "user"]
    assert sent["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert "temperature" not in sent["body"]["generationConfig"]
    blocked = _client(fake, "gemini-native", "blocked").complete(MESSAGES)
    assert not blocked.ok and blocked.error == "blocked"


def test_glm_temperature_is_clamped_into_the_open_interval(fake):
    client = _client(fake, "glm", "ok", temperature=0.0)
    assert client.complete(MESSAGES).ok
    assert _Fake.requests[-1]["body"]["temperature"] == 0.01


# --------------------------------------------------------------------------- #
# reliability
# --------------------------------------------------------------------------- #
def test_retries_on_rate_limit_and_overload(fake):
    sleeps = []
    profile = profile_from_mapping("t", {"provider": "openai-compatible", "model": "rate-then-ok",
                                         "base_url": fake, "api_key_env": "T", "retries": 2, "retry_backoff": 0.5})
    client = ProviderClient(profile, api_key=KEY, sleep=sleeps.append)
    result = client.complete(MESSAGES)
    assert result.ok and result.attempts == 2 and sleeps == [0.5] and client.usage.retries == 1
    claude = _client(fake, "anthropic", "overloaded-then-ok")
    assert claude.complete(MESSAGES).attempts == 2


def test_errors_are_classified_and_bounded(fake):
    boom = _client(fake, "openai-compatible", "boom", retries=2)
    result = boom.complete(MESSAGES)
    assert not result.ok and result.error == "http_500" and result.attempts == 3 and result.text is None
    assert _client(fake, "openai-compatible", "garbage").complete(MESSAGES).error == "bad_response"
    empty = _client(fake, "openai-compatible", "empty").complete(MESSAGES)
    assert empty.error == "empty_content" and empty.completion_tokens == 64       # still accounted
    slow = _client(fake, "openai-compatible", "slow", timeout=0.2, retries=0).complete(MESSAGES)
    assert slow.error == "timeout"
    down = _client("http://127.0.0.1:9", "openai-compatible", "ok", retries=0).complete(MESSAGES)
    assert down.error == "network"
    # a wrong key is not retried and never echoed back
    profile = profile_from_mapping("t", {"provider": "openai-compatible", "model": "ok", "base_url": fake, "api_key_env": "T"})
    wrong = ProviderClient(profile, api_key="sk-wrong-000000000000", sleep=lambda s: None).complete(MESSAGES)
    assert wrong.error == "auth" and wrong.attempts == 1 and KEY not in wrong.detail and "sk-wrong" not in wrong.detail
    missing = ProviderClient(profile, api_key="").complete(MESSAGES)
    assert missing.error == "no_key" and missing.attempts == 0


def test_parameter_rejections_are_adapted_once(fake):
    client = _client(fake, "openai", "needs-mct")
    result = client.complete(MESSAGES)
    assert result.ok and result.adapted == ("max_tokens->max_completion_tokens",) and result.attempts == 2
    assert "max_completion_tokens" in _Fake.requests[-1]["body"] and "max_tokens" not in _Fake.requests[-1]["body"]
    assert client.complete(MESSAGES).attempts == 1                       # remembered for later calls
    no_temp = _client(fake, "openai", "no-temp", temperature=0.0)
    result = no_temp.complete(MESSAGES)
    assert result.ok and result.adapted == ("temperature omitted",)
    assert "temperature" not in _Fake.requests[-1]["body"]


# --------------------------------------------------------------------------- #
# budget, accounting, log
# --------------------------------------------------------------------------- #
def test_budget_stops_calls_before_they_are_made(fake):
    client = _client(fake, "openai-compatible", "ok", budget={"max_calls": 2})
    assert client.complete(MESSAGES).ok and client.complete(MESSAGES).ok
    refused = client.complete(MESSAGES)
    assert refused.error == "budget" and "max_calls" in refused.detail and len(_Fake.requests) == 2
    by_tokens = _client(fake, "openai-compatible", "ok", budget={"max_tokens": 130})
    assert by_tokens.complete(MESSAGES).ok and by_tokens.complete(MESSAGES).error == "budget"
    by_cost = _client(fake, "openai-compatible", "ok", price_in=1000.0, price_out=1000.0, budget={"max_cost": 0.1})
    assert by_cost.complete(MESSAGES).ok and by_cost.budget_left() == "max_cost"
    assert build_client("mock", budget=Budget(max_calls=1)).profile.budget.max_calls == 1


def test_usage_and_call_log_hold_no_secret_and_no_prompt(fake, tmp_path):
    log = tmp_path / "calls.jsonl"
    profile = profile_from_mapping("logged", {"provider": "openai-compatible", "model": "ok", "base_url": fake,
                                              "api_key_env": "T", "price_in": 1.0, "price_out": 1.0})
    client = ProviderClient(profile, api_key=KEY, call_log=log, sleep=lambda s: None)
    client.complete(MESSAGES, tag="decision")
    ProviderClient(profile_from_mapping("logged", {"provider": "openai-compatible", "model": "boom", "base_url": fake,
                                                   "api_key_env": "T", "retries": 0}),
                   api_key=KEY, call_log=log).complete(MESSAGES)
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [r["ok"] for r in rows] == [True, False] and rows[1]["error"] == "http_500"
    assert rows[0]["tag"] == "decision" and rows[0]["latency_seconds"] >= 0 and rows[0]["cost"] == pytest.approx(132 / 1e6)
    text = log.read_text(encoding="utf-8")
    assert KEY not in text and "合法选项" not in text and len(rows[0]["prompt_sha"]) == 16
    usage = client.usage.as_dict()
    assert usage["calls"] == 1 and usage["prompt_tokens"] == 120 and usage["cost"] == pytest.approx(132 / 1e6)
    assert redact_secrets(f"key={KEY} and AIzaSyA0123456789abcdef", (KEY,)).count("***") == 2


def test_mock_provider_behaviours():
    assert json.loads(build_client("mock").complete(MESSAGES).text)["choice"] == 0
    assert json.loads(build_client("mock:last").complete(MESSAGES).text)["choice"] == 1
    assert json.loads(build_client("mock:out_of_range").complete(MESSAGES).text)["choice"] > 1
    assert build_client("mock:error").complete(MESSAGES).error == "network"
    a = [json.loads(build_client("mock:random", seed=3).complete(MESSAGES).text)["choice"] for _ in range(3)]
    b = [json.loads(build_client("mock:random", seed=3).complete(MESSAGES).text)["choice"] for _ in range(3)]
    assert a == b                                                         # seeded, reproducible
