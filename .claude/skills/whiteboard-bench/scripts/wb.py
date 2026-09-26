# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Run bookkeeping for /whiteboard-bench. Standard library only.

    wb.py list                           every task, with its number, category and rubric flag
    wb.py new [selector] [--model M] [--dry-run]
                                         resolve the selection, create the run, make it active
    wb.py next <run>                     task ids to spawn now (respects concurrency)
    wb.py retry <run> <task>             archive a failed attempt; requeue it or mark it failed
    wb.py timing <run> <task> --tokens N --ms M
                                         record what a player cost
    wb.py resume <run>                   make an old run active again and requeue unfinished tasks
    wb.py watch <run>                    one line per state change, for the Monitor tool
    wb.py aggregate <run> [<run> ...]    merge results into results.json + report.html

Selectors: a task by number, id or file stem (09, bs_divergent_ideas,
09_bs_divergent_ideas); a comma-separated list of those; a category
(diagramming); "smoke" (the first task of each category); "all".
Defaults come from config.toml next to this skill; flags override them.

Task states, stored in <run>/<task>/status.json:
    pending    no status yet
    spawned    handed out by `next`, player not connected yet   (written here)
    playing    the player called begin                          (written by mcp_server.py)
    done       the session completed and result.json exists     (mcp_server.py)
    abandoned  the player disconnected before the end           (mcp_server.py)
    error      the harness itself failed                        (mcp_server.py)
    failed     retries exhausted                                (written here)
`stalled` is not stored: `watch` derives it from a spawned/playing task
whose status hasn't changed for stall_minutes.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import time
import tomllib

ROOT = pathlib.Path(os.environ.get("WBENCH_ROOT") or pathlib.Path(__file__).resolve().parents[4])
sys.path.insert(0, str(ROOT))

from wbench.report import write_report  # noqa: E402
from wbench.run import summarize  # noqa: E402

RUNS = ROOT / "runs"
CONFIG = pathlib.Path(__file__).resolve().parents[1] / "config.toml"
DEFAULTS = {"select": "smoke", "model": "inherit", "concurrency": 6, "retries": 1, "stall_minutes": 10}
ACTIVE = {"spawned", "playing"}
RETRYABLE = {"abandoned", "error", "stalled"}
FINAL = {"done", "failed"}
QUIET = {"pending", "spawned"}  # bookkeeping states the orchestrator already knows about


# -- tasks and selectors -------------------------------------------------------

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


# -- config ----------------------------------------------------------------------

def load_config(path: pathlib.Path | None = None) -> dict:
    path = path or CONFIG
    cfg = dict(DEFAULTS)
    if path.exists():
        cfg.update(tomllib.loads(path.read_text()))
    unknown = set(cfg) - set(DEFAULTS)
    if unknown:
        raise SystemExit(f"unknown key(s) in {path}: {', '.join(sorted(unknown))}")
    for key in ("concurrency", "retries", "stall_minutes"):
        if not isinstance(cfg[key], int) or cfg[key] < (1 if key != "retries" else 0):
            raise SystemExit(f"{key} in {path} must be a whole number (got {cfg[key]!r})")
    return cfg


def settings(a) -> dict:
    """config.toml, then flags. The result is what the run records and uses."""
    cfg = load_config(pathlib.Path(a.config) if a.config else None)
    if a.selector:
        cfg["select"] = a.selector
    if a.model:
        cfg["model"] = a.model
    return cfg


# -- run state -------------------------------------------------------------------

def manifest(run: pathlib.Path) -> dict:
    return json.loads((run / "manifest.json").read_text())


def status(run: pathlib.Path, task: str) -> dict:
    try:
        return json.loads((run / task / "status.json").read_text())
    except FileNotFoundError:
        return {"state": "pending"}


def write_status(run: pathlib.Path, task: str, state: str, **extra):
    d = run / task
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "status.json.tmp"
    tmp.write_text(json.dumps({"state": state, "updated": time.time(), **extra}))
    tmp.replace(d / "status.json")


def effective_state(st: dict, now: float, stall_minutes: int) -> str:
    if st["state"] in ACTIVE and now - st.get("updated", now) > stall_minutes * 60:
        return "stalled"
    return st["state"]


