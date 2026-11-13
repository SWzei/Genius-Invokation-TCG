"""Check model profiles: one tiny real call each, reported without the key.

    python -m scripts.llm_smoke                 # every profile that has a key
    python -m scripts.llm_smoke deepseek-chat claude-haiku
    python -m scripts.llm_smoke --list          # show profiles and whether a key is set (no calls)

Each call sends a one-line prompt asking for a small JSON object, so it also
checks the JSON switch of the provider. Calls cost money; nothing here runs in the
test suite.
"""

from __future__ import annotations

import argparse
import json

from common.llm import extract_json_object
from common.llm_providers import build_client, load_profiles, profile_status

PROMPT = [{"role": "system", "content": "只输出一个 JSON 对象，不要输出其他文字。"},
          {"role": "user", "content": '请原样回复：{"choice": 0, "reason": "ok"}'}]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("profiles", nargs="*")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=64)
    args = parser.parse_args(argv)
    profiles = load_profiles()
    names = args.profiles or [n for n, p in profiles.items() if p.protocol != "mock"]
    rows = []
    for name in names:
        if name not in profiles:
            rows.append({"profile": name, "ok": False, "error": "unknown profile"})
            continue
        status = profile_status(profiles[name])
        row = {"profile": name, "provider": status["provider"], "model": status["model"],
               "key_present": status["key_present"]}
        if args.list:
            rows.append(row)
            continue
        if not status["usable"]:
            rows.append({**row, "ok": False, "error": "no_key", "detail": f"set one of {status['api_key_env']}"})
            continue
        client = build_client(profiles[name])
        result = client.complete(PROMPT, max_tokens=args.max_tokens, want_json=True, tag="smoke")
        parsed = extract_json_object(result.text)
        rows.append({**row, **result.as_dict(), "json_ok": bool(parsed and "choice" in parsed),
                     "reply": (result.text or "")[:120]})
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    return 0 if all(r.get("ok", True) for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
