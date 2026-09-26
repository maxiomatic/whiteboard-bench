"""Tool-use agent backed by the Anthropic Messages API (stdlib only).

    export ANTHROPIC_API_KEY=...
    python -m wbench.run --agent anthropic --model claude-sonnet-5

Conversation history persists across turns within a task, the way a
collaborator remembers what happened earlier in a session.
"""
import json
import os
import time
import urllib.error
import urllib.request

from .base import Agent

API_URL = "https://api.anthropic.com/v1/messages"


def post(body, api_key, retries=6):
    data = json.dumps(body).encode()
    for attempt in range(retries):
        req = urllib.request.Request(API_URL, data=data, method="POST", headers={
            "content-type": "application/json", "x-api-key": api_key,
            "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                time.sleep(min(60, 2 ** attempt * 2))
                continue
            raise RuntimeError(f"API error {e.code}: {e.read()[:500]!r}")
        except urllib.error.URLError:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise


def system_prompt(b):
    people = "\n".join(
        f"- {p.get('name', k)} (actor id human:{k})"
        + (f", color {p['color']}" if p.get("color") else "")
        + (f", arm's-reach region x={p['reach']['x']}..{p['reach']['x'] + p['reach']['w']}, "
           f"y={p['reach']['y']}..{p['reach']['y'] + p['reach']['h']}" if p.get("reach") else "")
        + (f". {p['note']}" if p.get("note") else "")
        for k, p in b["participants"].items()) or "- a facilitator"
    return (f"{b['conventions']}\n\nSetting: {b['setting']}\n\nPeople at the board:\n{people}\n\n"
            f"Board size: {b['board_size']['width']}x{b['board_size']['height']}.")


class AnthropicAgent(Agent):
    name = "anthropic"

    def __init__(self, model="claude-sonnet-5", max_tokens=4096, api_key=None, thinking_budget=0):
        self.model = model
        self.max_tokens = max_tokens
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.thinking_budget = thinking_budget
        if not self.api_key:
            raise SystemExit("Set ANTHROPIC_API_KEY to use the anthropic agent")

    def start(self, briefing):
        super().start(briefing)
        self.system = system_prompt(briefing)
        self.tools = briefing["tools"]
        self.messages = []

    def run_turn(self, message, env):
        self.messages.append({"role": "user", "content": message})
        while not env.done:
            body = {"model": self.model, "max_tokens": self.max_tokens, "system": self.system,
                    "tools": self.tools, "messages": self.messages}
            if self.thinking_budget:
                body["thinking"] = {"type": "enabled", "budget_tokens": self.thinking_budget}
            resp = post(body, self.api_key)
            content = resp.get("content", [])
            self.messages.append({"role": "assistant", "content": content})
            uses = [c for c in content if c.get("type") == "tool_use"]
            if not uses:
                env.call("finish_turn", {})
                self.messages.append({"role": "user", "content": "(turn ended)"})
                return
            results = []
            for u in uses:
                res = env.call(u["name"], u.get("input") or {})
                results.append({"type": "tool_result", "tool_use_id": u["id"],
                                "content": json.dumps(res), "is_error": not res.get("ok", False)})
            self.messages.append({"role": "user", "content": results})
