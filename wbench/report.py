"""Self-contained HTML report with per-check scores and board renderings."""
import html


def _pct(s):
    return "n/a" if s is None else f"{s * 100:.0f}%"


def _bar(s):
    if s is None:
        return '<span class="na">skipped</span>'
    hue = int(120 * s)
    return (f'<span class="bar"><span style="width:{s * 100:.0f}%;background:hsl({hue},60%,48%)"></span></span>'
            f' {_pct(s)}')


def _checks_table(checks):
    rows = "".join(
        f"<tr><td>{html.escape(c['label'])}</td><td>{c['weight']:g}</td><td>{_bar(c['score'])}</td>"
        f"<td class=d>{html.escape(str(c['detail']))}</td></tr>" for c in checks)
    return f"<table><tr><th>check</th><th>w</th><th>score</th><th>detail</th></tr>{rows}</table>"


def write_report(path, summary, results):
    cats = "".join(f"<tr><td>{html.escape(c)}</td><td>{_bar(s)}</td></tr>" for c, s in summary["by_category"].items())
    idx = "".join(
        f'<tr><td><a href="#{r["task_id"]}">{html.escape(r["task_id"])}</a></td><td>{r["category"]}</td>'
        f'<td>{r["difficulty"]}</td><td>{_bar(r["score"])}</td><td>{r["stats"]["tool_calls"]}</td>'
        f'<td>{r["stats"]["tool_errors"]}</td></tr>' for r in results)
    secs = []
    for r in results:
        turns = "".join(
            f"<h4>Turn {t['turn']} &middot; {_pct(t['score'])} &middot; {t['calls']} calls"
            + (f" &middot; <span class=err>agent error: {html.escape(t['agent_error'])}</span>" if t['agent_error'] else "")
            + f"</h4>{_checks_table(t['checks'])}" for t in r["turns"] if t["checks"] or t["agent_error"])
        final = f"<h4>Final checks</h4>{_checks_table(r['final_checks'])}" if r["final_checks"] else ""
        said = "".join(f"<li><b>turn {m['turn']}</b>: {html.escape(m['text'])}</li>" for m in r["messages"])
        boards = "".join(f"<figure><figcaption>{k}</figcaption>{v}</figure>"
                         for k, v in r["svgs"].items() if v and (k == "initial" or k == f"turn{len(r['turns'])}"))
        secs.append(
            f'<section id="{r["task_id"]}"><h2>{html.escape(r["title"])} <small>{r["task_id"]} &middot; '
            f'{_pct(r["score"])}</small></h2>{turns}{final}'
            + (f"<h4>Agent said</h4><ul>{said}</ul>" if said else "")
            + f'<div class="boards">{boards}</div></section>')
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WhiteboardBench report: {html.escape(summary['agent'])}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0 auto;max-width:1300px;padding:24px;color:#222}}
table{{border-collapse:collapse;margin:8px 0 16px;font-size:14px}}td,th{{border-bottom:1px solid #e3e3e3;padding:4px 10px;text-align:left;vertical-align:top}}
.bar{{display:inline-block;width:90px;height:9px;background:#eee;border-radius:5px;overflow:hidden;vertical-align:middle}}
.bar span{{display:block;height:100%}}.d{{color:#666;font-size:12px;max-width:560px}}.na{{color:#999}}.err{{color:#c62828}}
section{{border-top:2px solid #ddd;margin-top:28px}}.boards{{display:flex;flex-wrap:wrap;gap:16px}}
figure{{margin:0;flex:1 1 520px;border:1px solid #ddd;border-radius:8px;padding:8px;overflow:auto}}figure svg{{max-width:100%;height:auto}}
</style></head><body>
<h1>WhiteboardBench &middot; {html.escape(summary['agent'])}</h1>
<p><b>Overall: {_pct(summary['overall'])}</b> (mean of category means) &middot; {summary['tasks']} tasks &middot;
{summary['tool_calls']} tool calls &middot; error rate {summary['tool_error_rate']:.1%}</p>
<table><tr><th>category</th><th>score</th></tr>{cats}</table>
<table><tr><th>task</th><th>category</th><th>difficulty</th><th>score</th><th>calls</th><th>errors</th></tr>{idx}</table>
{''.join(secs)}</body></html>"""
    with open(path, "w") as f:
        f.write(doc)
