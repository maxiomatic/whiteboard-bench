# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Run bookkeeping for /whiteboard-bench. Standard library only.

    wb.py new <task>          create a run dir, make it the active run, print it
    wb.py aggregate <run>     merge per-task result.json files into results.json + report.html
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(os.environ.get("WBENCH_ROOT") or pathlib.Path(__file__).resolve().parents[4])
sys.path.insert(0, str(ROOT))

from wbench.report import write_report  # noqa: E402
from wbench.run import summarize  # noqa: E402

RUNS = ROOT / "runs"


def task_index() -> list[dict]:
    """Every task file as {num, id, stem, file, category}."""
    out = []
    for f in sorted((ROOT / "tasks").glob("*.json")):
        t = json.loads(f.read_text())
        out.append({"num": f.stem.split("_", 1)[0], "id": t["id"], "stem": f.stem, "file": f.name,
                    "category": t["category"]})
    return out


def resolve(selector: str) -> list[dict]:
    index = task_index()
    for t in index:
        if selector in (t["num"], t["id"], t["stem"]) or selector.lstrip("0") == t["num"].lstrip("0"):
            return [t]
    raise SystemExit(f"unknown task '{selector}'. Use a number (09), an id (bs_divergent_ideas) or a file stem.")


def cmd_new(a):
    tasks = resolve(a.selector)
    run = RUNS / f"subagents-{a.label}-{time.strftime('%Y%m%d-%H%M%S')}"
    run.mkdir(parents=True)
    manifest = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "label": a.label,
                "tasks": [t["id"] for t in tasks], "files": {t["id"]: t["file"] for t in tasks}}
    (run / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (RUNS / ".active").write_text(str(run))
    print(json.dumps({"run": str(run), "tasks": manifest["tasks"]}))


def cmd_aggregate(a):
    run = pathlib.Path(a.run)
    manifest = json.loads((run / "manifest.json").read_text())
    results, missing = [], []
    for tid in manifest["tasks"]:
        f = run / tid / "result.json"
        if f.exists():
            results.append(json.loads(f.read_text()))
        else:
            missing.append(tid)
    if not results:
        raise SystemExit(f"no finished tasks in {run}")
    summary = summarize(results)
    summary["agent"] = f"claude-code-subagents ({manifest['label']})"
    summary["missing"] = missing
    (run / "results.json").write_text(json.dumps(
        {"summary": summary, "results": [{k: v for k, v in r.items() if k != "svgs"} for r in results]}, indent=2))
    write_report(run / "report.html", summary, results)
    print(json.dumps({"overall": summary["overall"], "by_category": summary["by_category"],
                      "tasks": summary["tasks"], "missing": missing, "report": str(run / "report.html")}))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wb.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new", help="create a run for one task")
    p.add_argument("selector")
    p.add_argument("--label", default="inherit", help="usually the model under test")
    p.set_defaults(fn=cmd_new)
    p = sub.add_parser("aggregate", help="merge a run's results into a report")
    p.add_argument("run")
    p.set_defaults(fn=cmd_aggregate)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
