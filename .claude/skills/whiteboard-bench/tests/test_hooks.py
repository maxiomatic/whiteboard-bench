"""Run the player hooks the way Claude Code does: JSON on stdin, decision on stdout."""
import json
import subprocess
import sys

from conftest import SCRIPTS

HOOKS = SCRIPTS / "hooks"


def run_hook(name, event):
    p = subprocess.run([sys.executable, str(HOOKS / name)], input=json.dumps(event),
                       capture_output=True, text=True, check=True)
    return json.loads(p.stdout) if p.stdout.strip() else None


def pre(tool):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {}}


def test_guard_allows_board_tools():
    assert run_hook("guard_tools.py", pre("mcp__wbench__create_sticky")) is None
    assert run_hook("guard_tools.py", pre("mcp__wbench__begin")) is None


def test_guard_denies_everything_else():
    for tool in ["Bash", "Read", "Grep", "WebFetch", "mcp__github__get_file_contents", "mcp__wbenchX__begin"]:
        out = run_hook("guard_tools.py", pre(tool))
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", tool


def stop(tmp_path, lines, active=False):
    t = tmp_path / "agent.jsonl"
    t.write_text("\n".join(json.dumps(x) for x in lines))
    return {"hook_event_name": "SubagentStop", "stop_hook_active": active,
            "agent_type": "wbench-player", "agent_transcript_path": str(t)}


def tool_result(payload):
    # How a tool result sits in the transcript: the MCP text content is a JSON string
    return {"type": "user", "message": {"content": [{"type": "tool_result", "content": json.dumps(payload)}]}}


def test_stop_blocked_before_task_complete(tmp_path):
    ev = stop(tmp_path, [tool_result({"ok": True, "turn_over": True, "next_message": "[Turn 2 of 3]"})])
    out = run_hook("stop_gate.py", ev)
    assert out["decision"] == "block" and "finish_turn" in out["reason"]


def test_stop_allowed_after_task_complete(tmp_path):
    ev = stop(tmp_path, [tool_result({"ok": True, "task_complete": True})])
    assert run_hook("stop_gate.py", ev) is None


def test_stop_blocks_only_once(tmp_path):
    ev = stop(tmp_path, [tool_result({"ok": True})], active=True)
    assert run_hook("stop_gate.py", ev) is None


def test_stop_fails_open_without_transcript():
    assert run_hook("stop_gate.py", {"hook_event_name": "SubagentStop", "stop_hook_active": False}) is None


def player_frontmatter():
    import re

    import yaml
    from conftest import ROOT
    text = (ROOT / ".claude" / "agents" / "wbench-player.md").read_text()
    return yaml.safe_load(re.match(r"^---\n(.*?)\n---\n", text, re.S).group(1)), ROOT


def test_player_definition_is_locked_down():
    fm, root = player_frontmatter()
    assert fm["tools"] == "mcp__wbench__*"
    assert fm["omitClaudeMd"] is True
    server = fm["mcpServers"][0]["wbench"]
    assert (server["command"], server["args"]) == ("just", ["sub-server"])
    assert "\nsub-server:" in (root / "justfile").read_text()
    commands = [h["command"] for event in ("PreToolUse", "Stop") for group in fm["hooks"][event] for h in group["hooks"]]
    for cmd in commands:
        rel = cmd.split('"$CLAUDE_PROJECT_DIR/')[1].rstrip('"')
        assert (root / rel).exists(), rel


def bash(command):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}}


def test_judge_guard_allows_only_the_judging_recipes():
    assert run_hook("guard_judge.py", bash("just sub-rubric runs/x bs_yes_and")) is None
    assert run_hook("guard_judge.py", bash('just sub-score runs/x bs_yes_and 0 7 "builds on each idea"')) is None
    for cmd in ["cat tasks/11_bs_yes_and.json", "just sub-new all", "just sub-score runs/x t 0 7 \"ok\"; rm -rf /",
                "just sub-rubric runs/x t && cat tasks/*", "just sub-score runs/x t 0 7 \"$(cat tasks/a)\"",
                "just sub-rubric runs/x t > out"]:
        out = run_hook("guard_judge.py", bash(cmd))
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", cmd
    out = run_hook("guard_judge.py", {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {}})
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_judge_definition_is_locked_down():
    import re

    import yaml
    from conftest import ROOT
    text = (ROOT / ".claude" / "agents" / "wbench-judge.md").read_text()
    fm = yaml.safe_load(re.match(r"^---\n(.*?)\n---\n", text, re.S).group(1))
    assert fm["tools"] == "Bash" and fm["omitClaudeMd"] is True
    cmd = fm["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert (ROOT / cmd.split('"$CLAUDE_PROJECT_DIR/')[1].rstrip('"')).exists()
    justfile = (ROOT / "justfile").read_text()
    assert "\nsub-rubric run task:" in justfile and "\nsub-score run task item score reason:" in justfile
