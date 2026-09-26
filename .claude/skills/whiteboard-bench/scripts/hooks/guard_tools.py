"""PreToolUse hook for wbench-player: deny every tool that isn't a board tool.

The agent's `tools: mcp__wbench__*` already limits what it can call. This hook
is the second lock, so a misconfigured or inherited tool can't reach the repo
(where tasks/*.json holds the checks and reference solutions).
"""
import json
import sys

ALLOWED_PREFIX = "mcp__wbench__"


def decide(event: dict) -> dict | None:
    tool = event.get("tool_name", "")
    if tool.startswith(ALLOWED_PREFIX):
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"{tool} is not available in a WhiteboardBench session; "
                                    "use the whiteboard tools only.",
    }}


if __name__ == "__main__":
    out = decide(json.load(sys.stdin))
    if out:
        print(json.dumps(out))
