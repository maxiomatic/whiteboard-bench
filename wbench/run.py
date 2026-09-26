"""Command-line entry point.

    python -m wbench.run --agent replay            # validate tasks + graders
    python -m wbench.run --agent null              # floor scores
    python -m wbench.run --agent anthropic --model claude-sonnet-5 --judge
"""
import argparse
import json
import pathlib
import statistics
import sys
import time

from .agents import make_agent
from .harness import run_task
from .render import render_svg
from .report import write_report

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_tasks(path, only=None, category=None):
    tasks = []
    for f in sorted(pathlib.Path(path).glob("*.json")):
        t = json.loads(f.read_text())
        if only and t["id"] not in only:
            continue
        if category and t["category"] != category:
            continue
        tasks.append(t)
    return tasks


def summarize(results):
    cats = {}
    for r in results:
        if r["score"] is not None:
            cats.setdefault(r["category"], []).append(r["score"])
    per_cat = {c: round(statistics.mean(v), 4) for c, v in sorted(cats.items())}
    overall = round(statistics.mean(per_cat.values()), 4) if per_cat else None
    calls = sum(r["stats"]["tool_calls"] for r in results)
    errs = sum(r["stats"]["tool_errors"] for r in results)
    eff = [r["stats"]["efficiency"] for r in results if r["stats"]["efficiency"] is not None]
    return {"overall": overall, "by_category": per_cat, "tasks": len(results),
            "tool_calls": calls, "tool_error_rate": round(errs / calls, 4) if calls else 0.0,
            "mean_efficiency": round(statistics.mean(eff), 4) if eff else None}


def main(argv=None):
    ap = argparse.ArgumentParser(description="WhiteboardBench runner")
    ap.add_argument("--agent", default="replay", help="replay | null | anthropic")
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--thinking", type=int, default=0, help="extended thinking budget (anthropic agent)")
    ap.add_argument("--tasks", default=str(ROOT / "tasks"))
    ap.add_argument("--only", help="comma-separated task ids")
    ap.add_argument("--category")
    ap.add_argument("--judge", action="store_true", help="grade rubric checks with an LLM judge")
    ap.add_argument("--judge-model", default="claude-opus-5-5")
    ap.add_argument("--out", help="output directory (default runs/<agent>-<timestamp>)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    tasks = load_tasks(a.tasks, set(a.only.split(",")) if a.only else None, a.category)
    if not tasks:
        sys.exit("no tasks matched")
    kw = {"model": a.model, "thinking_budget": a.thinking} if a.agent == "anthropic" else {}
    judge = None
    if a.judge:
        from .judge import AnthropicJudge
        judge = AnthropicJudge(a.judge_model)
    label = a.agent if a.agent != "anthropic" else f"anthropic-{a.model}"
    out = pathlib.Path(a.out or ROOT / "runs" / f"{label}-{time.strftime('%Y%m%d-%H%M%S')}")
    out.mkdir(parents=True, exist_ok=True)

    results = []
    for t in tasks:
        agent = make_agent(a.agent, **kw)
        if hasattr(agent, "load"):
            agent.load(t)
        r = run_task(t, agent, judge=judge, render=render_svg)
        results.append(r)
        if not a.quiet:
            s = "  n/a" if r["score"] is None else f"{r['score']:.3f}"
            print(f"{s}  {r['category']:<14} {r['task_id']:<32} calls={r['stats']['tool_calls']}")
    summary = summarize(results)
    summary["agent"] = label
    (out / "results.json").write_text(json.dumps(
        {"summary": summary, "results": [{k: v for k, v in r.items() if k != "svgs"} for r in results]}, indent=2))
    write_report(out / "report.html", summary, results)
    print(json.dumps(summary, indent=2))
    print(f"report: {out / 'report.html'}")
    return summary


if __name__ == "__main__":
    main()
