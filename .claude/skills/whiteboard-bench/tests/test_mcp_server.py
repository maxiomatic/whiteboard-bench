"""Drive mcp_server.py over stdio exactly as Claude Code would, replaying reference solutions."""
import json
import os
import sys

import anyio
import pytest
from conftest import ROOT, SCRIPTS
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from wbench.agents.replay import ReplayAgent

SERVER = StdioServerParameters(command=sys.executable, args=[str(SCRIPTS / "mcp_server.py")])


def params(run):
    return StdioServerParameters(command=SERVER.command, args=SERVER.args,
                                 env={**os.environ, "WBENCH_RUN_DIR": str(run)})


class McpEnv:
    """The env interface ReplayAgent expects, backed by MCP tool calls."""

    def __init__(self, session):
        self.session = session
        self.done = False
        self.next_message = None
        self.complete = False
        self.seen = []

    def call(self, name, args=None):
        res = anyio.from_thread.run(self.session.call_tool, name, args or {})
        out = json.loads(res.content[0].text)
        self.seen.append(out)
        if out.get("turn_over"):
            self.done, self.next_message = True, out["next_message"]
        if out.get("task_complete"):
            self.done = self.complete = True
        return out


async def call(session, name, args):
    res = await session.call_tool(name, args)
    return json.loads(res.content[0].text)


def replay_through_mcp(run, task_id):
    task = json.loads(next((ROOT / "tasks").glob(f"*_{task_id}.json")).read_text())

    async def main():
        async with stdio_client(params(run)) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            assert {"begin", "create_sticky", "finish_turn"} <= names
            begun = await call(s, "begin", {"task_id": task_id})
            assert begun["ok"], begun
            again = await call(s, "begin", {"task_id": task_id})
            assert not again["ok"] and "already started" in again["error"]

            env = McpEnv(s)
            agent = ReplayAgent()
            agent.load(task)
            agent.start({"task_id": task_id})

            def play():
                message, turns = begun["message"], 0
                while not env.complete:
                    env.done = False
                    agent.run_turn(message, env)
                    message, turns = env.next_message, turns + 1
                    assert turns < 20, "session never completed"
                return turns

            turns = await anyio.to_thread.run_sync(play)
            after = await call(s, "get_board", {})
            assert not after["ok"] and "session is over" in after["error"]
            return turns, [begun, *env.seen]

    turns, seen = anyio.run(main)
    result = json.loads((run / task_id / "result.json").read_text())
    return turns, result, seen


def test_single_turn_task_scores_perfect(make_run):
    run = make_run("dg_org_chart")
    turns, result, seen = replay_through_mcp(run, "dg_org_chart")
    assert result["score"] == 1.0
    assert turns == 1
    assert not any('"score"' in json.dumps(out) for out in seen), "scores must never reach the player"


def test_mid_turn_event_is_delivered(make_run):
    """Task 16 fires a human event mid-turn; the replay only passes if the player saw it."""
    run = make_run("co_protected_region")
    task = json.loads(next((ROOT / "tasks").glob("*_co_protected_region.json")).read_text())
    assert any("at_call" in ev for t in task["turns"] for ev in t.get("events", []))
    _, result, _ = replay_through_mcp(run, "co_protected_region")
    assert result["score"] == 1.0
    assert not result["skipped_events"]


def test_multi_turn_task(make_run):
    run = make_run("pl_kanban_updates")
    turns, result, _ = replay_through_mcp(run, "pl_kanban_updates")
    assert result["score"] == 1.0
    assert turns >= 3


def test_tools_before_begin_and_unknown_task(make_run):
    run = make_run("dg_org_chart")

    async def main():
        async with stdio_client(params(run)) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            early = await call(s, "get_board", {})
            assert not early["ok"] and "begin" in early["error"]
            other = await call(s, "begin", {"task_id": "bs_yes_and"})
            assert not other["ok"] and "not part of this run" in other["error"]

    anyio.run(main)


def test_task_can_only_be_claimed_once(make_run):
    run = make_run("dg_org_chart")

    async def begin_once():
        async with stdio_client(params(run)) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            return await call(s, "begin", {"task_id": "dg_org_chart"})

    assert anyio.run(begin_once)["ok"]
    second = anyio.run(begin_once)
    assert not second["ok"] and "already claimed" in second["error"]


def status(run, task):
    return json.loads((run / task / "status.json").read_text())


def test_status_lifecycle_ends_done(make_run):
    run = make_run("dg_org_chart")
    replay_through_mcp(run, "dg_org_chart")
    st = status(run, "dg_org_chart")
    assert st["state"] == "done" and st["calls"] > 0


