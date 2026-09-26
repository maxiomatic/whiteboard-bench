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



def test_aggregate_merges_runs_and_timing(make_run, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(wb, "RUNS", tmp_path / "runs")
    first = make_run("dg_org_chart")
    finish(first, "dg_org_chart")
    wb.main(["timing", str(first), "dg_org_chart", "--tokens", "1000", "--ms", "10"])
    second = first.parent / "second"
    second.mkdir()
    (second / "manifest.json").write_text((first / "manifest.json").read_text().replace("dg_org_chart", "bs_yes_and"))
    finish(second, "bs_yes_and")
    capsys.readouterr()
    wb.main(["aggregate", str(first), str(second)])
    out = json.loads(capsys.readouterr().out)
    assert out["tasks"] == 2 and out["total_tokens"] == 1000
    assert "combined-" in out["report"]
    results = json.loads((tmp_path / "runs" / out["report"].split("/")[-2] / "results.json").read_text())
    assert len(results["summary"]["runs"]) == 2
