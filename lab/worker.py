"""Worker process for one lab session (``python -m lab.worker <session dir>``).

One process per game: the action codebook is process-global and the engine is not
re-entrant, so concurrent sessions must not share an interpreter. The protocol is
JSON lines -- events on stdout, commands on stdin. Anything else a policy or the
engine prints goes to stderr, so the event stream stays parseable.

The worker is the only writer of ``events.jsonl`` / ``chat.jsonl`` and of the final
status in ``session.json``: if the server goes away the record is still complete
up to the last event.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m lab.worker <session dir>", file=sys.stderr)
        return 2
    # Keep the protocol on the real stdout and send every other print to stderr.
    protocol = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    from common.llm_providers import CALL_LOG_ENV

    from .runner import LabGame
    from .session import CALLS_FILE, SessionStore

    store = SessionStore(Path(args[0]))
    os.environ[CALL_LOG_ENV] = str(store.path / CALLS_FILE)
    spec = store.spec()

    def send(event: Mapping[str, Any]) -> None:
        store.append_event(event)
        if event.get("type") == "chat":
            store.add_chat({k: v for k, v in event.items() if k not in ("type", "n", "t")})
        protocol.write(json.dumps(event, ensure_ascii=False) + "\n")
        protocol.flush()

    def recv() -> Mapping[str, Any]:
        line = sys.stdin.readline()
        if not line:
            return {"cmd": "quit"}        # the server went away: stop cleanly
        try:
            command = json.loads(line)
        except ValueError:
            return {"cmd": "invalid"}
        return command if isinstance(command, dict) else {"cmd": "invalid"}

    try:
        end = LabGame(spec, send, recv).run()
        status = "finished" if end["error"] is None and not end["truncated"] else "aborted"
        store.update_meta(status=status, result={k: v for k, v in end.items() if k not in ("type", "n", "t")})
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        send({"type": "error", "message": message})
        store.update_meta(status="error", result={"error": message})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
