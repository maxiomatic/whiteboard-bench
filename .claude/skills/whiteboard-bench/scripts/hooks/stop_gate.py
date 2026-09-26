"""Stop hook for wbench-player (runs as SubagentStop): don't quit mid-session.

If the player tries to stop before the board server has said
`task_complete`, block once and tell it to finish. The second attempt
(`stop_hook_active`) is let through, so a stuck player can't loop forever;
the unfinished task then shows up as missing in the report.
"""
import json
import pathlib
import sys

MARKERS = ('"task_complete": true', '\\"task_complete\\": true')
REASON = ("The whiteboard session is not over yet. Handle the current request, then call "
          "finish_turn and keep going until a result says task_complete.")


def completed(transcript: str | None) -> bool:
    if not transcript:
        return True  # nothing to check: fail open rather than trap the player
    path = pathlib.Path(transcript).expanduser()
    if not path.exists():
        return True
    text = path.read_text(errors="replace")
    return any(m in text for m in MARKERS)


def decide(event: dict) -> dict | None:
    if event.get("stop_hook_active"):
        return None
    if completed(event.get("agent_transcript_path") or event.get("transcript_path")):
        return None
    return {"decision": "block", "reason": REASON}


if __name__ == "__main__":
    out = decide(json.load(sys.stdin))
    if out:
        print(json.dumps(out))
