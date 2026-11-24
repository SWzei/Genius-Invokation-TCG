"""Model profiles and a provider-neutral chat client (standard library only).

``common.llm`` keeps the original single OpenAI-compatible client. This module
adds what the experiment platform needs on top of it:

* **profiles** -- named model configurations loaded from ``configs/models.toml``
  (plus an optional git-ignored ``configs/models.local.toml`` or the file named by
  ``GITCG_MODELS_CONFIG``). A profile holds no secret: it names the *environment
  variable(s)* that carry the API key, resolved from the process environment or
  the repo ``.env`` at call time;
* **three wire protocols** -- ``openai`` (chat completions; also DeepSeek, GLM,
  Gemini's OpenAI endpoint, and local OpenAI-compatible servers), ``anthropic``
  (Messages API) and ``gemini`` (``generateContent``) -- plus ``mock`` for offline
  runs;
* **reliability** -- bounded retries with backoff on 429 / 5xx / timeouts,
  ``Retry-After`` support, one automatic adaptation for the two parameter
  rejections seen in practice (``max_tokens`` vs ``max_completion_tokens``;
  ``temperature`` not accepted), and an error *kind* on every failure;
* **accounting** -- per-call latency, token counts, optional cost from the
  profile's own prices, a hard budget (calls / tokens / cost) and an optional
  JSONL call log that never contains the key.

``ProviderClient.chat`` has the same signature and ``None``-on-failure contract as
``common.llm.LLMClient.chat``, so ``agents.llm_assist`` and ``coach`` accept it.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import threading
import random
import re
import socket
import time
try:
    import tomllib
except ModuleNotFoundError:  # Python <=3.10 (e.g. the cluster): tomli backport
    import tomli as tomllib  # type: ignore
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from common.llm import LLMConfig, LLMUsage, _ENV_FILE, _read_env_file
from common.paths import REPO_ROOT

MODELS_ENV = "GITCG_MODELS_CONFIG"
CALL_LOG_ENV = "GITCG_LLM_CALL_LOG"
DEFAULT_MODELS_FILE = REPO_ROOT / "configs" / "models.toml"
LOCAL_MODELS_FILE = REPO_ROOT / "configs" / "models.local.toml"
PROTOCOLS = ("openai", "anthropic", "gemini", "decision", "file", "mock")
ANSWER_FILE_ENV = "GITCG_ANSWER_FILE"      # D38 "file" protocol: {prompt key: reply text}
PROMPT_DUMP_ENV = "GITCG_PROMPT_DUMP"      # D38 "file" protocol: unanswered prompts are appended here

# Provider presets: wire protocol, default endpoint, the env var(s) that carry the
# key. Model ids are deliberately *not* preset -- they change; a profile names one.
PRESETS: dict[str, dict[str, Any]] = {
    "openai": {"protocol": "openai", "base_url": "https://api.openai.com/v1",
               "api_key_env": ("OPENAI_API_KEY",)},
    "anthropic": {"protocol": "anthropic", "base_url": "https://api.anthropic.com/v1",
                  "api_key_env": ("ANTHROPIC_API_KEY",)},
    "gemini": {"protocol": "openai",
               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "api_key_env": ("GEMINI_API_KEY", "GOOGLE_API_KEY")},
    "gemini-native": {"protocol": "gemini",
                      "base_url": "https://generativelanguage.googleapis.com/v1beta",
                      "api_key_env": ("GEMINI_API_KEY", "GOOGLE_API_KEY")},
    # D38: Gemini Decisions API (``gemini-decision-1``): no generated text, a calibrated
    # choice among named options (or yes/no) per question; see ``decision_questions``.
    "gemini-decisions": {"protocol": "decision", "base_url": "https://generativelanguage.googleapis.com/v1beta",
                         "api_key_env": ("GEMINI_API_KEY", "GOOGLE_API_KEY")},
    # D38: GroqCloud (OpenAI-compatible).
    "groq": {"protocol": "openai", "base_url": "https://api.groq.com/openai/v1", "api_key_env": ("GROQ_API_KEY",)},
    "deepseek": {"protocol": "openai", "base_url": "https://api.deepseek.com",
                 "api_key_env": ("DEEPSEEK_API_KEY",)},
    # Zhipu documents the sampling temperature as the open interval (0, 1).
    "glm": {"protocol": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "api_key_env": ("ZAI_API_KEY", "ZHIPUAI_API_KEY"), "temperature_min": 0.01},
    # Any OpenAI-compatible server (vLLM, Ollama, LM Studio, a gateway ...).
    "openai-compatible": {"protocol": "openai", "api_key_env": ()},
    # D38: replies come from a file written by someone else (e.g. an isolated agent that
    # answered the dumped prompts); see ``prompt_key``. No network.
    "answer-file": {"protocol": "file", "base_url": "file://", "api_key_env": ()},
    "mock": {"protocol": "mock", "base_url": "mock://", "api_key_env": ()},
}
PRESETS["claude"] = PRESETS["anthropic"]
PRESETS["zhipu"] = PRESETS["glm"]

_RETRY_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})
_MAX_RETRY_AFTER = 30.0
# Error kinds that will not go away by retrying or by asking again later in the
# same run: the client stops sending requests after the first one (see
# ``ProviderClient.disabled``), so a run cannot silently degrade into its fallback.
FATAL_KINDS = frozenset({"auth", "quota", "model_not_found", "no_key"})
# Provider error codes / wording seen on real services. Zhipu answers "balance
# exhausted" with HTTP 429 + code 1113 (not a rate limit: retrying cannot help)
# and "no such model" with HTTP 400 + code 1211; DeepSeek uses HTTP 402; OpenAI
# uses 429 + ``insufficient_quota``.
# Zhipu codes per docs.bigmodel.cn/cn/faq/api-code (all HTTP 429): 1113 balance, 1308/1310
# plan limit reached, 1309/1314 plan expired, 1313 fair-use restriction, 1316-1321 limit
# reached and no balance to overflow into. 1302/1305 are real rate limits and stay retryable.
_QUOTA_CODES = frozenset({"1113", "1308", "1309", "1310", "1313", "1314", "1315", "1316", "1317", "1318",
                          "1319", "1320", "1321", "insufficient_quota", "insufficient_balance",
                          "billing_not_active"})
_QUOTA_WORDS = ("余额不足", "资源包", "欠费", "使用上限", "套餐已到期", "insufficient balance",
                "insufficient_quota", "exceeded your current quota", "usage limit reached", "billing")
_MODEL_CODES = frozenset({"1211", "1311", "model_not_found"})      # 1311: model not in the plan
_MODEL_WORDS = ("模型不存在", "model not found", "does not exist", "no such model", "model_not_found")
_BLOCK_CODES = frozenset({"1301", "content_filter"})


def classify_http_error(status: int, code: str, message: str) -> str:
    """Error kind for a non-2xx answer (``code`` is the provider's own code, may be empty)."""
    lowered = message.lower()
    if status in (401, 403):
        return "auth"
    # Gemini answers a per-minute free-tier limit with 429 "exceeded your current quota ...
    # Please retry in 22s": a rate limit, not an exhausted balance (D38).
    if status == 429 and ("per minute" in lowered or "perminute" in lowered or "please retry in" in lowered) \
            and "perday" not in lowered and "per day" not in lowered:
        return "rate_limit"
    if status == 402 or code in _QUOTA_CODES or any(word in lowered for word in _QUOTA_WORDS):
        return "quota"
    if code in _MODEL_CODES or (status in (400, 404) and any(word in lowered for word in _MODEL_WORDS)):
        return "model_not_found"
    if code in _BLOCK_CODES:
        return "blocked"
    if status == 429:
        return "rate_limit"
    return f"http_{status}"


@dataclass(frozen=True)
class Budget:
    """Hard caps for one client instance (``None`` = unlimited)."""

    max_calls: int | None = None
    max_tokens: int | None = None          # prompt + completion
    max_cost: float | None = None          # in the profile's price currency

    def as_dict(self) -> dict[str, Any]:
        return {"max_calls": self.max_calls, "max_tokens": self.max_tokens, "max_cost": self.max_cost}


@dataclass(frozen=True)
class ModelProfile:
    name: str
    provider: str
    protocol: str
    model: str
    base_url: str = ""
    api_key_env: tuple[str, ...] = ()
    temperature: float | None = 0.0         # None = do not send the parameter
    temperature_min: float | None = None    # clamp (providers that reject 0)
    max_tokens: int = 512
    max_tokens_param: str = "max_tokens"    # "max_completion_tokens" for newer OpenAI models
    top_p: float | None = None
    timeout: float = 60.0
    json_mode: bool = True                  # send the provider's JSON switch when asked for JSON
    retries: int = 2
    retry_backoff: float = 1.0
    extra_body: Mapping[str, Any] = field(default_factory=dict)
    extra_headers: Mapping[str, str] = field(default_factory=dict)
    anthropic_version: str = "2023-06-01"
    # Prices per 1,000,000 tokens, as *you* entered them; None = cost unknown.
    price_in: float | None = None
    price_out: float | None = None
    price_cached_in: float | None = None    # cache-hit input price; None = same as price_in
    currency: str = "USD"
    budget: Budget = field(default_factory=Budget)
    notes: str = ""

    @property
    def needs_key(self) -> bool:
        return bool(self.api_key_env)

    def public_dict(self) -> dict[str, Any]:
        """Everything about the profile that is safe to log (there is no secret in it)."""
        return {
            "name": self.name, "provider": self.provider, "protocol": self.protocol,
            "model": self.model, "base_url": self.base_url, "api_key_env": list(self.api_key_env),
            "temperature": self.temperature, "max_tokens": self.max_tokens,
            "max_tokens_param": self.max_tokens_param, "top_p": self.top_p, "timeout": self.timeout,
            "json_mode": self.json_mode, "retries": self.retries,
            "extra_body": dict(self.extra_body), "price_in": self.price_in,
            "price_out": self.price_out, "price_cached_in": self.price_cached_in,
            "currency": self.currency, "budget": self.budget.as_dict(),
        }


class ProfileError(ValueError):
    pass


def profile_from_mapping(name: str, raw: Mapping[str, Any]) -> ModelProfile:
    provider = str(raw.get("provider", "openai-compatible")).lower()
    if provider not in PRESETS:
        raise ProfileError(f"profile {name!r}: unknown provider {provider!r} (known: {sorted(PRESETS)})")
    preset = PRESETS[provider]
    protocol = str(raw.get("protocol", preset["protocol"])).lower()
    if protocol not in PROTOCOLS:
        raise ProfileError(f"profile {name!r}: unknown protocol {protocol!r}")
    model = str(raw.get("model", "mock" if protocol == "mock" else "")).strip()
    if not model:
        raise ProfileError(f"profile {name!r}: 'model' is required")
    base_url = str(raw.get("base_url", preset.get("base_url", ""))).rstrip("/")
    if protocol != "mock" and not base_url:
        raise ProfileError(f"profile {name!r}: 'base_url' is required for provider {provider!r}")
    for forbidden in ("api_key", "key", "token", "secret"):
        if forbidden in raw:
            raise ProfileError(
                f"profile {name!r}: do not put a key in the config file; name the environment "
                f"variable in 'api_key_env' and set it in the environment or the repo .env"
            )
    key_env = raw.get("api_key_env", preset.get("api_key_env", ()))
    if isinstance(key_env, str):
        key_env = (key_env,) if key_env else ()
    budget_raw = raw.get("budget", {}) or {}
    temperature = raw.get("temperature", 0.0)
    if isinstance(temperature, str):
        temperature = None if temperature.lower() in ("none", "omit", "") else float(temperature)
    return ModelProfile(
        name=name, provider=provider, protocol=protocol, model=model, base_url=base_url,
        api_key_env=tuple(str(v) for v in key_env),
        temperature=None if temperature is None else float(temperature),
        temperature_min=raw.get("temperature_min", preset.get("temperature_min")),
        max_tokens=int(raw.get("max_tokens", 512)),
        max_tokens_param=str(raw.get("max_tokens_param", "max_tokens")),
        top_p=raw.get("top_p"),
        timeout=float(raw.get("timeout", 60.0)),
        json_mode=bool(raw.get("json_mode", True)),
        retries=int(raw.get("retries", 2)),
        retry_backoff=float(raw.get("retry_backoff", 1.0)),
        extra_body=dict(raw.get("extra_body", {}) or {}),
        extra_headers={str(k): str(v) for k, v in (raw.get("extra_headers", {}) or {}).items()},
        anthropic_version=str(raw.get("anthropic_version", "2023-06-01")),
        price_in=raw.get("price_in"), price_out=raw.get("price_out"),
        price_cached_in=raw.get("price_cached_in"),
        currency=str(raw.get("currency", "USD")),
        budget=Budget(budget_raw.get("max_calls"), budget_raw.get("max_tokens"), budget_raw.get("max_cost")),
        notes=str(raw.get("notes", "")),
    )


def config_paths() -> list[Path]:
    """Config files read, in order; later files override earlier ones by profile name."""
    paths = [DEFAULT_MODELS_FILE, LOCAL_MODELS_FILE]
    override = os.environ.get(MODELS_ENV)
    if override:
        paths.append(Path(override))
    return [p for p in paths if p.exists()]


def load_profiles(paths: Sequence[str | Path] | None = None) -> dict[str, ModelProfile]:
    """All configured profiles. The built-in ``mock`` profile is always present."""
    profiles: dict[str, ModelProfile] = {
        "mock": profile_from_mapping("mock", {"provider": "mock", "model": "first"}),
    }
    for path in ([Path(p) for p in paths] if paths is not None else config_paths()):
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        for name, raw in (data.get("profiles") or {}).items():
            profiles[str(name)] = profile_from_mapping(str(name), raw)
    return profiles


def get_profile(name: str, profiles: Mapping[str, ModelProfile] | None = None) -> ModelProfile:
    """Resolve ``name``; ``mock`` / ``mock:<behaviour>`` and ``env`` are built in."""
    table = dict(profiles) if profiles is not None else load_profiles()
    if name in table:
        return table[name]
    if name.startswith("mock:"):
        return profile_from_mapping(name, {"provider": "mock", "model": name.split(":", 1)[1]})
    if name == "env":
        # The legacy single-model environment config (GITCG_LLM_* / DEEPSEEK_*).
        from common.llm import load_llm_config

        legacy = load_llm_config()
        if legacy is None:
            raise ProfileError("profile 'env': GITCG_LLM_BASE_URL / _API_KEY / _MODEL are not all set")
        env_name = "GITCG_LLM_API_KEY" if _lookup_env(("GITCG_LLM_API_KEY",)) else "DEEPSEEK_API_KEY"
        return profile_from_mapping("env", {
            "provider": "openai-compatible", "base_url": legacy.base_url, "model": legacy.model,
            "api_key_env": env_name, "max_tokens": legacy.max_tokens,
            "temperature": legacy.temperature, "timeout": legacy.timeout,
        })
    raise ProfileError(f"unknown model profile {name!r} (configured: {sorted(table)})")


def _lookup_env(names: Sequence[str]) -> str | None:
    file_env: dict[str, str] | None = None
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
        if file_env is None:
            file_env = _read_env_file(_ENV_FILE)
        if file_env.get(name):
            return file_env[name]
    return None


def resolve_api_key(profile: ModelProfile) -> str | None:
    return _lookup_env(profile.api_key_env) if profile.api_key_env else None


def profile_status(profile: ModelProfile) -> dict[str, Any]:
    """Whether a profile is usable right now, without revealing the key."""
    key = resolve_api_key(profile)
    return {**profile.public_dict(),
            "key_present": bool(key) or not profile.needs_key,
            "usable": profile.protocol == "mock" or bool(key) or not profile.needs_key}


# --------------------------------------------------------------------------- #
# results / usage
# --------------------------------------------------------------------------- #
@dataclass
class ChatResult:
    text: str | None
    error: str | None = None            # kind: auth | rate_limit | timeout | network | http_<n> |
    #                                     bad_response | empty_content | budget | no_key | blocked
    detail: str = ""
    status: int | None = None
    latency_seconds: float = 0.0
    attempts: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0              # part of prompt_tokens served from the provider's cache
    reasoning_tokens: int = 0           # part of completion_tokens spent on hidden reasoning
    cost: float | None = None
    model: str = ""
    finish_reason: str | None = None
    adapted: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.error is None and self.text is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "error": self.error, "detail": self.detail[:300], "status": self.status,
            "latency_seconds": round(self.latency_seconds, 3), "attempts": self.attempts,
            "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens, "reasoning_tokens": self.reasoning_tokens,
            "cost": None if self.cost is None else round(self.cost, 6), "model": self.model,
            "finish_reason": self.finish_reason, "adapted": list(self.adapted),
        }


