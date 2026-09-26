"""Scripted human collaborator events.

Events simulate the other people at the board. They run between agent turns
or, with "at_call": k, in the middle of a turn right after the agent's k-th
tool call, so agents have to cope with a board that changes underneath them.

Targets are resolved by content, so events work no matter where the agent put
things. Pointing events report only coordinates: the agent must work out
which element is being pointed at.
"""
from __future__ import annotations

from .board import rect_of, overlap_area
from .checks import find_one, select


def display_name(actor, participants):
    if not actor.startswith("human:"):
        return actor
    key = actor.split(":", 1)[1]
    p = participants.get(key) or {}
    return p.get("name") or key.capitalize()


def _target(board, spec):
    if isinstance(spec, str):
        el = find_one(board, spec)
    elif "id" in spec:
        el = board.elements.get(spec["id"])
    else:
        els = select(board, spec)
        el = els[0] if els else None
    if el is None:
        raise LookupError(f"event target not found: {spec}")
    return el


def _free_spot(board, frame, w, h, ignore=None):
    fx, fy, fx1, fy1 = rect_of(frame)
    others = [board.bbox(e) for e in board.elements.values()
              if e["type"] in ("sticky", "shape", "text") and e["id"] != ignore]
    y = fy + 60
    while y + h <= fy1 - 10:
        x = fx + 20
        while x + w <= fx1 - 10:
            r = (x, y, x + w, y + h)
            if all(overlap_area(r, o) == 0 for o in others):
                return x, y
            x += 20
        y += 20
    return fx + (frame["w"] - w) / 2, fy + (frame["h"] - h) / 2


def _placement(board, ev, w, h, ignore=None):
    """Resolve absolute x/y, into_frame (free spot or center) or near+offset."""
    if "into_frame" in ev:
        frame = find_one(board, ev["into_frame"], {"type": "frame"})
        if frame is None:
            raise LookupError(f"frame not found: {ev['into_frame']}")
        if ev.get("placement") == "center":
            return frame["x"] + (frame["w"] - w) / 2, frame["y"] + (frame["h"] - h) / 2
        return _free_spot(board, frame, w, h, ignore)
    if "near" in ev:
        ref = _target(board, ev["near"])
        dx, dy = ev.get("offset", [220, 0])
        return ref["x"] + dx, ref["y"] + dy
    return ev["x"], ev["y"]


def apply_event(board, ev, participants):
    """Apply one event and return a natural-language description for the agent."""
    actor = ev.get("actor", "human:facilitator")
    who = display_name(actor, participants)
    op = ev["op"]
    if op == "say":
        return f'{who} says: "{ev["text"]}"'
    if op == "point":
        if "target" in ev:
            el = _target(board, ev["target"])
            cx, cy = board.center(el)
            ox, oy = ev.get("jitter", [0, 0])
            x, y = cx + ox, cy + oy
        else:
            x, y = ev["at"]
        verb = ev.get("verb", "points at")
        return f"{who} {verb} board position ({x:.0f}, {y:.0f})"

    board.begin(actor)
    try:
        if op == "create":
            el = dict(ev["element"])
            etype = el.pop("type")
            if any(k in ev for k in ("into_frame", "near")):
                w, h = el.get("w", 160), el.get("h", 160)
                el["x"], el["y"] = _placement(board, ev, w, h)
            eid = board.create(actor, etype, **el)
            e = board.elements[eid]
            desc = f'{who} added a {etype} "{e.get("text", "")}" (id {eid}) at ({e["x"]:.0f}, {e["y"]:.0f})'
        elif op == "update":
            el = _target(board, ev["target"])
            board.update(actor, el["id"], **ev["fields"])
            desc = f"{who} edited {el['type']} {el['id']}: " + ", ".join(
                f"{k} -> {v!r}" for k, v in ev["fields"].items())
        elif op == "move":
            el = _target(board, ev["target"])
            if "dx" in ev:
                board.translate(actor, [el["id"]], ev["dx"], ev["dy"])
            else:
                x, y = _placement(board, ev, el["w"], el["h"], ignore=el["id"])
                board.move_to(actor, el["id"], x, y)
            desc = f'{who} moved "{el.get("text", "")}" (id {el["id"]}) to ({el["x"]:.0f}, {el["y"]:.0f})'
        elif op == "delete":
            el = _target(board, ev["target"])
            board.delete(actor, [el["id"]])
            desc = f'{who} deleted "{el.get("text", "")}" (id {el["id"]})'
        elif op == "vote":
            el = _target(board, ev["target"])
            board.add_votes(actor, el["id"], ev["count"])
            desc = (f'{who} added {ev["count"]} vote(s) to "{el["text"]}" (id {el["id"]}); '
                    f'it now has {el["votes"]}')
        elif op == "comment":
            el = _target(board, ev["target"])
            board.add_comment(actor, el["id"], ev["text"])
            desc = f'{who} commented on {el["id"]}: "{ev["text"]}"'
        else:
            raise ValueError(f"unknown event op {op}")
    except Exception:
        board.rollback()
        raise
    board.commit()
    return desc