def states(run: pathlib.Path, now: float | None = None) -> dict[str, str]:
    m = manifest(run)
    now = time.time() if now is None else now
    return {t: effective_state(status(run, t), now, m["config"]["stall_minutes"]) for t in m["tasks"]}


def attempts(run: pathlib.Path, task: str) -> int:
    archive = run / ".attempts"
    return len(list(archive.glob(f"{task}-*"))) if archive.exists() else 0


def archive_attempt(run: pathlib.Path, task: str):
    """Move a task's files aside. Its claim goes with them, so a stale player can no longer write."""
    src = run / task
    if src.exists():
        dest = run / ".attempts" / f"{task}-{attempts(run, task) + 1}"
        dest.parent.mkdir(exist_ok=True)
        shutil.move(str(src), dest)


# -- commands --------------------------------------------------------------------

def cmd_list(a):
    print(f"{'#':<3} {'id':<30} {'category':<14} {'turns':>5}  rubric")
    for t in task_index():
        print(f"{t['num']:<3} {t['id']:<30} {t['category']:<14} {t['turns']:>5}  {'yes' if t['rubric'] else ''}")


def cmd_new(a):
    cfg = settings(a)
    tasks = resolve(cfg["select"])
    plan = {"select": cfg["select"], "model": cfg["model"], "tasks": [t["id"] for t in tasks],
            "players": len(tasks), "concurrency": cfg["concurrency"]}
    if a.dry_run:
        print(json.dumps({"dry_run": True, **plan}))
        return
    run = RUNS / f"subagents-{_slug(cfg['model'])}-{time.strftime('%Y%m%d-%H%M%S')}"
    run.mkdir(parents=True)
    m = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "config": cfg,
         "tasks": plan["tasks"], "files": {t["id"]: t["file"] for t in tasks}}
    (run / "manifest.json").write_text(json.dumps(m, indent=2))
    (RUNS / ".active").write_text(str(run))
    print(json.dumps({"run": str(run), **plan}))


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-." else "-" for c in text)


def next_tasks(run: pathlib.Path, now: float | None = None) -> list[str]:
    """Pending tasks to spawn now, marked spawned so they are never handed out twice."""
    m = manifest(run)
    st = states(run, now)
    slots = m["config"]["concurrency"] - sum(s in ACTIVE for s in st.values())
    picked = [t for t in m["tasks"] if st[t] == "pending"][:max(0, slots)]
    for t in picked:
        write_status(run, t, "spawned")
    return picked


def cmd_next(a):
    run = pathlib.Path(a.run)
    picked = next_tasks(run)
    st = states(run)
    print(json.dumps({"spawn": picked, "running": sum(s in ACTIVE for s in st.values()),
                      "pending": sum(s == "pending" for s in st.values()),
                      "finished": sum(s in FINAL for s in st.values()), "total": len(st)}))


def retry(run: pathlib.Path, task: str) -> str:
    """Archive the attempt; requeue it if retries remain, else mark it failed. Returns the new state."""
    m = manifest(run)
    if task not in m["tasks"]:
        raise SystemExit(f"task '{task}' is not part of {run}")
    if status(run, task)["state"] == "done":
        raise SystemExit(f"task '{task}' is already done")
    archive_attempt(run, task)
    if attempts(run, task) - m.get("retry_base", {}).get(task, 0) > m["config"]["retries"]:
        write_status(run, task, "failed", attempts=attempts(run, task))
        return "failed"
    return "pending"


def cmd_retry(a):
    run = pathlib.Path(a.run)
    print(json.dumps({"task": a.task, "state": retry(run, a.task), "attempts": attempts(run, a.task)}))


def cmd_timing(a):
    run = pathlib.Path(a.run)
    d = run / a.task
    d.mkdir(parents=True, exist_ok=True)
    (d / "timing.json").write_text(json.dumps({"total_tokens": a.tokens, "duration_ms": a.ms}))
    print(json.dumps({"task": a.task, "recorded": True}))


def resume(run: pathlib.Path) -> list[str]:
    """Requeue every unfinished task with a fresh retry budget. Returns the requeued ids."""
    requeued = []
    for task, state in states(run).items():
        if state == "done":
            continue
        if state != "pending":
            archive_attempt(run, task)
        requeued.append(task)
    m = manifest(run)
    m.setdefault("resumed", []).append(time.strftime("%Y-%m-%dT%H:%M:%S"))
    # retries are counted from the latest resume; earlier attempts stay archived for reference
    m["retry_base"] = {t: attempts(run, t) for t in requeued}
    (run / "manifest.json").write_text(json.dumps(m, indent=2))
    (RUNS / ".active").write_text(str(run))
    return requeued