@dataclass
class ProviderUsage(LLMUsage):
    cost: float = 0.0
    cost_known: bool = True
    by_error: dict[str, int] = field(default_factory=dict)
    retries: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0

    def as_dict(self) -> dict[str, Any]:
        out = super().as_dict()
        out.update({"cost": round(self.cost, 6) if self.cost_known else None,
                    "by_error": dict(self.by_error), "retries": self.retries,
                    "cached_tokens": self.cached_tokens, "reasoning_tokens": self.reasoning_tokens})
        return out


Transport = Callable[[str, Mapping[str, str], bytes, float], tuple[int, Mapping[str, str], bytes]]


def _urllib_transport(url: str, headers: Mapping[str, str], body: bytes, timeout: float):
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:      # non-2xx: still a response we can classify
        return int(exc.code), dict(exc.headers.items()) if exc.headers else {}, exc.read() or b""


def redact_secrets(text: str, secrets: Sequence[str | None] = ()) -> str:
    out = str(text)
    for secret in secrets:
        if secret and len(secret) >= 6:
            out = out.replace(secret, "***")
    return re.sub(r"\b(sk|key|AIza)[-_A-Za-z0-9]{12,}", "***", out)


def _split_system(messages: Sequence[Mapping[str, str]]) -> tuple[str, list[dict[str, str]]]:
    system = "\n\n".join(str(m["content"]) for m in messages if m.get("role") == "system")
    rest = [{"role": str(m["role"]), "content": str(m["content"])} for m in messages if m.get("role") != "system"]
    return system, rest


