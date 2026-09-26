"""Smoke and unit tests. Run with:  python -m unittest discover -s tests -v"""
import json
import pathlib
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wbench import textmatch as tm  # noqa: E402
from wbench.agents import make_agent  # noqa: E402
from wbench.agents.replay import ReplayAgent  # noqa: E402
from wbench.board import Board  # noqa: E402
from wbench.checks import CHECKS  # noqa: E402
from wbench.harness import Context, run_task, weighted  # noqa: E402
from wbench.render import render_svg  # noqa: E402
from wbench.tools import ToolExecutor  # noqa: E402

TASKS = [json.loads(p.read_text()) for p in sorted((ROOT / "tasks").glob("*.json"))]


def run(task, agent):
    if hasattr(agent, "load"):
        agent.load(task)
    return run_task(task, agent, render=render_svg)


class VandalAgent(ReplayAgent):
    """Solves the task, then deletes everything humans made. Should be penalized."""
    name = "vandal"

    def run_turn(self, message, env):
        super().run_turn(message, env)
        human = [e["id"] for e in env.executor.board.elements.values()
                 if str(e.get("author", "")).startswith("human")]
        if human:
            env.executor.finished = False
            env.done = False
            env.call("delete_elements", {"ids": human})
            env.call("finish_turn", {})


class TaskSuite(unittest.TestCase):
    def test_task_files_are_well_formed(self):
        ids = set()
        for t in TASKS:
            for key in ("id", "category", "title", "turns", "reference_solution"):
                self.assertIn(key, t, f"{t.get('id')} missing {key}")
            self.assertNotIn(t["id"], ids)
            ids.add(t["id"])
            self.assertEqual(len(t["turns"]), len(t["reference_solution"]), t["id"])
            for turn in t["turns"]:
                for c in turn.get("checks", []):
                    self.assertIn(c["check"], CHECKS, f"{t['id']}: unknown check {c['check']}")
        self.assertGreaterEqual(len(TASKS), 20)

    def test_reference_solutions_score_full_marks(self):
        for t in TASKS:
            with self.subTest(task=t["id"]):
                r = run(t, make_agent("replay"))
                errs = [x["agent_error"] for x in r["turns"] if x["agent_error"]]
                self.assertEqual(errs, [])
                self.assertEqual(r["stats"]["tool_errors"], 0)
                self.assertGreaterEqual(r["score"], 0.999)
                for svg in r["svgs"].values():
                    ET.fromstring(svg)  # well-formed XML

    def test_null_agent_scores_near_zero(self):
        scores = [run(t, make_agent("null"))["score"] or 0.0 for t in TASKS]
        self.assertLess(sum(scores) / len(scores), 0.15)
        self.assertLess(max(scores), 0.5)

    def test_destroying_human_work_is_penalized(self):
        hits = 0
        for t in TASKS:
            if not any(str(e.get("author", "")).startswith("human") for e in t.get("initial_elements", [])):
                continue
            r = run(t, VandalAgent())
            if r["score"] < 0.9:
                hits += 1
        self.assertGreaterEqual(hits, 12)


class BoardTests(unittest.TestCase):
    def test_undo_keeps_other_peoples_later_edits(self):
        b = Board()
        b.begin("agent")
        a = b.create("agent", "sticky", text="A", x=0, y=0)
        c = b.create("agent", "sticky", text="C", x=300, y=0)
        b.commit()
        b.begin("agent")
        b.translate("agent", [a, c], 100, 0)
        b.commit()
        b.begin("human:maya")
        b.update("human:maya", c, text="C edited")
        b.commit()
        b.begin("agent")
        reverted, conflicts = b.undo("agent")
        b.commit()
        self.assertEqual(b.elements[a]["x"], 0)
        self.assertIn(c, conflicts)
        self.assertEqual(b.elements[c]["text"], "C edited")

    def test_failed_tool_call_rolls_back(self):
        b = Board()
        ex = ToolExecutor(b, "agent")
        res = ex.call("create_connector", {"source_id": "nope", "target_id": "also_nope"})
        self.assertFalse(res["ok"])
        self.assertEqual(b.elements, {})

    def test_moving_frame_carries_contents(self):
        b = Board()
        ex = ToolExecutor(b, "agent")
        f = ex.call("create_frame", {"title": "F", "x": 0, "y": 0, "w": 400, "h": 400})["id"]
        s = ex.call("create_sticky", {"text": "inside", "x": 50, "y": 80})["id"]
        ex.call("translate_elements", {"ids": [f], "dx": 500, "dy": 0})
        self.assertEqual(b.elements[s]["x"], 550)


class TextMatchTests(unittest.TestCase):
    def test_matching(self):
        self.assertTrue(tm.matches("activation dashboard", "Build an Activation Dashboard by Friday"))
        self.assertTrue(tm.matches("train support|support trained", "Support team gets trained"))
        self.assertFalse(tm.matches("dark mode", "Offline mode"))


class ScoringTests(unittest.TestCase):
    def test_guards_cannot_earn_points_alone(self):
        progress = {"score": 0.0, "weight": 1, "guard": False}
        guard = {"score": 1.0, "weight": 5, "guard": True}
        self.assertEqual(weighted([progress, guard]), 0.0)
        self.assertAlmostEqual(weighted([dict(progress, score=1.0), dict(guard, score=0.0)]), 0.5)

    def test_graph_check_rewards_edges(self):
        b = Board()
        ex = ToolExecutor(b, "agent")
        ids = {n: ex.call("create_shape", {"kind": "rect", "text": n, "x": 300 * i, "y": 0})["id"]
               for i, n in enumerate(["A", "B", "C"])}
        spec = {"check": "graph", "nodes": ["A", "B", "C"], "edges": [["A", "B"], ["B", "C"]]}
        ctx = Context(task={}, participants={}, judge=None)
        before, _ = CHECKS["graph"](b, spec, ctx)
        ex.call("create_connector", {"source_id": ids["A"], "target_id": ids["B"]})
        ex.call("create_connector", {"source_id": ids["B"], "target_id": ids["C"]})
        after, _ = CHECKS["graph"](b, spec, ctx)
        self.assertLess(before, 0.5)
        self.assertAlmostEqual(after, 1.0)


if __name__ == "__main__":
    unittest.main()
