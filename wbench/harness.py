"""Runs one task (a multi-turn episode) with one agent and grades it."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from .board import Board
from .checks import CHECKS
from .events import apply_event, display_name
from .tools import TOOLS, ToolExecutor

CONVENTIONS = """\
You are a collaborator at a shared whiteboard with the people listed in the briefing.
Coordinates are board pixels: x grows to the right, y grows downward, and (x, y) is an
element's top-left corner. Sticky notes default to 160x160. An element belongs to the
smallest frame containing its center; moving a frame moves everything inside it.
Humans keep editing the board too: read the activity notes you receive, and treat
other people's content as theirs (don't rewrite or delete it unless asked).
Keep the board legible: short sticky text, no overlapping items, related things together.
When you have fully handled the current request, call finish_turn."""


@dataclass
class Context:
    task: dict
    participants: dict
    judge: object = None
    snapshots: dict = field(default_factory=dict)
    messages: list = field(default_factory=list)
    turn: int = 0


class TurnEnv:
    """What an agent sees during one turn: a call() function plus bookkeeping."""

    def __init__(self, executor, participants, pending, max_calls, trace, turn):
        self.executor = executor
        self.participants = participants
        self.pending = pending
        self.max_calls = max_calls
        self.trace = trace
        self.turn = turn
        self.calls = 0
        self.errors = 0
        self.done = False

    def call(self, name, args=None):
        if self.done:
            return {"ok": False, "error": "this turn is over; wait for the next request"}
        if self.calls >= self.max_calls:
            self.done = True
            return {"ok": False, "error": "tool-call budget for this turn is exhausted"}
        self.calls += 1
        res = self.executor.call(name, args or {})
        if not res.get("ok"):
            self.errors += 1
        if name == "finish_turn" and res.get("ok"):
            self.done = True
        fired = [ev for ev in self.pending if ev["at_call"] <= self.calls]
        if fired and not self.done:
            self.pending[:] = [ev for ev in self.pending if ev not in fired]
            acts = []
            for ev in fired:
                try:
                    acts.append(apply_event(self.executor.board, ev, self.participants))
                except LookupError:
                    pass
            if acts:
                res["board_activity"] = acts
        self.trace.append({"turn": self.turn, "n": self.calls, "tool": name, "args": args or {},
                           "result": _truncate(res)})
        return res


def _truncate(res, limit=1500):
    s = json.dumps(res)
    return res if len(s) <= limit else {"truncated": s[:limit]}


def build_board(task):
    spec = task.get("board", {})
    board = Board(spec.get("width", 4000), spec.get("height", 3000))
    for raw in task.get("initial_elements", []):
        el = dict(raw)
        actor = el.pop("author", "human:facilitator")
        etype = el.pop("type")
        board.begin(actor)
        board.create(actor, etype, **el)
        board.commit()
    board._undo.clear()
    return board


def briefing(task):
    return {
        "task_id": task["id"],
        "title": task["title"],
        "setting": task.get("setting", "A shared digital whiteboard."),
        "participants": task.get("participants", {}),
        "board_size": task.get("board", {"width": 4000, "height": 3000}),
        "conventions": CONVENTIONS,
        "tools": TOOLS,
    }


def compose_message(task, turn_idx, turn, activity, board):
    n_turns = len(task["turns"])
    parts = [f"[Turn {turn_idx} of {n_turns}]"]
    if turn_idx == 1:
        parts.append(f"The board currently has {len(board.elements)} element(s). Use get_board to inspect it.")
    if activity:
        parts.append("Since your last turn:\n" + "\n".join(f"- {a}" for a in activity))
    who = display_name(turn.get("speaker", "human:facilitator"), task.get("participants", {}))
    parts.append(f"{who} asks: {turn['prompt']}")
    return "\n\n".join(parts)


def grade(checks, board, ctx):
    out = []
    for spec in checks:
        fn = CHECKS[spec["check"]]
        try:
            score, detail = fn(board, spec, ctx)
        except Exception as e:  # a crashing check scores 0 and says why
            score, detail = 0.0, f"check error: {type(e).__name__}: {e}"
        if score and "requires_change" in spec and not _changed(ctx, *spec["requires_change"]):
            score, detail = 0.0, f"no credit: board did not change between {' and '.join(spec['requires_change'])}"
        out.append({"check": spec["check"], "label": spec.get("label", spec["check"]),
                    "weight": spec.get("weight", 1.0), "guard": is_guard(spec),
                    "score": None if score is None else round(float(score), 4), "detail": detail})
    return out


def _changed(ctx, a, b):
    """True if element geometry or text differs between two snapshots."""
    sa, sb = ctx.snapshots.get(a), ctx.snapshots.get(b)
    if sa is None or sb is None:
        return True
    key = lambda s: {k: (e.get("x"), e.get("y"), e.get("text"), e.get("color")) for k, e in s.items()}
    return key(sa) != key(sb)


GUARD_CHECKS = {"preserve_human", "no_overlap", "texts_absent"}


def is_guard(spec):
    """Guards are constraints an empty board satisfies trivially (don't delete human
    work, don't overlap, don't leave wrong text). They can cut a score but never earn
    points alone. A spec can override with "guard": true/false."""
    if "guard" in spec:
        return bool(spec["guard"])
    if spec["check"] == "count" and spec.get("min") in (None, 0) and "max" in spec:
        return True
    return spec["check"] in GUARD_CHECKS


def _mean(results):
    num = sum(r["score"] * r["weight"] for r in results if r["score"] is not None)
    den = sum(r["weight"] for r in results if r["score"] is not None)
    return num / den if den else None


def weighted(results):
    """Score = progress * (0.5 + 0.5 * guards). With no progress checks, guards alone."""
    progress = _mean([r for r in results if not r.get("guard")])
    guards = _mean([r for r in results if r.get("guard")])
    if progress is None:
        return guards
    if guards is None:
        return progress
    return progress * (0.5 + 0.5 * guards)


def _apply(board, ev, participants, skipped):
    """Apply an event; if its target is missing (agent never drew it), skip and record."""
    try:
        return apply_event(board, ev, participants)
    except LookupError as e:
        skipped.append(str(e))
        return None


def run_task(task, agent, judge=None, render=None):
    board = build_board(task)
    participants = task.get("participants", {})
    ctx = Context(task=task, participants=participants, judge=judge)
    executor = ToolExecutor(board, "agent")
    ctx.messages = executor.messages
    ctx.snapshots["initial"] = board.snapshot()
    trace, turns, svgs, skipped = [], [], {}, []
    svgs["initial"] = render(board, participants) if render else None
    agent.start(briefing(task))
    budget = task.get("max_calls_per_turn", 60)
    t_start = time.time()
    for i, turn in enumerate(task["turns"], 1):
        board.turn = i
        ctx.turn = i
        pre = [ev for ev in turn.get("events", []) if "at_call" not in ev]
        mid = sorted((ev for ev in turn.get("events", []) if "at_call" in ev), key=lambda e: e["at_call"])
        activity = [a for a in (_apply(board, ev, participants, skipped) for ev in pre) if a]
        ctx.snapshots[f"turn{i}_start"] = board.snapshot()
        env = TurnEnv(executor, participants, list(mid), budget, trace, i)
        executor.finished = False
        agent_error = None
        try:
            agent.run_turn(compose_message(task, i, turn, activity, board), env)
            if env.pending:  # agent wrapped up before the interruption: deliver it now
                late = [a for a in (_apply(board, ev, participants, skipped) for ev in env.pending) if a]
                env.pending.clear()
                env.done = False
                executor.finished = False
                agent.run_turn("While you were wrapping up:\n" + "\n".join(f"- {a}" for a in late)
                               + "\n\nPlease account for this, then call finish_turn.", env)
        except Exception as e:
            agent_error = f"{type(e).__name__}: {e}"
        ctx.snapshots[f"turn{i}_end"] = board.snapshot()
        results = grade(turn.get("checks", []), board, ctx)
        turns.append({"turn": i, "calls": env.calls, "errors": env.errors, "agent_error": agent_error,
                      "checks": results, "score": weighted(results)})
        if render:
            svgs[f"turn{i}"] = render(board, participants)
    final = grade(task.get("final_checks", []), board, ctx)
    all_checks = [c for t in turns for c in t["checks"]] + final
    calls = sum(t["calls"] for t in turns)
    errors = sum(t["errors"] for t in turns)
    target = task.get("efficient_calls")
    return {
        "task_id": task["id"], "category": task["category"], "title": task["title"],
        "difficulty": task.get("difficulty", "medium"),
        "score": weighted(all_checks),
        "turns": turns, "final_checks": final,
        "skipped_events": skipped,
        "skipped_checks": sum(1 for c in all_checks if c["score"] is None),
        "stats": {"tool_calls": calls, "tool_errors": errors,
                  "error_rate": round(errors / calls, 4) if calls else 0.0,
                  "efficiency": (min(1.0, target / calls) if target and calls else None),
                  "seconds": round(time.time() - t_start, 2)},
        "messages": executor.messages,
        "trace": trace,
        "svgs": svgs,
    }