def cmd_resume(a):
    run = pathlib.Path(a.run)
    requeued = resume(run)
    print(json.dumps({"run": str(run), "requeued": requeued, "model": manifest(run)["config"]["model"]}))


class Watcher:
    """Turns polled task states into one line per change, for the Monitor tool."""

    def __init__(self, run: pathlib.Path):
        self.run = run
        self.last: dict[str, str] | None = None

    def poll(self, now: float | None = None) -> list[str]:
        st = states(self.run, now)
        total = len(st)
        finished = sum(s in FINAL for s in st.values())
        if self.last is None:
            counts = {}
            for s in st.values():
                counts[s] = counts.get(s, 0) + 1
            lines = ["status " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))]
        else:
            lines = []
            for task, s in st.items():
                if s != self.last.get(task) and s not in QUIET:
                    suffix = f" ({finished}/{total} finished)" if s in FINAL else ""
                    lines.append(f"{s} {task}{suffix}")
        if finished == total and (self.last is None or any(v not in FINAL for v in self.last.values())):
            lines.append(f"all done {finished}/{total}")
        self.last = st
        return lines


def cmd_watch(a):
    w = Watcher(pathlib.Path(a.run))
    while True:
        for line in w.poll():
            print(line, flush=True)
            if line.startswith("all done"):
                return
        time.sleep(a.interval)


def cmd_aggregate(a):
    runs = [pathlib.Path(r) for r in a.runs]
    results, missing, configs = [], [], []
    for run in runs:
        m = manifest(run)
        configs.append(m["config"])
        for tid in m["tasks"]:
            f = run / tid / "result.json"
            if not f.exists():
                missing.append(tid)
                continue
            r = json.loads(f.read_text())
            timing = run / tid / "timing.json"
            if timing.exists():
                r["stats"].update(json.loads(timing.read_text()))
            results.append(r)
    if not results:
        raise SystemExit("no finished tasks in " + ", ".join(map(str, runs)))
    models = sorted({c["model"] for c in configs})
    out = runs[0] if len(runs) == 1 else RUNS / f"combined-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    summary = summarize(results)
    summary["agent"] = f"claude-code-subagents ({', '.join(models)})"
    summary["runs"] = [str(r) for r in runs]
    summary["config"] = configs[0] if len(configs) == 1 else configs
    summary["missing"] = missing
    tokens = [r["stats"]["total_tokens"] for r in results if "total_tokens" in r["stats"]]
    summary["total_tokens"] = sum(tokens) if tokens else None
    (out / "results.json").write_text(json.dumps(
        {"summary": summary, "results": [{k: v for k, v in r.items() if k != "svgs"} for r in results]}, indent=2))
    write_report(out / "report.html", summary, results)
    print(json.dumps({"overall": summary["overall"], "by_category": summary["by_category"],
                      "tasks": summary["tasks"], "missing": missing, "total_tokens": summary["total_tokens"],
                      "report": str(out / "report.html")}))


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
    p = sub.add_parser("next", help="task ids to spawn now")
    p.add_argument("run")
    p.set_defaults(fn=cmd_next)
    p = sub.add_parser("retry", help="archive a failed attempt and requeue or fail the task")
    p.add_argument("run")
    p.add_argument("task")
    p.set_defaults(fn=cmd_retry)
    p = sub.add_parser("timing", help="record a player's token and time cost")
    p.add_argument("run")
    p.add_argument("task")
    p.add_argument("--tokens", type=int, required=True)
    p.add_argument("--ms", type=int, required=True)
    p.set_defaults(fn=cmd_timing)
    p = sub.add_parser("resume", help="requeue a run's unfinished tasks")
    p.add_argument("run")
    p.set_defaults(fn=cmd_resume)
    p = sub.add_parser("watch", help="print task state changes until every task is finished")
    p.add_argument("run")
    p.add_argument("--interval", type=float, default=5.0)
    p.set_defaults(fn=cmd_watch)
    p = sub.add_parser("aggregate", help="merge one or more runs into a report")
    p.add_argument("runs", nargs="+")
    p.set_defaults(fn=cmd_aggregate)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
