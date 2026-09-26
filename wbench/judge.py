"""Optional LLM judge for `rubric` checks (qualitative dimensions such as
idea quality or theme naming). Deterministic checks never depend on it."""
import json
import os
import re

from .agents.anthropic_agent import post


def board_as_text(board):
    lines = []
    for el in board.elements.values():
        d = board.describe(el)
        lines.append(json.dumps({k: v for k, v in d.items() if k not in ("comments",)}))
    return "\n".join(lines)


class AnthropicJudge:
    def __init__(self, model="claude-opus-5-5"):
        self.model = model
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise SystemExit("Set ANTHROPIC_API_KEY to use the judge")

    def __call__(self, board, spec, ctx):
        said = "\n".join(m["text"] for m in ctx.messages)
        prompt = (
            "You are grading an AI collaborator's work on a shared whiteboard.\n\n"
            f"Task: {ctx.task['title']}\nRequests made:\n"
            + "\n".join(f"- {t['prompt']}" for t in ctx.task["turns"][: ctx.turn])
            + f"\n\nFinal board elements (JSON lines):\n{board_as_text(board)}\n\n"
            f"What the AI said:\n{said or '(nothing)'}\n\n"
            f"Rubric question: {spec['question']}\n"
            "Score from 0 to 10 where 10 means an excellent human facilitator could not do better. "
            'Reply with JSON only: {"score": <0-10>, "reason": "<one sentence>"}')
        resp = post({"model": self.model, "max_tokens": 400,
                     "messages": [{"role": "user", "content": prompt}]}, self.api_key)
        text = "".join(c.get("text", "") for c in resp.get("content", []))
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0)) if m else {"score": 0, "reason": "unparseable judge output"}
        return max(0.0, min(1.0, float(data["score"]) / 10)), f"judge: {data.get('reason', '')}"
