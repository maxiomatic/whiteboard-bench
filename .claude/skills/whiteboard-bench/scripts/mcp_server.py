# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=2.2,<3"]
# ///
"""One WhiteboardBench board per Claude Code subagent, served over MCP stdio.

Claude Code starts this process when a `wbench-player` subagent starts and
stops it when the subagent finishes. The player calls `begin` with its task
id, then works the board with the benchmark's own tools. The unmodified
harness (`wbench.harness.run_task`) runs on a background thread and drives
the session; `BridgeAgent` hands each MCP tool call to it and hands the
harness's next message back in the result of the call that ended the turn.

Scores never reach the player. The graded result is written to
`<run>/<task>/result.json` for `wb.py aggregate`.
"""
from __future__ import annotations

import json
import os
import pathlib
import queue
import sys
import threading
import time
import uuid

ROOT = pathlib.Path(os.environ.get("WBENCH_ROOT") or pathlib.Path(__file__).resolve().parents[4])
sys.path.insert(0, str(ROOT))

import anyio  # noqa: E402
from mcp import types  # noqa: E402
from mcp.server.lowlevel import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402

from wbench.agents.anthropic_agent import system_prompt  # noqa: E402
from wbench.agents.base import Agent  # noqa: E402
from wbench.harness import briefing, run_task  # noqa: E402
from wbench.judge import board_as_text  # noqa: E402
from wbench.render import render_svg  # noqa: E402
from wbench.tools import TOOLS  # noqa: E402

BEGIN_TOOL = {
    "name": "begin",
    "description": "Start your whiteboard session. Call this once, first, with the task id you were given. "
                   "Returns who is at the board, the conventions, and the first request.",
    "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
}


class Shutdown(Exception):
    """Raised inside the harness thread when the player disconnects mid-task."""


class BridgeAgent(Agent):
    """Agent whose turns are played by tool calls arriving over MCP."""
    name = "claude-code-subagent"

    def __init__(self):
        self.inbox = queue.Queue()    # (tool, args) from the player, or None to shut down
        self.outbox = queue.Queue()   # ("result" | "message" | "complete" | "error", payload)
        self.closed = False

    def run_turn(self, message, env):
        if self.closed:
            return
        self.outbox.put(("message", message))
        while True:
            req = self.inbox.get()
            if req is None:
                self.closed = True
                raise Shutdown()
            name, args = req
            res = env.call(name, args)
            if env.done:  # finish_turn or budget exhausted: the harness decides what comes next
                self.turn_end = res
                return
            self.outbox.put(("result", res))


class RubricCapture:
    """Stands in for the LLM judge during the run: records what a grader needs, scores nothing.

    `wb.py` later applies an LLM judge's or a human's score to these checks.
    The materials match what `wbench.judge.AnthropicJudge` would have seen.
    """

    def __init__(self):
        self.items = []

    def __call__(self, board, spec, ctx):
        self.items.append({
            "question": spec["question"],
            "label": spec.get("label", "rubric"),
            "weight": spec.get("weight", 1.0),
            "requests": [t["prompt"] for t in ctx.task["turns"][: ctx.turn]],
            "said": "\n".join(m["text"] for m in ctx.messages),
            "board": board_as_text(board),
            "turn": ctx.turn,
        })
        return None, "awaiting judgement"


def rubric_positions(result: dict) -> list[list]:
    """Where each rubric check sits in a result, in grading order: ["turn", i, j] or ["final", j]."""
    where = [["turn", i, j] for i, t in enumerate(result["turns"])
             for j, c in enumerate(t["checks"]) if c["check"] == "rubric"]
    return where + [["final", j] for j, c in enumerate(result["final_checks"]) if c["check"] == "rubric"]


