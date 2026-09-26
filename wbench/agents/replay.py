"""Replays each task's reference solution through the normal tool API.

Reference solutions prove every task is solvable with the public tools and
that the graders accept a correct board. Argument values may use:
  "$name"                 id returned by an earlier call tagged "as": "name"
  {"$find": {...}}        first id from find_elements(**selector)
  {"$find_all": {...}}    all ids from find_elements(**selector)
  {"$at": [x, y]}         nearest non-frame element from get_elements_at
Selectors may name frames by title with "frame": "<title>".
"""
from .base import Agent


class ReplayAgent(Agent):
    name = "replay"
    solution = None

    def start(self, briefing):
        super().start(briefing)
        self.task_id = briefing["task_id"]
        self.vars = {}
        self.turn = 0

    def load(self, task):
        self.solution = task.get("reference_solution", [])

    def run_turn(self, message, env):
        if message.startswith("While you were wrapping up"):
            env.call("finish_turn", {})
            return
        self.turn += 1
        steps = self.solution[self.turn - 1] if self.solution and self.turn <= len(self.solution) else []
        for step in steps:
            args = self._resolve(step.get("args", {}), env)
            res = env.call(step["tool"], args)
            if not res.get("ok"):
                raise RuntimeError(f"reference step failed: {step['tool']} {args} -> {res}")
            if "as" in step:
                self.vars[step["as"]] = res.get("id") or res.get("group")
        if not env.done:
            env.call("finish_turn", {})

    def _selector(self, sel, env):
        sel = dict(sel)
        if "frame" in sel:
            title = sel.pop("frame")
            frames = env.call("find_elements", {"query": title, "type": "frame"})["elements"]
            if not frames:
                raise RuntimeError(f"frame '{title}' not found")
            sel["frame_id"] = frames[0]["id"]
        return env.call("find_elements", sel)["elements"]

    def _resolve(self, v, env):
        if isinstance(v, str) and v.startswith("$"):
            return self.vars[v[1:]]
        if isinstance(v, list):
            return [self._resolve(x, env) for x in v]
        if isinstance(v, dict):
            if "$find" in v:
                els = self._selector(v["$find"], env)
                if not els:
                    raise RuntimeError(f"not found: {v['$find']}")
                return els[0]["id"]
            if "$find_all" in v:
                return [e["id"] for e in self._selector(v["$find_all"], env)]
            if "$at" in v:
                x, y = v["$at"]
                els = [e for e in env.call("get_elements_at", {"x": x, "y": y, "radius": 40})["elements"]
                       if e["type"] != "frame"]
                return els[0]["id"]
            return {k: self._resolve(x, env) for k, x in v.items()}
        return v
