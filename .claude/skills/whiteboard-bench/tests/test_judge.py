import json

import pytest
import wb
from test_mcp_server import replay_through_mcp


def scripted(*answers):
    it = iter(answers)
    return lambda prompt: next(it)


def played(make_run, judge, *tasks):
    run = make_run(*tasks, judge=judge)
    for t in tasks:
        replay_through_mcp(run, t)
    return run


def rubric_check(run, task):
    result = next(r for r in json.loads((run / "results.json").read_text())["results"] if r["task_id"] == task)
    return result, next(c for t in result["turns"] for c in t["checks"] + result["final_checks"]
                        if c["check"] == "rubric")


def test_off_captures_nothing(make_run):
    run = played(make_run, "off", "bs_yes_and")
    assert not (run / "bs_yes_and" / "rubric.json").exists()
    out = wb.aggregate([run])
    assert out["judge"] == "off" and out["awaiting_judgement"] == []
    _, check = rubric_check(run, "bs_yes_and")
    assert check["score"] is None and "no judge" in check["detail"]


def test_capture_has_what_the_judge_needs(make_run):
    run = played(make_run, "llm", "bs_yes_and")
    r = wb.rubric(run, "bs_yes_and")
    assert len(r["items"]) == 1
    item = r["items"][0]
    assert item["question"].startswith("Does each new sticky")
    assert item["requests"] and item["board"].count("\n") > 3
    prompt = wb.judge_prompt(r, item)
    assert "Rubric question:" in prompt and "Final board elements" in prompt


def test_human_judging_flow(make_run, capsys):
    run = played(make_run, "human", "bs_yes_and", "xr_focus_layers")
    out = wb.aggregate([run])
    assert sorted(out["awaiting_judgement"]) == ["bs_yes_and", "xr_focus_layers"]
    assert out["overall"] is None  # nothing counts until it is judged

    counts = wb.human_judge(run, ask=scripted("s", "12", "8", "clearly frames the options"))
    assert counts == {"scored": 1, "skipped": 1, "quit": False}
    assert (run / "bs_yes_and" / "review-0.html").read_text().count("<svg") == 1
    assert wb.scores(run, "xr_focus_layers")["0"]["human"]["score"] == 8

    out = wb.aggregate([run])
    assert out["awaiting_judgement"] == ["bs_yes_and"]
    _, check = rubric_check(run, "bs_yes_and")
    assert check["detail"] == "awaiting human judgement"

    counts = wb.human_judge(run, ask=scripted("6", "decent builds"))  # resumes with the skipped one
    assert counts["scored"] == 1
    out = wb.aggregate([run])
    assert out["awaiting_judgement"] == [] and out["overall"] is not None
    _, check = rubric_check(run, "bs_yes_and")
    assert check["score"] == 0.6 and check["detail"] == "judge: human 6/10: decent builds"


def test_quit_stops_early(make_run):
    run = played(make_run, "human", "bs_yes_and", "xr_focus_layers")
    assert wb.human_judge(run, ask=scripted("q"))["quit"] is True
    assert wb.scores(run, "bs_yes_and") == {}


def test_rejudge_keeps_both_scores_and_human_wins(make_run):
    run = played(make_run, "llm", "bs_yes_and")
    wb.record_score(run, "bs_yes_and", 0, "llm", 4, "generic")
    assert wb.human_judge(run, ask=scripted())["scored"] == 0  # already judged: nothing to do without --rejudge
    wb.human_judge(run, rejudge=True, ask=scripted("9", "specific and linked"))
    both = wb.scores(run, "bs_yes_and")["0"]
    assert both["llm"]["score"] == 4 and both["human"]["score"] == 9
    wb.aggregate([run])
    _, check = rubric_check(run, "bs_yes_and")
    assert check["score"] == 0.9
    assert check["detail"] == "judge: human 9/10: specific and linked | llm 4/10: generic"


def test_judge_without_score_is_closed_out(make_run):
    run = played(make_run, "llm", "bs_yes_and")
    assert wb.llm_judge_pending(run, "bs_yes_and")
    wb.main(["timing", str(run), "bs_yes_and", "--tokens", "10", "--ms", "1", "--role", "judge"])
    assert not wb.llm_judge_pending(run, "bs_yes_and")
    out = wb.aggregate([run])
    assert out["awaiting_judgement"] == ["bs_yes_and"]
    _, check = rubric_check(run, "bs_yes_and")
    assert "judge gave no score" in check["detail"]


@pytest.mark.parametrize("score", [-1, 11])
def test_score_range_is_enforced(make_run, score):
    run = played(make_run, "llm", "bs_yes_and")
    with pytest.raises(SystemExit, match="0 to 10"):
        wb.record_score(run, "bs_yes_and", 0, "llm", score, "x")


def test_score_needs_a_rubric(make_run):
    run = played(make_run, "llm", "dg_org_chart")
    with pytest.raises(SystemExit, match="no rubric"):
        wb.record_score(run, "dg_org_chart", 0, "llm", 5, "x")
