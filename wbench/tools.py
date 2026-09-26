"""Agent-facing tool API.

Tool schemas follow the JSON-schema `input_schema` convention used by most
LLM tool-use APIs, so they can be passed through to a model unchanged.
"""
from __future__ import annotations

from .board import COLORS, SHAPE_KINDS, BoardError
from . import textmatch

_color = {"type": "string", "enum": list(COLORS)}
_id_list = {"type": "array", "items": {"type": "string"}}
_layer = {"type": "integer", "description": "Depth layer. 0 = board surface, >0 floats toward viewers (XR), <0 pushed behind."}


def _tool(name, description, props=None, required=()):
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": props or {}, "required": list(required)}}


TOOLS = [
    _tool("get_board",
          "Return every element on the board (or those inside one frame / region). "
          "Coordinates are in board pixels; x grows right, y grows down; (x, y) is the top-left corner.",
          {"frame_id": {"type": "string", "description": "Only elements inside this frame."},
           "region": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"},
                                                        "w": {"type": "number"}, "h": {"type": "number"}}},
           "types": {"type": "array", "items": {"type": "string"}}}),
    _tool("find_elements", "Search elements by fuzzy text and/or attributes.",
          {"query": {"type": "string"}, "type": {"type": "string"}, "color": _color,
           "frame_id": {"type": "string"}, "author": {"type": "string", "description": "'agent', 'human', or 'human:<name>'"}}),
    _tool("get_elements_at", "List elements at or near a board position, nearest first. Use this to resolve pointing and gaze.",
          {"x": {"type": "number"}, "y": {"type": "number"}, "radius": {"type": "number"}}, ["x", "y"]),
    _tool("create_sticky", "Create a sticky note (default 160x160, yellow).",
          {"text": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"},
           "color": _color, "w": {"type": "number"}, "h": {"type": "number"}, "layer": _layer},
          ["text", "x", "y"]),
    _tool("create_shape", "Create a diagram shape with optional text inside (default 180x90).",
          {"kind": {"type": "string", "enum": list(SHAPE_KINDS)}, "x": {"type": "number"}, "y": {"type": "number"},
           "w": {"type": "number"}, "h": {"type": "number"}, "text": {"type": "string"}, "color": _color, "layer": _layer},
          ["kind", "x", "y"]),
    _tool("create_text", "Create a free text label or heading.",
          {"text": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"},
           "font_size": {"type": "number"}, "w": {"type": "number"}, "h": {"type": "number"}, "color": _color, "layer": _layer},
          ["text", "x", "y"]),
    _tool("create_frame", "Create a titled frame (a region that contains elements). Moving a frame moves its contents.",
          {"title": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"},
           "w": {"type": "number"}, "h": {"type": "number"}, "color": _color},
          ["title", "x", "y", "w", "h"]),
    _tool("create_connector", "Connect two elements with a line or arrow.",
          {"source_id": {"type": "string"}, "target_id": {"type": "string"}, "label": {"type": "string"},
           "directed": {"type": "boolean", "description": "Arrow from source to target (default true)."}, "color": _color},
          ["source_id", "target_id"]),
    _tool("draw_stroke", "Draw a freehand stroke through the given points (e.g. to circle or underline something).",
          {"points": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}}, "color": _color, "layer": _layer},
          ["points"]),
    _tool("update_element", "Change text, color, shape kind, layer, tags, or connector label/direction of one element.",
          {"id": {"type": "string"}, "text": {"type": "string"}, "color": _color,
           "kind": {"type": "string", "enum": list(SHAPE_KINDS)}, "layer": _layer,
           "tags": {"type": "array", "items": {"type": "string"}}, "label": {"type": "string"},
           "directed": {"type": "boolean"}},
          ["id"]),
    _tool("move_elements", "Move elements so their top-left corners land at absolute positions.",
          {"moves": {"type": "array", "items": {"type": "object", "properties": {
              "id": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"}}, "required": ["id", "x", "y"]}}},
          ["moves"]),
    _tool("translate_elements", "Shift elements by (dx, dy).",
          {"ids": _id_list, "dx": {"type": "number"}, "dy": {"type": "number"}}, ["ids", "dx", "dy"]),
    _tool("resize_element", "Set an element's width and height.",
          {"id": {"type": "string"}, "w": {"type": "number"}, "h": {"type": "number"}}, ["id", "w", "h"]),
    _tool("arrange", "Lay elements out in a row, column, or grid starting at (x, y), in the order given.",
          {"ids": _id_list, "layout": {"type": "string", "enum": ["row", "column", "grid"]},
           "x": {"type": "number"}, "y": {"type": "number"}, "gap": {"type": "number"},
           "columns": {"type": "integer"}},
          ["ids", "layout", "x", "y"]),
    _tool("align", "Align elements along an edge or center line.",
          {"ids": _id_list, "edge": {"type": "string", "enum": ["left", "right", "top", "bottom", "center_x", "center_y"]}},
          ["ids", "edge"]),
    _tool("delete_elements", "Delete elements. Connectors attached to them are deleted too.", {"ids": _id_list}, ["ids"]),
    _tool("group", "Group elements so they read as one unit.", {"ids": _id_list, "name": {"type": "string"}}, ["ids"]),
    _tool("ungroup", "Remove elements from their group.", {"ids": _id_list}, ["ids"]),
    _tool("add_comment", "Attach a comment to an element without changing it.",
          {"id": {"type": "string"}, "text": {"type": "string"}}, ["id", "text"]),
    _tool("undo", "Undo your own most recent tool call. Changes other people made since then are kept."),
    _tool("say", "Say something to the people at the board (questions, summaries, confirmations).",
          {"message": {"type": "string"}}, ["message"]),
    _tool("finish_turn", "Signal that you have finished responding to the current request.",
          {"summary": {"type": "string"}}),
]
TOOL_NAMES = {t["name"] for t in TOOLS}
_SCHEMAS = {t["name"]: t["input_schema"] for t in TOOLS}
_JSON_TYPES = {"string": str, "number": (int, float), "integer": int, "boolean": bool,
               "array": list, "object": dict}


def _validate(name, args):
    schema = _SCHEMAS[name]
    if not isinstance(args, dict):
        raise BoardError("arguments must be an object")
    for req in schema["required"]:
        if req not in args:
            raise BoardError(f"missing required argument '{req}'")
    for k, v in args.items():
        spec = schema["properties"].get(k)
        if spec is None:
            raise BoardError(f"unknown argument '{k}'")
        py = _JSON_TYPES[spec["type"]]
        if isinstance(v, bool) and spec["type"] in ("number", "integer"):
            raise BoardError(f"'{k}' must be a {spec['type']}")
        if not isinstance(v, py):
            raise BoardError(f"'{k}' must be a {spec['type']}")
        if "enum" in spec and v not in spec["enum"]:
            raise BoardError(f"'{k}' must be one of {spec['enum']}")


class ToolExecutor:
    """Executes tool calls against a board on behalf of one actor."""

    def __init__(self, board, actor="agent"):
        self.board = board
        self.actor = actor
        self.messages: list[dict] = []   # things the agent said
        self.finished = False

    def call(self, name, args=None):
        args = args or {}
        if name not in TOOL_NAMES:
            return {"ok": False, "error": f"unknown tool '{name}'"}
        try:
            _validate(name, args)
        except BoardError as e:
            return {"ok": False, "error": str(e)}
        b = self.board
        b.begin(self.actor)
        try:
            result = getattr(self, "_t_" + name)(**args)
        except BoardError as e:
            b.rollback()
            return {"ok": False, "error": str(e)}
        except Exception as e:  # defensive: never crash the harness
            b.rollback()
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        b.commit()
        out = {"ok": True}
        out.update(result or {})
        return out

    # ------------------------------------------------------------- reading
    def _t_get_board(self, frame_id=None, region=None, types=None):
        b = self.board
        els = list(b.elements.values())
        if frame_id:
            f = b.get(frame_id)
            if f["type"] != "frame":
                raise BoardError(f"'{frame_id}' is not a frame")
            inside = set(b.descendants(frame_id))
            els = [e for e in els if e["id"] in inside or (
                e["type"] == "connector" and (e["source"] in inside or e["target"] in inside))]
        if region:
            r = (region.get("x", 0), region.get("y", 0),
                 region.get("x", 0) + region.get("w", 0), region.get("y", 0) + region.get("h", 0))
            els = [e for e in els if e["type"] == "connector" or _intersects(b.bbox(e), r)]
        if types:
            els = [e for e in els if e["type"] in types]
        return {"elements": [b.describe(e) for e in els], "count": len(els)}

    def _t_find_elements(self, query=None, type=None, color=None, frame_id=None, author=None):
        b = self.board
        scored = []
        for e in b.elements.values():
            if type and e["type"] != type:
                continue
            if color and e["color"] != color:
                continue
            if author and not _author_ok(e["author"], author):
                continue
            if frame_id and frame_id not in [f["id"] for f in b.frames_containing(e)]:
                continue
            s = 1.0
            if query:
                s = textmatch.score(query, e.get("text") or e.get("label") or "")
                if s < 0.5:
                    continue
            scored.append((s, e))
        scored.sort(key=lambda t: -t[0])
        return {"elements": [b.describe(e) for _, e in scored[:50]]}

    def _t_get_elements_at(self, x, y, radius=0):
        return {"elements": [self.board.describe(e) for e in self.board.elements_at(x, y, radius)[:10]]}

    # ------------------------------------------------------------ creating
    def _t_create_sticky(self, text, x, y, color=None, w=None, h=None, layer=0):
        return {"id": self.board.create(self.actor, "sticky", text=text, x=x, y=y, color=color, w=w, h=h, layer=layer)}

    def _t_create_shape(self, kind, x, y, w=None, h=None, text="", color=None, layer=0):
        return {"id": self.board.create(self.actor, "shape", kind=kind, x=x, y=y, w=w, h=h, text=text, color=color, layer=layer)}

    def _t_create_text(self, text, x, y, font_size=None, w=None, h=None, color=None, layer=0):
        if w is None:
            fs = font_size or 24
            w = max(40, len(text) * fs * 0.55 + 10)
        return {"id": self.board.create(self.actor, "text", text=text, x=x, y=y, font_size=font_size, w=w, h=h, color=color, layer=layer)}

    def _t_create_frame(self, title, x, y, w, h, color=None):
        return {"id": self.board.create(self.actor, "frame", text=title, x=x, y=y, w=w, h=h, color=color)}

    def _t_create_connector(self, source_id, target_id, label="", directed=True, color=None):
        return {"id": self.board.create(self.actor, "connector", source=source_id, target=target_id,
                                        label=label, directed=directed, color=color)}

    def _t_draw_stroke(self, points, color=None, layer=0):
        return {"id": self.board.create(self.actor, "stroke", points=points, color=color, layer=layer)}

    # ------------------------------------------------------------ changing
    def _t_update_element(self, id, **fields):
        if not fields:
            raise BoardError("nothing to update")
        self.board.update(self.actor, id, **fields)
        return {"element": self.board.describe(self.board.get(id))}

    def _t_move_elements(self, moves):
        moved = []
        for m in moves:
            if not isinstance(m, dict) or not {"id", "x", "y"} <= set(m):
                raise BoardError("each move needs id, x, y")
            moved += self.board.move_to(self.actor, m["id"], m["x"], m["y"])
        return {"moved": sorted(set(moved))}

    def _t_translate_elements(self, ids, dx, dy):
        return {"moved": self.board.translate(self.actor, ids, dx, dy)}

    def _t_resize_element(self, id, w, h):
        self.board.update(self.actor, id, w=w, h=h)
        return {}

    def _t_arrange(self, ids, layout, x, y, gap=20, columns=None):
        b = self.board
        els = [b.get(i) for i in ids]
        if any(e["type"] == "connector" for e in els):
            raise BoardError("connectors cannot be arranged")
        if layout == "row":
            columns = len(els)
        elif layout == "column":
            columns = 1
        else:
            columns = columns or max(1, round(len(els) ** 0.5))
        cw = max(b.bbox(e)[2] - b.bbox(e)[0] for e in els)
        ch = max(b.bbox(e)[3] - b.bbox(e)[1] for e in els)
        for i, e in enumerate(els):
            r, c = divmod(i, columns)
            b.move_to(self.actor, e["id"], x + c * (cw + gap), y + r * (ch + gap))
        return {"moved": ids}

    def _t_align(self, ids, edge):
        b = self.board
        els = [b.get(i) for i in ids]
        boxes = [b.bbox(e) for e in els]
        if edge == "left":
            t = min(bx[0] for bx in boxes); f = lambda bx: (t - bx[0], 0)
        elif edge == "right":
            t = max(bx[2] for bx in boxes); f = lambda bx: (t - bx[2], 0)
        elif edge == "top":
            t = min(bx[1] for bx in boxes); f = lambda bx: (0, t - bx[1])
        elif edge == "bottom":
            t = max(bx[3] for bx in boxes); f = lambda bx: (0, t - bx[3])
        elif edge == "center_x":
            t = sum((bx[0] + bx[2]) / 2 for bx in boxes) / len(boxes); f = lambda bx: (t - (bx[0] + bx[2]) / 2, 0)
        else:
            t = sum((bx[1] + bx[3]) / 2 for bx in boxes) / len(boxes); f = lambda bx: (0, t - (bx[1] + bx[3]) / 2)
        for e, bx in zip(els, boxes):
            dx, dy = f(bx)
            b.translate(self.actor, [e["id"]], dx, dy, carry=True)
        return {"aligned": ids}

    def _t_delete_elements(self, ids):
        return {"deleted": self.board.delete(self.actor, ids)}

    def _t_group(self, ids, name=None):
        gid = name or f"g{self.board.step}"
        self.board.set_group(self.actor, ids, gid)
        return {"group": gid}

    def _t_ungroup(self, ids):
        self.board.set_group(self.actor, ids, None)
        return {}

    def _t_add_comment(self, id, text):
        self.board.add_comment(self.actor, id, text)
        return {}

    def _t_undo(self):
        self.board.commit()          # close the (empty) txn opened for this call
        reverted, conflicts = self.board.undo(self.actor)
        self.board.begin(self.actor)  # reopen so call() can commit normally
        out = {"reverted": reverted}
        if conflicts:
            out["kept_because_others_edited"] = conflicts
        return out

    # ----------------------------------------------------------- dialogue
    def _t_say(self, message):
        self.messages.append({"turn": self.board.turn, "kind": "say", "text": message})
        return {}

    def _t_finish_turn(self, summary=""):
        if summary:
            self.messages.append({"turn": self.board.turn, "kind": "summary", "text": summary})
        self.finished = True
        return {}


def _intersects(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _author_ok(author, want):
    if want == "agent":
        return author == "agent"
    if want == "human":
        return author.startswith("human")
    return author == want
