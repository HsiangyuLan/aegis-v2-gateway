#!/usr/bin/env python3
"""postToolUse: append minimal audit line (best-effort)."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload: dict[str, Any] = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {"_parse_error": True}

    root = os.environ.get("CURSOR_PROJECT_ROOT", os.getcwd())
    log_dir = os.path.join(root, "logs")
    os.makedirs(log_dir, exist_ok=True)
    line = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": "postToolUse",
        "keys": sorted(payload.keys()),
    }
    path = os.path.join(log_dir, "agent-hook-audit.jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    print(json.dumps({}))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except OSError:
        print(json.dumps({}))
        sys.exit(0)