class Session:
    def __init__(self, run_dir: pathlib.Path):
        self.run_dir = run_dir
        self.task = None
        self.agent = None
        self.thread = None
        self.complete = False
        self.token = uuid.uuid4().hex
        self.calls = 0
        self.turn = 0

    # -- files ---------------------------------------------------------------
    def _owner(self) -> bool:
        """False once `wb.py retry` has archived this attempt: a stale player must not write."""
        try:
            return (self.task_dir / "claim").read_text() == self.token
        except FileNotFoundError:
            return False

    def _status(self, state: str, **extra):
        if not self._owner():
            return
        data = {"state": state, "turn": self.turn, "calls": self.calls, "updated": time.time(), **extra}
        tmp = self.task_dir / "status.json.tmp"
        tmp.write_text(json.dumps(data))
        tmp.replace(self.task_dir / "status.json")

    # -- begin -------------------------------------------------------------
    def begin(self, task_id: str) -> dict:
        if self.task is not None:
            return {"ok": False, "error": f"session already started for task {self.task['id']}"}
        manifest = json.loads((self.run_dir / "manifest.json").read_text())
        if task_id not in manifest["tasks"]:
            return {"ok": False, "error": f"task '{task_id}' is not part of this run"}
        task_dir = self.run_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(task_dir / "claim", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return {"ok": False, "error": f"task '{task_id}' was already claimed by another player"}
        os.write(fd, self.token.encode())
        os.close(fd)
        self.task = json.loads((ROOT / "tasks" / manifest["files"][task_id]).read_text())
        self.task_dir = task_dir
        self.judge_mode = manifest["config"].get("judge", "llm")
        self.capture = RubricCapture() if self.judge_mode != "off" else None
        self.turn = 1
        self._status("playing")
        self.agent = BridgeAgent()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        kind, first = self.agent.outbox.get()
        if kind == "error":
            self.complete = True  # the session never started: keep the "error" status, don't mark it abandoned
            return {"ok": False, "error": first}
        b = briefing(self.task)
        return {"ok": True, "task": self.task["title"], "instructions": system_prompt(b), "message": first}

    def _run(self):
        try:
            result = run_task(self.task, self.agent, judge=self.capture, render=render_svg)
        except Exception as e:  # the harness itself failed: surface it rather than hang
            self._status("error", error=f"{type(e).__name__}: {e}")
            self.agent.outbox.put(("error", f"{type(e).__name__}: {e}"))
            return
        if self.agent.closed:
            return
        if self._owner():
            (self.task_dir / "result.json").write_text(json.dumps(result))
            if self.capture and self.capture.items:
                items = [{"where": w, **item} for w, item in zip(rubric_positions(result), self.capture.items, strict=True)]
                (self.task_dir / "rubric.json").write_text(json.dumps(
                    {"task_id": self.task["id"], "title": self.task["title"], "mode": self.judge_mode,
                     "items": items}, indent=2))
            self._status("done")
        self.agent.outbox.put(("complete", None))

    # -- board tools ---------------------------------------------------------
    def call(self, name: str, args: dict) -> dict:
        if self.task is None:
            return {"ok": False, "error": "call begin with your task id first"}
        if self.complete:
            return {"ok": False, "error": "the session is over; reply with one line and stop"}
        self.calls += 1  # counted when sent, so the final "done" status includes the call that ended the session
        self.agent.inbox.put((name, args))
        kind, payload = self.agent.outbox.get()
        if kind == "result":
            self._status("playing")
            return payload
        res = dict(getattr(self.agent, "turn_end", {}) or {})
        if kind == "message":
            self.turn += 1
            self._status("playing")
            res.update(turn_over=True, next_message=payload)
        elif kind == "complete":
            self.complete = True
            res.update(task_complete=True, message="The session is over. Reply with one line and stop.")
        else:
            self.complete = True
            res.update(ok=False, error=f"harness error: {payload}")
        return res

    def close(self):
        if self.agent and not self.complete:
            self.agent.inbox.put(None)
            self._status("abandoned")


def active_run_dir() -> pathlib.Path:
    if os.environ.get("WBENCH_RUN_DIR"):
        return pathlib.Path(os.environ["WBENCH_RUN_DIR"])
    pointer = ROOT / "runs" / ".active"
    if not pointer.exists():
        sys.exit("no active run: start one with `just sub-new <selector>`")
    return pathlib.Path(pointer.read_text().strip())


def build_server(session: Session) -> Server:
    tools = [types.Tool(name=t["name"], description=t["description"], inputSchema=t["input_schema"])
             for t in [BEGIN_TOOL, *TOOLS]]

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=tools)

    async def call_tool(ctx, params):
        args = params.arguments or {}
        if params.name == "begin":
            res = await anyio.to_thread.run_sync(session.begin, str(args.get("task_id", "")))
        else:
            res = await anyio.to_thread.run_sync(session.call, params.name, args)
        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(res))],
                                    isError=not res.get("ok", False))

    return Server("wbench", on_list_tools=list_tools, on_call_tool=call_tool)


async def main():
    session = Session(active_run_dir())
    server = build_server(session)
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        session.close()


if __name__ == "__main__":
    anyio.run(main)
