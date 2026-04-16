#!/usr/bin/env python3
"""beforeShellExecution: gate shell strings (stdin JSON with command)."""

from __future__ import annotations

import json
import re
import sys
from typing import Any


def main() -> None:
    try:
        data: dict[str, Any] = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        print(json.dumps({"permission": "allow"}))
        sys.exit(0)

    cmd = str(data.get("command", ""))
    if re.search(r"rm\s+-rf\s+/", cmd, re.I):
        print(
            json.dumps(
                {
                    "permission": "deny",
                    "user_message": "Blocked: rm -rf / style command.",
                    "agent_message": "Shell hook denied destructive rm.",
                }
            )
        )
        sys.exit(0)
    if re.search(r"curl\s+.*\|\s*(?:sudo\s+)?bash", cmd, re.I):
        print(
            json.dumps(
                {
                    "permission": "deny",
                    "user_message": "Blocked: curl | bash.",
                    "agent_message": "Shell hook denied curl pipe to bash.",
                }
            )
        )
        sys.exit(0)
    print(json.dumps({"permission": "allow"}))
    sys.exit(0)


if __name__ == "__main__":
    main()