_OPTION_LINE = re.compile(r"^\[(\d+)\]", re.M)


def prompt_key(messages: Sequence[Mapping[str, str]]) -> str:
    """Stable key of a prompt for the ``file`` protocol."""
    return hashlib.sha256(json.dumps([dict(m) for m in messages], ensure_ascii=False,
                                     sort_keys=True).encode("utf-8")).hexdigest()


_FILE_LOCK = threading.Lock()
_ANSWERS: dict[str, tuple[float, dict[str, str]]] = {}


def _file_reply(messages: Sequence[Mapping[str, str]]) -> ChatResult:
    key = prompt_key(messages)
    path = os.environ.get(ANSWER_FILE_ENV)
    answers: dict[str, str] = {}
    if path and Path(path).exists():
        mtime = Path(path).stat().st_mtime
        with _FILE_LOCK:
            cached = _ANSWERS.get(path)
            if cached is None or cached[0] != mtime:
                cached = (mtime, json.loads(Path(path).read_text(encoding="utf-8")))
                _ANSWERS[path] = cached
        answers = cached[1]
    chars = sum(len(str(m.get("content", ""))) for m in messages)
    if key in answers:
        text = str(answers[key])
        return ChatResult(text, attempts=1, prompt_tokens=chars // 2, completion_tokens=len(text) // 2,
                          finish_reason="stop")
    dump = os.environ.get(PROMPT_DUMP_ENV)
    if dump:
        with _FILE_LOCK, open(dump, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"key": key, "messages": [dict(m) for m in messages]}, ensure_ascii=False) + "\n")
    return ChatResult(None, error="missing_answer", detail=f"no answer for prompt {key[:16]}", attempts=1)


