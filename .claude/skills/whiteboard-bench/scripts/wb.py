# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Run bookkeeping for /whiteboard-bench. Standard library only.

    wb.py list                          every task, with its number, category and rubric flag
    wb.py new [selector] [--model M] [--dry-run]
                                        resolve the selection, create the run, make it active
    wb.py aggregate <run>               merge per-task result.json files into results.json + report.html

Selectors: a task by number, id or file stem (09, bs_divergent_ideas,
09_bs_divergent_ideas); a comma-separated list of those; a category
(diagramming); "smoke" (the first task of each category); "all".
Defaults come from config.toml next to this skill; flags override them.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import tomllib

ROOT = pathlib.Path(os.environ.get("WBENCH_ROOT") or pathlib.Path(__file__).resolve().parents[4])
sys.path.insert(0, str(ROOT))

from wbench.report import write_report  # noqa: E402
from wbench.run import summarize  # noqa: E402

RUNS = ROOT / "runs"
CONFIG = pathlib.Path(__file__).resolve().parents[1] / "config.toml"
DEFAULTS = {"select": "smoke", "model": "inherit"}


def task_index() -> list[dict]:
    """Every task file as {num, id, stem, file, category, turns, rubric}."""
    out = []
    for f in sorted((ROOT / "tasks").glob("*.json")):
        t = json.loads(f.read_text())
        checks = [c for turn in t["turns"] for c in turn.get("checks", [])] + t.get("final_checks", [])
        out.append({"num": f.stem.split("_", 1)[0], "id": t["id"], "stem": f.stem, "file": f.name,
                    "category": t["category"], "title": t["title"], "turns": len(t["turns"]),
                    "rubric": any(c["check"] == "rubric" for c in checks)})
    return out


def resolve(selector: str) -> list[dict]:
    """Turn a selector into task entries, in task-file order, without duplicates."""
    index = task_index()
    categories = sorted({t["category"] for t in index})
    chosen = set()
    for part in (p.strip() for p in selector.split(",")):
        if part == "all":
            chosen.update(t["id"] for t in index)
        elif part == "smoke":
            seen = set()
            for t in index:
                if t["category"] not in seen:
                    seen.add(t["category"])
                    chosen.add(t["id"])
        elif part in categories:
            chosen.update(t["id"] for t in index if t["category"] == part)
        else:
            match = [t for t in index if part in (t["num"], t["id"], t["stem"])
                     or (part.isdigit() and int(part) == int(t["num"]))]
            if not match:
                raise SystemExit(f"unknown selector '{part}'. Use a task number (09), id (bs_divergent_ideas), "
                                 f"file stem, a category ({', '.join(categories)}), smoke or all. "
                                 "`just sub-list` shows every task.")
            chosen.add(match[0]["id"])
    return [t for t in index if t["id"] in chosen]


def load_config(path: pathlib.Path | None = None) -> dict:
    path = path or CONFIG
    cfg = dict(DEFAULTS)
    if path.exists():
        cfg.update(tomllib.loads(path.read_text()))
    unknown = set(cfg) - set(DEFAULTS)
    if unknown:
        raise SystemExit(f"unknown key(s) in {path}: {', '.join(sorted(unknown))}")
    return cfg


def settings(a) -> dict:
    """config.toml, then flags. The result is what the run records and uses."""
    cfg = load_config(pathlib.Path(a.config) if a.config else None)
    if a.selector:
        cfg["select"] = a.selector
    if a.model:
        cfg["model"] = a.model
    return cfg


def cmd_list(a):
    print(f"{'#':<3} {'id':<30} {'category':<14} {'turns':>5}  rubric")
    for t in task_index():
        print(f"{t['num']:<3} {t['id']:<30} {t['category']:<14} {t['turns']:>5}  {'yes' if t['rubric'] else ''}")


def cmd_new(a):
    cfg = settings(a)
    tasks = resolve(cfg["select"])
    plan = {"select": cfg["select"], "model": cfg["model"], "tasks": [t["id"] for t in tasks],
            "players": len(tasks)}
    if a.dry_run:
        print(json.dumps({"dry_run": True, **plan}))
        return
    run = RUNS / f"subagents-{_slug(cfg['model'])}-{time.strftime('%Y%m%d-%H%M%S')}"
    run.mkdir(parents=True)
    manifest = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "config": cfg,
                "tasks": plan["tasks"], "files": {t["id"]: t["file"] for t in tasks}}
    (run / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (RUNS / ".active").write_text(str(run))
    print(json.dumps({"run": str(run), **plan}))


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-." else "-" for c in text)


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
    summary["agent"] = f"claude-code-subagents ({manifest['config']['model']})"
    summary["config"] = manifest["config"]
    summary["missing"] = missing
    (run / "results.json").write_text(json.dumps(
        {"summary": summary, "results": [{k: v for k, v in r.items() if k != "svgs"} for r in results]}, indent=2))
    write_report(run / "report.html", summary, results)
    print(json.dumps({"overall": summary["overall"], "by_category": summary["by_category"],
                      "tasks": summary["tasks"], "missing": missing, "report": str(run / "report.html")}))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wb.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="show every task")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("new", help="create a run")
    p.add_argument("selector", nargs="?", help="task(s), category, smoke or all (default: config select)")
    p.add_argument("--model", help="model the players run on (default: config model)")
    p.add_argument("--dry-run", action="store_true", help="show what would run, create nothing")
    p.add_argument("--config", help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_new)
    p = sub.add_parser("aggregate", help="merge a run's results into a report")
    p.add_argument("run")
    p.set_defaults(fn=cmd_aggregate)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
