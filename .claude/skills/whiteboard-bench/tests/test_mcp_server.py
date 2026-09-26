"""Drive mcp_server.py over stdio exactly as Claude Code would, replaying reference solutions."""
import json
import os
import sys

import anyio
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