def _mock_reply(behaviour: str, messages: Sequence[Mapping[str, str]], rng: random.Random) -> str:
    """Offline stand-in for a model. Behaviours: ``first`` | ``last`` | ``random`` |
    ``invalid`` (unparseable) | ``out_of_range`` | ``error`` (transport failure)."""
    # The decision prompt is the newest user message that lists options (a later
    # "please answer in JSON" follow-up lists none).
    users = [str(m["content"]) for m in reversed(messages) if m.get("role") == "user"]
    user = next((text for text in users if _OPTION_LINE.search(text)), users[0] if users else "")
    indices = [int(n) for n in _OPTION_LINE.findall(user)]
    count = (max(indices) + 1) if indices else 1
    if behaviour == "invalid":
        return "I think the best move is to attack."
    if behaviour == "out_of_range":
        return json.dumps({"choice": count + 7, "reason": "mock out of range"})
    choice = {"first": 0, "last": count - 1}.get(behaviour)
    if choice is None:
        choice = rng.randrange(count)
    return json.dumps({"choice": choice, "reroll": [], "swap": [], "reason": f"mock:{behaviour}"},
                      ensure_ascii=False)


class ProviderClient:
    """Chat client for one :class:`ModelProfile`."""

    def __init__(
        self,
        profile: ModelProfile,
        *,
        api_key: str | None = None,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        call_log: str | Path | None = None,
        seed: int = 0,
    ) -> None:
        self.profile = profile
        self._key = api_key if api_key is not None else resolve_api_key(profile)
        self._transport = transport or _urllib_transport
        self._sleep = sleep
        self._rng = random.Random(seed)
        self.call_log = Path(call_log) if call_log else None
        self.usage = ProviderUsage()
        self.last: ChatResult | None = None
        #: set after a fatal error (``FATAL_KINDS``): later calls fail at once, no request.
        self.disabled: ChatResult | None = None
        self._last_details: tuple[int, int] = (0, 0)
        self._max_tokens_param = profile.max_tokens_param
        self._send_temperature = profile.temperature is not None
        # ``common.llm`` compatibility (callers read ``client.config.model``).
        self.config = LLMConfig(base_url=profile.base_url or "mock://", model=profile.model,
                                api_key="", timeout=profile.timeout, max_tokens=profile.max_tokens,
                                temperature=profile.temperature or 0.0, name=profile.name)

    # -- availability / budget ------------------------------------------------ #
    @property
    def available(self) -> bool:
        return self.profile.protocol == "mock" or bool(self._key) or not self.profile.needs_key

    def budget_left(self) -> str | None:
        """``None`` when another call is allowed, else which cap is exhausted."""
        budget, usage = self.profile.budget, self.usage
        if budget.max_calls is not None and usage.calls + usage.errors >= budget.max_calls:
            return "max_calls"
        if budget.max_tokens is not None and usage.prompt_tokens + usage.completion_tokens >= budget.max_tokens:
            return "max_tokens"
        if budget.max_cost is not None and usage.cost >= budget.max_cost:
            return "max_cost"
        return None

    # -- request construction -------------------------------------------------- #
    def _temperature(self, override: float | None) -> float | None:
        if not self._send_temperature:
            return None
        value = self.profile.temperature if override is None else override
        if value is None:
            return None
        if self.profile.temperature_min is not None:
            value = max(float(value), float(self.profile.temperature_min))
        return float(value)

    def _request(self, messages, max_tokens: int, temperature: float | None, want_json: bool):
        profile = self.profile
        # A named User-Agent: some Cloudflare-fronted APIs (Groq) refuse urllib's default one (403/1010).
        headers = {"Content-Type": "application/json", "User-Agent": "gitcg-bench/1.0", **profile.extra_headers}
        if profile.protocol == "openai":
            url = profile.base_url if profile.base_url.endswith("/chat/completions") \
                else f"{profile.base_url}/chat/completions"
            if self._key:
                headers["Authorization"] = f"Bearer {self._key}"
            body: dict[str, Any] = {"model": profile.model,
                                    "messages": [dict(m) for m in messages],
                                    self._max_tokens_param: int(max_tokens)}
            if temperature is not None:
                body["temperature"] = temperature
            if profile.top_p is not None:
                body["top_p"] = profile.top_p
            if want_json and profile.json_mode:
                body["response_format"] = {"type": "json_object"}
        elif profile.protocol == "anthropic":
            url = f"{profile.base_url}/messages"
            headers["x-api-key"] = self._key or ""
            headers["anthropic-version"] = profile.anthropic_version
            system, rest = _split_system(messages)
            body = {"model": profile.model, "max_tokens": int(max_tokens), "messages": rest}
            if system:
                body["system"] = system
            if temperature is not None:
                body["temperature"] = temperature
            if profile.top_p is not None:
                body["top_p"] = profile.top_p
        elif profile.protocol == "gemini":
            url = f"{profile.base_url}/models/{profile.model}:generateContent"
            headers["x-goog-api-key"] = self._key or ""
            system, rest = _split_system(messages)
            config: dict[str, Any] = {"maxOutputTokens": int(max_tokens)}
            if temperature is not None:
                config["temperature"] = temperature
            if profile.top_p is not None:
                config["topP"] = profile.top_p
            if want_json and profile.json_mode:
                config["responseMimeType"] = "application/json"
            body = {"contents": [{"role": "model" if m["role"] == "assistant" else "user",
                                  "parts": [{"text": m["content"]}]} for m in rest],
                    "generationConfig": config}
            if system:
                body["systemInstruction"] = {"parts": [{"text": system}]}
        elif profile.protocol == "decision":
            url = f"{profile.base_url}/decisions"
            headers["x-goog-api-key"] = self._key or ""
            questions = next((json.loads(m["content"]) for m in messages if m.get("role") == "decision"), {})
            text = "\n\n".join(str(m["content"]) for m in messages if m.get("role") in ("system", "user"))
            body = {"model": profile.model, "input": text, "questions": questions}
        else:  # pragma: no cover - guarded by profile validation
            raise ProfileError(f"unsupported protocol {profile.protocol!r}")
        body.update(profile.extra_body)
        return url, headers, body

    def _parse(self, payload: Mapping[str, Any]) -> tuple[str | None, int, int, str | None, str | None]:
        """-> (text, prompt_tokens, completion_tokens, finish_reason, error_kind).

        Cache-hit and reasoning token counts (when the provider reports them) are
        left in ``self._last_details`` for the caller."""
        protocol = self.profile.protocol
        self._last_details = (0, 0)
        try:
            if protocol == "openai":
                choice = payload["choices"][0]
                text = choice["message"].get("content")
                usage = payload.get("usage") or {}
                tokens = int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)
                finish = choice.get("finish_reason")
                self._last_details = (
                    int((usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0),
                    int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0))
            elif protocol == "anthropic":
                text = "".join(str(block.get("text", "")) for block in payload["content"]
                               if block.get("type") == "text")
                usage = payload.get("usage") or {}
                tokens = int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)
                finish = payload.get("stop_reason")
                self._last_details = (int(usage.get("cache_read_input_tokens", 0) or 0), 0)
            elif protocol == "decision":
                usage = payload.get("usage") or {}
                tokens = int(usage.get("total_input_tokens", 0) or 0), 0
                text = json.dumps(payload["answers"], ensure_ascii=False)
                finish = "stop"
            else:  # gemini
                usage = payload.get("usageMetadata") or {}
                tokens = (int(usage.get("promptTokenCount", 0) or 0),
                          int(usage.get("candidatesTokenCount", 0) or 0) + int(usage.get("thoughtsTokenCount", 0) or 0))
                self._last_details = (int(usage.get("cachedContentTokenCount", 0) or 0),
                                      int(usage.get("thoughtsTokenCount", 0) or 0))
                candidates = payload.get("candidates") or []
                if not candidates:
                    reason = (payload.get("promptFeedback") or {}).get("blockReason")
                    return None, tokens[0], tokens[1], reason, "blocked" if reason else "bad_response"
                parts = (candidates[0].get("content") or {}).get("parts") or []
                text = "".join(str(p.get("text", "")) for p in parts if not p.get("thought"))
                finish = candidates[0].get("finishReason")
        except (KeyError, IndexError, TypeError, AttributeError):
            return None, 0, 0, None, "bad_response"
        if isinstance(text, list):       # content parts (some OpenAI-compatible servers)
            text = "".join(str(p.get("text", "")) for p in text if isinstance(p, dict))
        if not text or not str(text).strip():
            return None, tokens[0], tokens[1], finish, "empty_content"
        return str(text), tokens[0], tokens[1], finish, None

    @staticmethod
    def _error_parts(raw: bytes) -> tuple[str, str]:
        """-> (provider error code, message) of a non-2xx body; both may be empty."""
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return "", raw.decode("utf-8", "replace")[:1000]
        if isinstance(payload, list) and len(payload) == 1:      # Gemini's OpenAI endpoint wraps errors in a list
            payload = payload[0]
        error = payload.get("error") if isinstance(payload, dict) else None
        # Keep enough of the message to see Gemini's "... per minute ... Please retry in 17s" tail (D38).
        if isinstance(error, dict):
            code = str(error.get("code") or error.get("type") or "")
            return code, str(error.get("message") or error.get("type") or error)[:1000]
        return "", str(error or payload)[:1000]

    @classmethod
    def _error_message(cls, raw: bytes) -> str:
        return cls._error_parts(raw)[1]

    def _adapt(self, status: int, message: str) -> str | None:
        """One-shot fixes for parameter rejections; returns what was changed."""
        if status != 400:
            return None
        lowered = message.lower()
        if self.profile.protocol == "openai" and self._max_tokens_param == "max_tokens" \
                and "max_completion_tokens" in lowered:
            self._max_tokens_param = "max_completion_tokens"
            return "max_tokens->max_completion_tokens"
        if self._send_temperature and "temperature" in lowered and any(
            word in lowered for word in ("unsupported", "not support", "does not support", "only the default")
        ):
            self._send_temperature = False
            return "temperature omitted"
        return None

    # -- call ------------------------------------------------------------------ #
    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        want_json: bool = False,
        tag: str = "",
    ) -> ChatResult:
        profile = self.profile
        started = time.perf_counter()
        result = self._complete(messages, max_tokens or profile.max_tokens, temperature, want_json)
        result.latency_seconds = time.perf_counter() - started
        result.model = profile.model
        if profile.price_in is not None and profile.price_out is not None:
            cached = min(result.cached_tokens, result.prompt_tokens)
            cached_price = profile.price_in if profile.price_cached_in is None else profile.price_cached_in
            result.cost = ((result.prompt_tokens - cached) * float(profile.price_in)
                           + cached * float(cached_price)
                           + result.completion_tokens * float(profile.price_out)) / 1_000_000.0
        usage = self.usage
        if result.ok:
            usage.record(prompt=result.prompt_tokens, completion=result.completion_tokens,
                         seconds=result.latency_seconds)
        else:
            usage.errors += 1
            usage.prompt_tokens += result.prompt_tokens
            usage.completion_tokens += result.completion_tokens
            usage.total_seconds += result.latency_seconds
            usage.by_error[result.error or "unknown"] = usage.by_error.get(result.error or "unknown", 0) + 1
        usage.retries += max(0, result.attempts - 1)
        usage.cached_tokens += result.cached_tokens
        usage.reasoning_tokens += result.reasoning_tokens
        if result.error in FATAL_KINDS and result.error != "no_key" and self.disabled is None:
            self.disabled = result
        if result.cost is None:
            if result.prompt_tokens or result.completion_tokens:
                usage.cost_known = False
        else:
            usage.cost += result.cost
        self.last = result
        self._log(messages, result, tag)
        return result

    def _complete(self, messages, max_tokens: int, temperature: float | None, want_json: bool) -> ChatResult:
        profile = self.profile
        exhausted = self.budget_left()
        if exhausted is not None:
            return ChatResult(None, error="budget", detail=f"{exhausted} reached")
        if self.disabled is not None:
            return ChatResult(None, error=self.disabled.error, status=self.disabled.status,
                              detail=f"not sent (earlier fatal error): {self.disabled.detail}"[:300])
        if profile.protocol == "mock":
            if profile.model == "error":
                return ChatResult(None, error="network", detail="mock transport failure", attempts=1)
            text = _mock_reply(profile.model, messages, self._rng)
            prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
            return ChatResult(text, attempts=1, prompt_tokens=prompt_chars // 2,
                              completion_tokens=len(text) // 2, finish_reason="stop")
        if profile.protocol == "file":
            return _file_reply(messages)
        if not self.available:
            return ChatResult(None, error="no_key",
                              detail=f"none of {list(profile.api_key_env)} is set")
        adapted: list[str] = []
        attempts = 0
        last = ChatResult(None, error="network", detail="not attempted")
        retries_left = max(0, int(profile.retries))
        while True:
            attempts += 1
            url, headers, body = self._request(messages, max_tokens, self._temperature(temperature), want_json)
            try:
                status, response_headers, raw = self._transport(
                    url, headers, json.dumps(body, ensure_ascii=False).encode("utf-8"), profile.timeout)
            except (TimeoutError, socket.timeout) as exc:
                last = ChatResult(None, error="timeout", detail=str(exc))
                status, response_headers, raw = None, {}, b""
            except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as exc:
                # HTTPException: e.g. IncompleteRead when the connection drops mid-response (D32)
                reason = getattr(exc, "reason", exc)
                kind = "timeout" if isinstance(reason, (TimeoutError, socket.timeout)) else "network"
                last = ChatResult(None, error=kind, detail=redact_secrets(str(exc), (self._key,)))
                status, response_headers, raw = None, {}, b""
            if status is not None:
                if 200 <= status < 300:
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                    except ValueError:
                        last = ChatResult(None, error="bad_response", detail="response is not JSON", status=status)
                    else:
                        text, p_tok, c_tok, finish, kind = self._parse(payload)
                        cached, reasoning = self._last_details
                        detail = "" if kind is None else f"finish_reason={finish}"
                        if kind == "empty_content" and reasoning:
                            detail += (f"; {reasoning} of {c_tok} output tokens were hidden reasoning -- "
                                       "raise max_tokens, or lower the reasoning effort / turn thinking off"
                                       " if the model allows it")
                        last = ChatResult(text, error=kind, status=status, prompt_tokens=p_tok,
                                          completion_tokens=c_tok, finish_reason=finish, detail=detail,
                                          cached_tokens=cached, reasoning_tokens=reasoning)
                    last.attempts, last.adapted = attempts, tuple(adapted)
                    return last
                code, message = self._error_parts(raw)
                message = redact_secrets(message, (self._key,))
                change = self._adapt(status, message)
                if change is not None and change not in adapted:
                    adapted.append(change)
                    continue            # retry immediately with the adapted request
                kind = classify_http_error(status, code, message)
                last = ChatResult(None, error=kind, detail=f"[{code}] {message}" if code else message,
                                  status=status)
                if status not in _RETRY_STATUS or kind in FATAL_KINDS or kind == "blocked":
                    break
            if retries_left <= 0:
                break
            retries_left -= 1
            delay = min(_MAX_RETRY_AFTER, profile.retry_backoff * (2 ** (attempts - 1)))
            retry_after = {k.lower(): v for k, v in dict(response_headers).items()}.get("retry-after")
            if not retry_after and last.error == "rate_limit":          # Gemini: "Please retry in 22.5s"
                hint = re.search(r"retry in ([0-9.]+)s", last.detail or "")
                retry_after = hint.group(1) if hint else None
            if retry_after:
                try:
                    delay = min(_MAX_RETRY_AFTER, max(delay, float(retry_after)))
                except ValueError:
                    pass
            self._sleep(delay)
        last.attempts, last.adapted = attempts, tuple(adapted)
        return last

    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format_json: bool = False,
        model: str | None = None,   # accepted for signature compatibility; the profile decides
    ) -> str | None:
        return self.complete(messages, max_tokens=max_tokens, temperature=temperature,
                             want_json=response_format_json).text

    def _log(self, messages, result: ChatResult, tag: str) -> None:
        if self.call_log is None:
            return
        digest = hashlib.sha256(json.dumps([dict(m) for m in messages], ensure_ascii=False,
                                           sort_keys=True).encode("utf-8")).hexdigest()[:16]
        row = {"t": round(time.time(), 3), "profile": self.profile.name, "provider": self.profile.provider,
               "tag": tag, "prompt_sha": digest,
               "prompt_chars": sum(len(str(m.get("content", ""))) for m in messages), **result.as_dict()}
        try:
            self.call_log.parent.mkdir(parents=True, exist_ok=True)
            with self.call_log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass   # accounting must never break a decision


def build_client(
    profile: str | ModelProfile,
    *,
    budget: Budget | None = None,
    call_log: str | Path | None = None,
    seed: int = 0,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ProviderClient:
    """Client for a profile name or object. Check ``client.available`` before relying on it."""
    resolved = get_profile(profile) if isinstance(profile, str) else profile
    if budget is not None:
        resolved = replace(resolved, budget=budget)
    # A run (lab session, arena) names one call log for every client it builds.
    call_log = call_log or os.environ.get(CALL_LOG_ENV) or None
    return ProviderClient(resolved, call_log=call_log, seed=seed, transport=transport, sleep=sleep)
