# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Run bookkeeping for /whiteboard-bench. Standard library only.

    wb.py list                           every task, with its number, category and rubric flag
    wb.py new <selector> [--model M] [--judge llm|human|off] [--dry-run]
                                         resolve the selection, create the run, make it active
    wb.py next <run>                     task ids to spawn now (respects concurrency)
    wb.py retry <run> <task>             archive a failed attempt; requeue it or mark it failed
    wb.py timing <run> <task> --tokens N --ms M
                                         record what a player cost
    wb.py resume <run>                   make an old run active again and requeue unfinished tasks
    wb.py watch <run>                    one line per state change, for the Monitor tool
    wb.py rubric <run> <task>            what an LLM judge grades (used by wbench-judge)
    wb.py score <run> <task> <item> <0-10> <reason> [--judge llm|human]
                                         record a rubric score
    wb.py judge <run> [--rejudge]        score rubric checks yourself, at the terminal
    wb.py aggregate <run> [<run> ...]    merge results into results.json + report.html

Selectors: a task by number, id or file stem (09, bs_divergent_ideas,
09_bs_divergent_ideas); a comma-separated list of those; a category
(diagramming); "all". A selector is always required: `list` shows the tasks.
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

Rubric checks (6 tasks) are graded after the player finishes. The board
server stores what a grader needs in <task>/rubric.json; scores go in
<task>/judge.json as {"<item>": {"llm": {...}, "human": {...}}}. A human
score wins over an LLM score. A task with an unscored rubric check is
reported as awaiting judgement and left out of the overall score until
it is scored. With judge = "off" rubric checks are left out entirely.
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

from wbench.harness import weighted  # noqa: E402
from wbench.report import write_report  # noqa: E402
from wbench.run import summarize  # noqa: E402

RUNS = ROOT / "runs"
CONFIG = pathlib.Path(__file__).resolve().parents[1] / "config.toml"
DEFAULTS = {"model": "inherit", "judge": "llm", "judge_model": "inherit",
            "concurrency": 6, "retries": 1, "stall_minutes": 10}
