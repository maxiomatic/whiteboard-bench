"""The whole /whiteboard-bench loop with scripted players instead of subagents.

Mirrors SKILL.md: next -> spawn players -> react to watch events -> aggregate.
Players replay reference solutions over real MCP stdio, in parallel threads.
"""
import json
import threading

import wb
from test_mcp_server import replay_through_mcp


def test_run_a_category_in_parallel_with_one_abandoned_player(make_run, capsys):
    tasks = ["dg_org_chart", "bs_yes_and", "co_protected_region", "pl_kanban_updates"]
    run = make_run(*tasks)  # concurrency 2, retries 1
    flaky = {"bs_yes_and"}  # first player for this task gives up without playing
    threads, events = [], []
    watcher = wb.Watcher(run)
    watcher.poll()

    def player(task):
        if task in flaky:
            flaky.discard(task)
            wb.write_status(run, task, "abandoned")
            return
        replay_through_mcp(run, task)

    def spawn():
        for task in wb.next_tasks(run):
            t = threading.Thread(target=player, args=(task,))
            t.start()
            threads.append(t)

    spawn()
    for _ in range(200):
        for t in threads:
            t.join(timeout=0.05)
        for line in watcher.poll():
            events.append(line)
            kind, task = line.split()[0], line.split()[1]
            if kind == "done":
                spawn()
            elif kind in ("abandoned", "error", "stalled"):
                assert wb.retry(run, task) == "pending"
                spawn()
        if events and events[-1].startswith("all done"):
            break
    for t in threads:
        t.join()

    assert events[-1] == "all done 4/4"
    assert "abandoned bs_yes_and" in events
    assert (run / ".attempts" / "bs_yes_and-1").exists()
    wb.main(["aggregate", str(run)])
    out = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert out["overall"] == 1.0 and out["tasks"] == 4 and out["missing"] == []


def test_llm_judge_runs_after_the_player_and_counts(make_run, capsys):
    run = make_run("dg_org_chart", "bs_yes_and", judge="llm")  # bs_yes_and has a rubric check
    watcher = wb.Watcher(run)
    watcher.poll()
    events, judged = [], []
    for task in wb.next_tasks(run):
        replay_through_mcp(run, task)
        events += watcher.poll()
    assert "judging bs_yes_and" in events and "done dg_org_chart (1/2 finished)" in events
    for _ in range(50):
        for task in wb.judges_to_spawn(run):  # what `just sub-next` hands to wbench-judge
            judged.append(task)
            for i, _ in enumerate(wb.rubric(run, task)["items"]):
                wb.record_score(run, task, i, "llm", 7, "builds on most ideas")
            wb.main(["timing", str(run), task, "--tokens", "500", "--ms", "9", "--role", "judge"])
        events += watcher.poll()
        if events and events[-1].startswith("all done"):
            break
    assert judged == ["bs_yes_and"]
    assert wb.judges_to_spawn(run) == []  # handed out once
    assert "judged bs_yes_and (2/2 finished)" in events and events[-1] == "all done 2/2"
    capsys.readouterr()
    out = wb.aggregate([run])
    assert out["judge"] == "llm" and out["awaiting_judgement"] == []
    result = next(r for r in json.loads((run / "results.json").read_text())["results"] if r["task_id"] == "bs_yes_and")
    rubric = next(c for t in result["turns"] for c in t["checks"] + result["final_checks"] if c["check"] == "rubric")
    assert rubric["score"] == 0.7 and "llm 7/10" in rubric["detail"]
    assert 0 < result["score"] < 1.0
