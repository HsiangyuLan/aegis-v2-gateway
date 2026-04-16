#!/usr/bin/env python3
"""preToolUse: block destructive tool payloads and heuristic secret/PII leakage (stdin JSON)."""

from __future__ import annotations

import json
import re
import sys
from typing import Any, Iterator

# High-signal patterns only — heuristic DLP, not a substitute for gateway NER redaction.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"AKIA[0-9A-Z]{16}"), "possible AWS access key id"),
    (re.compile(r"sk_live_[0-9a-zA-Z]{24,}"), "possible Stripe live secret"),
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "possible API secret key sk- prefix"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36,}"), "possible GitHub PAT"),
    (re.compile(r"xox[baprs]-[0-9a-zA-Z-]{10,}"), "possible Slack token"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "PEM private key block"),
    (re.compile(r"PRIVATE KEY-----"), "private key material"),
)

_PII_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "possible US SSN pattern"),
)


def _deny(msg: str) -> None:
    try:
        print(json.dumps({"permission": "deny", "user_message": msg, "agent_message": msg}))
    except (TypeError, ValueError) as exc:
        print(json.dumps({"permission": "deny", "user_message": f"Hook emit error: {exc}"}))
    sys.exit(0)


def _allow() -> None:
    try:
        print(json.dumps({"permission": "allow"}))
    except (TypeError, ValueError) as exc:
        print(json.dumps({"permission": "deny", "user_message": f"Hook emit error: {exc}"}))
        sys.exit(0)
    sys.exit(0)


def _iter_strings(obj: Any) -> Iterator[str]:
    """Depth-first collection of string leaves for nested hook JSON."""
    try:
        if isinstance(obj, str):
            if obj:
                yield obj
        elif isinstance(obj, dict):
            for v in obj.values():
                yield from _iter_strings(v)
        elif isinstance(obj, list):
            for item in obj:
                yield from _iter_strings(item)
    except (TypeError, AttributeError, RecursionError):
        return


def _scan_destructive(blob: str) -> str | None:
    """Return deny message if a destructive shell pattern is present."""
    try:
        if re.search(r"rm\s+-rf\s+/", blob, re.I):
            return "Hook: blocked recursive delete against filesystem root in tool input."
        if re.search(r"curl\s+[^\n]*\|\s*(?:sudo\s+)?bash", blob, re.I):
            return "Hook: blocked remote payload piped into shell in tool input."
        if re.search(r"mkfs\.|dd\s+if=/dev/zero", blob, re.I):
            return "Hook: blocked destructive disk command in tool input."
    except re.error as exc:
        return f"Hook: destructive scan regex error: {exc}"
    return None


def _scan_secrets_and_pii(text: str) -> str | None:
    """Return deny message if a secret or high-signal PII pattern matches."""
    try:
        for rx, label in _SECRET_PATTERNS:
            if rx.search(text):
                return f"Hook: blocked {label} in tool payload (pre-write secret scan)."
        for rx, label in _PII_PATTERNS:
            if rx.search(text):
                return f"Hook: blocked {label} in tool payload (pre-write PII heuristic scan)."
    except re.error as exc:
        return f"Hook: secret/PII scan regex error: {exc}"
    return None


def main() -> None:
    try:
        raw = sys.stdin.read()
        data: dict[str, Any] = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        if "--fail-closed" in sys.argv:
            _deny(f"Invalid hook JSON: {exc}")
        _allow()

    try:
        blob = json.dumps(data, default=str)
    except (TypeError, ValueError) as exc:
        _deny(f"Hook: cannot serialize payload for scan: {exc}")

    destructive = _scan_destructive(blob)
    if destructive:
        _deny(destructive)

    texts: list[str] = [blob]
    try:
        texts.extend(s for s in _iter_strings(data))
    except (TypeError, AttributeError) as exc:
        _deny(f"Hook: payload walk error: {exc}")

    combined = "\n".join(texts)
    leak = _scan_secrets_and_pii(combined)
    if leak:
        _deny(leak)

    _allow()


if __name__ == "__main__":
    try:
        main()
    except OSError as exc:
        try:
            print(json.dumps({"permission": "deny", "user_message": str(exc)}))
        except (TypeError, ValueError):
            print('{"permission":"deny","user_message":"Hook OS error"}')
        sys.exit(0)
    except Exception as exc:
        try:
            print(
                json.dumps(
                    {
                        "permission": "deny",
                        "user_message": f"Hook unexpected error ({type(exc).__name__}): {exc}",
                    }
                )
            )
        except (TypeError, ValueError):
            print('{"permission":"deny","user_message":"Hook fatal error"}')
        sys.exit(0)
