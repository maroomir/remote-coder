#!/usr/bin/env python3
"""
Cursor project hook: block a small set of destructive shell commands.

Reads JSON from stdin (beforeShellExecution). Writes JSON to stdout.
If stdin is not JSON or python3 fails, exits 0 without printing (fail-open).
"""
from __future__ import annotations

import json
import re
import sys

# (regex, short label for messages)
_DENY: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"git\s+reset\b.*--hard\b", re.I), "git reset --hard"),
    (re.compile(r"git\s+clean\b(?:\s+-\S*)*\s-(?:[a-z]*f[a-z]*d|[a-z]*d[a-z]*f)\b", re.I), "git clean removing files (-fd etc.)"),
    (re.compile(r"\brm\b(?:\s+\S+)*\s-(?:[^\s]*f[^\s]*r[^\s]*|[^\s]*r[^\s]*f[^\s]*)\b", re.I), "rm -rf / similar"),
    (re.compile(r"git\s+push\b.*--force\b", re.I), "git push --force"),
    (re.compile(r"git\s+push\b(?:\s+\S+)*\s-f\b", re.I), "git push -f"),
]


def _deny_payload(label: str) -> dict[str, str]:
    return {
        "permission": "deny",
        "user_message": (
            f"remote-coder hook blocked a destructive pattern: {label}. "
            "Run from a normal terminal if you truly need this."
        ),
        "agent_message": f"blocked_dangerous_shell:{label}",
    }


def main() -> None:
    raw = sys.stdin.read()
    if not raw.strip():
        print(json.dumps({"permission": "allow"}))
        return

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"permission": "allow"}))
        return

    command = (data.get("command") or "").strip()
    if not command:
        print(json.dumps({"permission": "allow"}))
        return

    for pattern, label in _DENY:
        if pattern.search(command):
            print(json.dumps(_deny_payload(label)))
            return

    print(json.dumps({"permission": "allow"}))


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        pass