JUDGE_MODES = ("llm", "human", "off")
ACTIVE = {"spawned", "playing"}
RETRYABLE = {"abandoned", "error", "stalled"}
FINAL = {"done", "judged", "failed"}
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
        elif part in categories:
            chosen.update(t["id"] for t in index if t["category"] == part)
        else:
            match = [t for t in index if part in (t["num"], t["id"], t["stem"])
                     or (part.isdigit() and int(part) == int(t["num"]))]
            if not match:
                raise SystemExit(f"unknown selector '{part}'. Use a task number (09), id (bs_divergent_ideas), "
                                 f"file stem, a category ({', '.join(categories)}) or all. "
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
    if cfg["judge"] not in JUDGE_MODES:
        raise SystemExit(f"judge in {path} must be one of {', '.join(JUDGE_MODES)} (got {cfg['judge']!r})")
    for key, least in (("concurrency", 1), ("retries", 0), ("stall_minutes", 1)):
        if not isinstance(cfg[key], int) or cfg[key] < least:
            raise SystemExit(f"{key} in {path} must be a whole number of at least {least} (got {cfg[key]!r})")
    return cfg


def settings(a) -> dict:
    """config.toml, then flags. The result is what the run records and uses."""
    cfg = load_config(pathlib.Path(a.config) if a.config else None)
    if a.model:
        cfg["model"] = a.model
    if a.judge:
        cfg["judge"] = a.judge
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



# -- judging ---------------------------------------------------------------------

def rubric(run: pathlib.Path, task: str) -> dict | None:
    f = run / task / "rubric.json"
    return json.loads(f.read_text()) if f.exists() else None


def scores(run: pathlib.Path, task: str) -> dict:
    f = run / task / "judge.json"
    return json.loads(f.read_text()) if f.exists() else {}


def record_score(run: pathlib.Path, task: str, item: int, judge: str, score, reason: str):
    r = rubric(run, task)
    if r is None:
        raise SystemExit(f"task '{task}' has no rubric checks to score (or hasn't finished)")
    if not 0 <= item < len(r["items"]):
        raise SystemExit(f"item must be 0..{len(r['items']) - 1}")
    if score is not None and not (isinstance(score, (int, float)) and 0 <= score <= 10):
        raise SystemExit("score must be a number from 0 to 10")
    s = scores(run, task)
    s.setdefault(str(item), {})[judge] = {"score": score, "reason": reason, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (run / task / "judge.json").write_text(json.dumps(s, indent=2))


def llm_judge_pending(run: pathlib.Path, task: str) -> bool:
    """A finished task whose rubric checks still wait on the LLM judge (judge = "llm" only)."""
    r = rubric(run, task)
    if r is None or r["mode"] != "llm":
        return False
    s = scores(run, task)
    return any("llm" not in s.get(str(i), {}) for i in range(len(r["items"])))


def judge_prompt(r: dict, item: dict) -> str:
    """The same materials and wording as wbench.judge.AnthropicJudge."""
    return ("You are grading an AI collaborator's work on a shared whiteboard.\n\n"
            f"Task: {r['title']}\nRequests made:\n" + "\n".join(f"- {p}" for p in item["requests"])
            + f"\n\nFinal board elements (JSON lines):\n{item['board']}\n\n"
            f"What the AI said:\n{item['said'] or '(nothing)'}\n\n"
            f"Rubric question: {item['question']}\n"
            "Score from 0 to 10 where 10 means an excellent human facilitator could not do better.")


def cmd_rubric(a):
    run = pathlib.Path(a.run)
    r = rubric(run, a.task)
    if r is None:
        raise SystemExit(f"task '{a.task}' has no rubric checks to judge")
    for i, item in enumerate(r["items"]):
        print(f"=== item {i} ===\n{judge_prompt(r, item)}\n")


def cmd_score(a):
    run = pathlib.Path(a.run)
    record_score(run, a.task, a.item, a.judge, a.score, a.reason)
    print(json.dumps({"task": a.task, "item": a.item, "judge": a.judge, "score": a.score}))


def review_page(r: dict, item: dict, svg: str | None) -> str:
    esc = __import__("html").escape
    requests = "".join(f"<li>{esc(p)}</li>" for p in item["requests"])
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Judge: {esc(r['title'])}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:#222}}
.q{{font-size:1.25em;background:#f4f4f8;border-left:4px solid #556;padding:12px 16px}}
figure{{border:1px solid #ddd;border-radius:8px;padding:8px;margin:16px 0;overflow:auto}}figure svg{{max-width:100%;height:auto}}
pre{{white-space:pre-wrap;background:#fafafa;padding:8px}}</style></head><body>
<h1>{esc(r['title'])} <small>{esc(r['task_id'])}</small></h1>
<p class="q"><b>Rubric question:</b> {esc(item['question'])}<br>
Score from 0 to 10, where 10 means an excellent human facilitator could not do better.</p>
<h2>Requests made</h2><ol>{requests}</ol>
<h2>Final board</h2><figure>{svg or "<p>(no rendering)</p>"}</figure>
<h2>What the AI said</h2><pre>{esc(item['said'] or '(nothing)')}</pre>
<details><summary>Board elements as the judge sees them</summary><pre>{esc(item['board'])}</pre></details>
</body></html>"""


def human_judge(run: pathlib.Path, rejudge: bool = False, ask=input) -> dict:
    """Walk every rubric item that still needs a human score. Returns counts."""
    done = skipped = 0
    for task in manifest(run)["tasks"]:
        r = rubric(run, task)
        if r is None:
            continue
        result = json.loads((run / task / "result.json").read_text())
        for i, item in enumerate(r["items"]):
            s = scores(run, task).get(str(i), {})
            if "human" in s or (not rejudge and s.get("llm", {}).get("score") is not None):
                continue
            svg = result["svgs"].get(f"turn{item['turn']}")
            page = run / task / f"review-{i}.html"
            page.write_text(review_page(r, item, svg))
            print(f"\n{r['title']} ({task}), item {i}\n  {item['question']}\n  review: {page}")
            if "llm" in s and s["llm"].get("score") is not None:
                print("  (an LLM judge already scored this; your score will be shown next to it)")
            while True:
                answer = ask("  score 0-10, s = skip, q = quit: ").strip().lower()
                if answer in ("q", "s") or (answer.isdigit() and 0 <= int(answer) <= 10):
                    break
                print("  please enter a whole number from 0 to 10, s or q")
            if answer == "q":
                return {"scored": done, "skipped": skipped, "quit": True}
            if answer == "s":
                skipped += 1
                continue
            reason = ask("  one-line reason: ").strip()
            record_score(run, task, i, "human", int(answer), reason)
            done += 1
    return {"scored": done, "skipped": skipped, "quit": False}


def cmd_judge(a):
    run = pathlib.Path(a.run)
    counts = human_judge(run, a.rejudge)
    print(json.dumps(counts))
    aggregate([run])


def apply_judgement(run: pathlib.Path, task: str, r: dict, mode: str) -> bool:
    """Put judge scores into a result's rubric checks and recompute its scores. False if any is unscored."""
    rubric_items = rubric(run, task)
    if rubric_items is None:
        return True
    judged = scores(run, task)
    complete = True
    for i, item in enumerate(rubric_items["items"]):
        where = item["where"]
        check = r["turns"][where[1]]["checks"][where[2]] if where[0] == "turn" else r["final_checks"][where[1]]
        s = judged.get(str(i), {})
        human, llm = s.get("human"), s.get("llm")
        pick = human if human and human["score"] is not None else llm if llm and llm["score"] is not None else None
        if pick is None:
            complete = False
            check["score"] = None
            check["detail"] = ("awaiting human judgement" if mode == "human" else
                               f"judge gave no score: {llm['reason']}" if llm else "awaiting judge")
            continue
        check["score"] = round(pick["score"] / 10, 4)
        parts = [f"{who} {v['score']:g}/10: {v['reason']}" for who, v in (("human", human), ("llm", llm))
                 if v and v["score"] is not None]
        check["detail"] = "judge: " + " | ".join(parts)
    for t in r["turns"]:
        t["score"] = weighted(t["checks"])
    r["score"] = weighted([c for t in r["turns"] for c in t["checks"]] + r["final_checks"]) if complete else None
    return complete


# -- commands --------------------------------------------------------------------

def cmd_list(a):
    print(f"{'#':<3} {'id':<30} {'category':<14} {'turns':>5}  rubric")
    for t in task_index():
        print(f"{t['num']:<3} {t['id']:<30} {t['category']:<14} {t['turns']:>5}  {'yes' if t['rubric'] else ''}")


def cmd_new(a):
    if not a.selector:
        raise SystemExit("a selector is required: a task (09), a list (04,09,16), a category (diagramming) or all. "
                         "`just sub-list` shows every task.")
    cfg = settings(a)
    tasks = resolve(a.selector)
    plan = {"selector": a.selector, "model": cfg["model"], "judge": cfg["judge"],
            "tasks": [t["id"] for t in tasks], "players": len(tasks),
            "judges": sum(t["rubric"] for t in tasks) if cfg["judge"] == "llm" else 0,
            "concurrency": cfg["concurrency"]}
    if a.dry_run:
        print(json.dumps({"dry_run": True, **plan}))
        return
    run = RUNS / f"subagents-{_slug(cfg['model'])}-{time.strftime('%Y%m%d-%H%M%S')}"
    run.mkdir(parents=True)
    m = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "selector": a.selector, "config": cfg,
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


def judges_to_spawn(run: pathlib.Path) -> list[str]:
    """Finished tasks that need an LLM judge and don't have one yet, marked so they're handed out once."""
    picked = []
    for task in manifest(run)["tasks"]:
        marker = run / task / "judge.spawned"
        if status(run, task)["state"] == "done" and llm_judge_pending(run, task) and not marker.exists():
            marker.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"))
            picked.append(task)
    return picked


def cmd_next(a):
    run = pathlib.Path(a.run)
    picked = next_tasks(run)
    st = states(run)
    print(json.dumps({"spawn": picked, "judge": judges_to_spawn(run),
                      "running": sum(s in ACTIVE for s in st.values()),
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
    name = "timing.json" if a.role == "player" else "judge_timing.json"
    (d / name).write_text(json.dumps({"total_tokens": a.tokens, "duration_ms": a.ms}))
    if a.role == "judge" and llm_judge_pending(run, a.task):
        # the judge finished without scoring everything: close it out so the run can finish
        for i, _ in enumerate(rubric(run, a.task)["items"]):
            if "llm" not in scores(run, a.task).get(str(i), {}):
                record_score(run, a.task, i, "llm", None, "judge finished without a score")
    print(json.dumps({"task": a.task, "role": a.role, "recorded": True}))


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
        for task, s in st.items():
            if s == "done" and llm_judge_pending(self.run, task):
                st[task] = "judging"
            elif s == "done" and self.last and self.last.get(task) == "judging":
                st[task] = "judged"
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


def aggregate(runs: list[pathlib.Path]) -> dict:
    results, missing, awaiting, configs = [], [], [], []
    for run in runs:
        m = manifest(run)
        configs.append(m["config"])
        for tid in m["tasks"]:
            f = run / tid / "result.json"
            if not f.exists():
                missing.append(tid)
                continue
            r = json.loads(f.read_text())
            if not apply_judgement(run, tid, r, m["config"]["judge"]):
                awaiting.append(tid)
            for name, key in (("timing.json", "total_tokens"), ("judge_timing.json", "judge_tokens")):
                timing = run / tid / name
                if timing.exists():
                    r["stats"][key] = json.loads(timing.read_text())["total_tokens"]
            results.append(r)
    if not results:
        raise SystemExit("no finished tasks in " + ", ".join(map(str, runs)))
    models = sorted({c["model"] for c in configs})
    judges = sorted({c["judge"] for c in configs})
    out = runs[0] if len(runs) == 1 else RUNS / f"combined-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    summary = summarize(results)
    summary["agent"] = f"claude-code-subagents · {', '.join(models)} · judge: {', '.join(judges)}"
    summary["judge"] = judges[0] if len(judges) == 1 else judges
    summary["runs"] = [str(r) for r in runs]
    summary["config"] = configs[0] if len(configs) == 1 else configs
    summary["missing"] = missing
    summary["awaiting_judgement"] = awaiting
    player = [r["stats"]["total_tokens"] for r in results if "total_tokens" in r["stats"]]
    judge = [r["stats"]["judge_tokens"] for r in results if "judge_tokens" in r["stats"]]
    summary["total_tokens"] = sum(player) + sum(judge) if player or judge else None
    (out / "results.json").write_text(json.dumps(
        {"summary": summary, "results": [{k: v for k, v in r.items() if k != "svgs"} for r in results]}, indent=2))
    write_report(out / "report.html", summary, results)
    report = {"overall": summary["overall"], "by_category": summary["by_category"], "judge": summary["judge"],
              "tasks": summary["tasks"], "missing": missing, "awaiting_judgement": awaiting,
              "total_tokens": summary["total_tokens"], "report": str(out / "report.html")}
    print(json.dumps(report))
    return report


def cmd_aggregate(a):
    aggregate([pathlib.Path(r) for r in a.runs])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wb.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="show every task")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("new", help="create a run")
    p.add_argument("selector", nargs="?", help="task(s), a category, or all (required)")
    p.add_argument("--model", help="model the players run on (default: config model)")
    p.add_argument("--judge", choices=JUDGE_MODES, help="who grades rubric checks (default: config judge)")
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
    p.add_argument("--role", choices=("player", "judge"), default="player")
    p.set_defaults(fn=cmd_timing)
    p = sub.add_parser("resume", help="requeue a run's unfinished tasks")
    p.add_argument("run")
    p.set_defaults(fn=cmd_resume)
    p = sub.add_parser("watch", help="print task state changes until every task is finished")
    p.add_argument("run")
    p.add_argument("--interval", type=float, default=5.0)
    p.set_defaults(fn=cmd_watch)
    p = sub.add_parser("rubric", help="print what the LLM judge grades for a task")
    p.add_argument("run")
    p.add_argument("task")
    p.set_defaults(fn=cmd_rubric)
    p = sub.add_parser("score", help="record a rubric score")
    p.add_argument("run")
    p.add_argument("task")
    p.add_argument("item", type=int)
    p.add_argument("score", type=float)
    p.add_argument("reason")
    p.add_argument("--judge", choices=("llm", "human"), default="llm")
    p.set_defaults(fn=cmd_score)
    p = sub.add_parser("judge", help="score rubric checks yourself")
    p.add_argument("run")
    p.add_argument("--rejudge", action="store_true", help="also re-score items an LLM judge already scored")
    p.set_defaults(fn=cmd_judge)
    p = sub.add_parser("aggregate", help="merge one or more runs into a report")
    p.add_argument("runs", nargs="+")
    p.set_defaults(fn=cmd_aggregate)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
