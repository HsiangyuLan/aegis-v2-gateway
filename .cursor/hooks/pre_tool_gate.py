#!/usr/bin/env python3
"""preToolUse: block obviously destructive tool payloads (stdin JSON)."""

from __future__ import annotations

import json
import re
import sys
from typing import Any


def _deny(msg: str) -> None:
    print(json.dumps({"permission": "deny", "user_message": msg, "agent_message": msg}))
    sys.exit(0)


def _allow() -> None:
    print(json.dumps({"permission": "allow"}))
    sys.exit(0)


def main() -> None:
    try:
        raw = sys.stdin.read()
        data: dict[str, Any] = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        if "--fail-closed" in sys.argv:
            _deny(f"Invalid hook JSON: {exc}")
        _allow()

    blob = json.dumps(data, default=str)
    if re.search(r"rm\s+-rf\s+/", blob, re.I):
        _deny("Hook: blocked rm -rf / pattern in tool input.")
    if re.search(r"curl\s+[^\n]*\|\s*(?:sudo\s+)?bash", blob, re.I):
        _deny("Hook: blocked curl | bash pattern.")
    if re.search(r"mkfs\.|dd\s+if=/dev/zero", blob, re.I):
        _deny("Hook: blocked destructive disk command pattern.")
    _allow()


if __name__ == "__main__":
    try:
        main()
    except OSError as exc:
        print(json.dumps({"permission": "deny", "user_message": str(exc)}))
        sys.exit(0)