def test_disconnect_mid_task_marks_abandoned(make_run):
    run = make_run("pl_kanban_updates")

    async def main():
        async with stdio_client(params(run)) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            assert (await call(s, "begin", {"task_id": "pl_kanban_updates"}))["ok"]
            await call(s, "get_board", {})
            assert status(run, "pl_kanban_updates")["state"] == "playing"

    anyio.run(main)
    assert status(run, "pl_kanban_updates")["state"] == "abandoned"
    assert not (run / "pl_kanban_updates" / "result.json").exists()


def test_retried_task_locks_out_the_stale_player(make_run):
    import wb
    run = make_run("dg_org_chart")

    async def main():
        async with stdio_client(params(run)) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            assert (await call(s, "begin", {"task_id": "dg_org_chart"}))["ok"]
            wb.retry(run, "dg_org_chart")  # the orchestrator gave up on this player
            await call(s, "get_board", {})
            assert not (run / "dg_org_chart").exists(), "stale player recreated the task dir"

    anyio.run(main)
    assert not (run / "dg_org_chart").exists()


def custom_task_run(tmp_path, make_run, task_id, change):
    """A run whose one task is a modified copy of a real task file."""
    task = json.loads(next((ROOT / "tasks").glob(f"*_{task_id}.json")).read_text())
    change(task)
    path = tmp_path / f"custom_{task_id}.json"
    path.write_text(json.dumps(task))
    run = make_run(task_id)
    m = json.loads((run / "manifest.json").read_text())
    m["files"][task_id] = str(path)  # absolute path: the server joins it onto tasks/ and pathlib keeps it
    (run / "manifest.json").write_text(json.dumps(m))
    return run


def test_harness_failure_is_reported_not_hung(tmp_path, make_run):
    """If the harness can't even build the board, begin must say so instead of blocking the player."""
    run = custom_task_run(tmp_path, make_run, "dg_org_chart",
                          lambda t: t.update(initial_elements=[{"type": "nonsense", "x": 0, "y": 0}]))

    async def main():
        async with stdio_client(params(run)) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            with anyio.fail_after(20):
                return await call(s, "begin", {"task_id": "dg_org_chart"})

    out = anyio.run(main)
    assert not out["ok"] and "unknown element type" in out["error"]
    assert status(run, "dg_org_chart")["state"] == "error"


def test_budget_exhaustion_ends_the_turn(tmp_path, make_run):
    """A player that never calls finish_turn is cut off at max_calls_per_turn and told what comes next."""
    run = custom_task_run(tmp_path, make_run, "dg_org_chart", lambda t: t.update(max_calls_per_turn=3))

    async def main():
        async with stdio_client(params(run)) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            assert (await call(s, "begin", {"task_id": "dg_org_chart"}))["ok"]
            outs = [await call(s, "get_board", {}) for _ in range(5)]
            return outs

    outs = anyio.run(main)
    assert all(o["ok"] for o in outs[:3])  # the budget allows 3 calls
    assert "budget" in outs[3]["error"] and outs[3]["task_complete"] is True  # single-turn task: that was the end
    assert "session is over" in outs[4]["error"]
    result = json.loads((run / "dg_org_chart" / "result.json").read_text())
    assert result["stats"]["tool_calls"] == 3 and result["score"] < 1.0


def test_no_active_run_exits_with_a_hint(tmp_path, monkeypatch):
    import mcp_server
    monkeypatch.delenv("WBENCH_RUN_DIR", raising=False)
    monkeypatch.setattr(mcp_server, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="just sub-new"):
        mcp_server.active_run_dir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / ".active").write_text(str(tmp_path / "some-run") + "\n")
    assert mcp_server.active_run_dir() == tmp_path / "some-run"


def test_harness_failure_mid_session_ends_it_cleanly(tmp_path, make_run):
    """A crash between turns (here: a broken human event before turn 2) reaches the player as an error."""
    def break_turn_two(task):
        task["turns"][1].setdefault("events", []).insert(0, {"op": "create", "element": {"type": "nonsense"}})

    run = custom_task_run(tmp_path, make_run, "pl_kanban_updates", break_turn_two)

    async def main():
        async with stdio_client(params(run)) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            assert (await call(s, "begin", {"task_id": "pl_kanban_updates"}))["ok"]
            with anyio.fail_after(20):
                end = await call(s, "finish_turn", {"summary": "done with turn 1"})
            after = await call(s, "get_board", {})
            return end, after

    end, after = anyio.run(main)
    assert not end["ok"] and "harness error" in end["error"] and "unknown element type" in end["error"]
    assert "session is over" in after["error"]
    assert status(run, "pl_kanban_updates")["state"] == "error"
    assert not (run / "pl_kanban_updates" / "result.json").exists()
