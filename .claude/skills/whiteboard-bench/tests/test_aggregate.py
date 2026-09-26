import json

import wb

from wbench.agents.replay import ReplayAgent
from wbench.harness import run_task
from wbench.render import render_svg
from conftest import ROOT


def finish(run, task_id):
    task = json.loads(next((ROOT / "tasks").glob(f"*_{task_id}.json")).read_text())
    agent = ReplayAgent()
    agent.load(task)
    (run / task_id).mkdir()
    (run / task_id / "result.json").write_text(json.dumps(run_task(task, agent, render=render_svg)))


def test_aggregate_writes_results_and_report(make_run, capsys):
    run = make_run("dg_org_chart", "bs_yes_and")
    finish(run, "dg_org_chart")
    wb.main(["aggregate", str(run)])
    out = json.loads(capsys.readouterr().out)
    assert out["tasks"] == 1 and out["missing"] == ["bs_yes_and"]
    assert out["overall"] == 1.0
    summary = json.loads((run / "results.json").read_text())["summary"]
    assert summary["agent"].startswith("claude-code-subagents")
    html = (run / "report.html").read_text()
    assert "dg_org_chart" in html and "<svg" in html


def test_resolve_accepts_number_id_and_stem():
    assert wb.resolve("08")[0]["id"] == "dg_org_chart"
    assert wb.resolve("8")[0]["id"] == "dg_org_chart"
    assert wb.resolve("dg_org_chart")[0]["id"] == "dg_org_chart"
    assert wb.resolve("08_dg_org_chart")[0]["id"] == "dg_org_chart"
