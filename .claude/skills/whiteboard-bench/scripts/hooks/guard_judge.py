"""PreToolUse hook for wbench-judge: only the two judging recipes, nothing else.

The judge reads its task's materials with `just sub-rubric` and records a
score with `just sub-score`. Any other tool, or a command that tries to
chain or redirect, is denied.
"""
import json
import re
import sys

ALLOWED = re.compile(r"^just sub-(rubric|score) ")
FORBIDDEN = re.compile(r"[;&|`<>\n]|\$\(")


def decide(event: dict) -> dict | None:
    tool = event.get("tool_name", "")
    command = (event.get("tool_input") or {}).get("command", "")
    if tool == "Bash" and ALLOWED.match(command) and not FORBIDDEN.search(command):
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "A WhiteboardBench judge may only run `just sub-rubric <run> <task>` and "
                                    "`just sub-score <run> <task> <item> <score> \"<reason>\"` "
                                    "(no ; & | ` < > or $( in the command).",
    }}


if __name__ == "__main__":
    out = decide(json.load(sys.stdin))
    if out:
        print(json.dumps(out))
