"""Whiteboard state model.

The board is a flat collection of elements on an infinite 2D canvas with an
integer depth `layer` (used by XR tasks: 0 = board surface, positive values
float toward the viewer, negative values sit behind the surface).

Every mutation is attributed to an actor ("agent", "human:maya", ...) and is
recorded in an append-only log. Mutations are grouped into transactions so a
single tool call can be undone as one unit, the way people expect "undo" to
work on a shared board.
"""
from __future__ import annotations

import copy
import itertools
import math

ELEMENT_TYPES = ("sticky", "shape", "text", "frame", "connector", "stroke")
SHAPE_KINDS = (
    "rect", "rounded_rect", "ellipse", "diamond", "triangle",
    "cylinder", "parallelogram", "hexagon", "cloud",
)
COLORS = ("yellow", "orange", "pink", "red", "purple", "blue", "green",
          "gray", "white", "black")
DEFAULT_SIZE = {"sticky": (160, 160), "shape": (180, 90), "text": (240, 40),
                "frame": (800, 600)}
DEFAULT_COLOR = {"sticky": "yellow", "shape": "white", "text": "black",
                 "frame": "white", "connector": "black", "stroke": "black"}
BOX_TYPES = ("sticky", "shape", "text", "frame")

UPDATABLE = {
    "sticky": {"text", "color", "tags", "layer", "w", "h"},
    "shape": {"text", "color", "kind", "tags", "layer", "w", "h"},
    "text": {"text", "color", "font_size", "tags", "layer", "w", "h"},
    "frame": {"text", "color", "tags", "layer", "w", "h"},
    "connector": {"label", "color", "directed", "tags", "source", "target"},
    "stroke": {"color", "tags", "layer", "points"},
}


class BoardError(ValueError):
    """Raised for invalid operations. Tool calls surface these as errors."""


def _num(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BoardError(f"'{name}' must be a number")
    if math.isnan(value) or math.isinf(value):
        raise BoardError(f"'{name}' must be finite")
    return float(value)


def rect_of(el):
    return (el["x"], el["y"], el["x"] + el["w"], el["y"] + el["h"])


def overlap_area(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    w = min(ax1, bx1) - max(ax0, bx0)
    h = min(ay1, by1) - max(ay0, by0)
    return w * h if w > 0 and h > 0 else 0.0


def point_in_rect(px, py, r, pad=0.0):
    return r[0] - pad <= px <= r[2] + pad and r[1] - pad <= py <= r[3] + pad


def dist_point_rect(px, py, r):
    dx = max(r[0] - px, 0, px - r[2])
    dy = max(r[1] - py, 0, py - r[3])
    return math.hypot(dx, dy)


def dist_point_segment(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    if vx == 0 and vy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / (vx * vx + vy * vy)))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


class Board:
    def __init__(self, width=4000, height=3000):
        self.width = width
        self.height = height
        self.elements: dict[str, dict] = {}
        self._ids = itertools.count(1)
        self.log: list[dict] = []
        self.step = 0
        self.turn = 0
        self._txn = None
        self._undo: dict[str, list[dict]] = {}

    # ------------------------------------------------------------------ ids
    def _new_id(self):
        while True:
            eid = f"e{next(self._ids)}"
            if eid not in self.elements:
                return eid

    # --------------------------------------------------------- transactions
    def begin(self, actor):
        if self._txn is not None:
            raise RuntimeError("transaction already open")
        self.step += 1
        self._txn = {"actor": actor, "step": self.step, "before": {}}

    def _touch(self, eid):
        if self._txn is not None and eid not in self._txn["before"]:
            cur = self.elements.get(eid)
            self._txn["before"][eid] = copy.deepcopy(cur) if cur else None

    def commit(self):
        txn, self._txn = self._txn, None
        if txn and txn["before"]:
            self._undo.setdefault(txn["actor"], []).append(txn)

    def rollback(self):
        txn, self._txn = self._txn, None
        if txn:
            self._restore(txn["before"])

    def _restore(self, before):
        for eid, prev in before.items():
            if prev is None:
                self.elements.pop(eid, None)
            else:
                self.elements[eid] = copy.deepcopy(prev)

    def undo(self, actor):
        """Revert the actor's most recent transaction.

        Elements that someone else modified after that transaction are left
        alone and reported as conflicts instead of being clobbered.
        """
        stack = self._undo.get(actor) or []
        if not stack:
            raise BoardError("nothing to undo")
        txn = stack.pop()
        restorable, conflicts = {}, []
        for eid, prev in txn["before"].items():
            cur = self.elements.get(eid)
            if cur and cur.get("modified_by") != actor and cur.get("modified_step", 0) > txn["step"]:
                conflicts.append(eid)
                continue
            restorable[eid] = prev
        for eid in restorable:
            self._touch(eid)
        self._restore(restorable)
        self._record(actor, "undo", None, {"reverted": sorted(restorable), "conflicts": conflicts})
        return sorted(restorable), conflicts

    # ---------------------------------------------------------------- log
    def _record(self, actor, op, eid, extra=None):
        entry = {"step": self.step, "turn": self.turn, "actor": actor, "op": op, "id": eid}
        if extra:
            entry.update(extra)
        self.log.append(entry)

    def _stamp(self, el, actor):
        el["modified_by"] = actor
        el["modified_step"] = self.step
        el["updated_turn"] = self.turn

    # ------------------------------------------------------------ creation
    def create(self, actor, etype, **fields):
        if etype not in ELEMENT_TYPES:
            raise BoardError(f"unknown element type '{etype}'")
        eid = fields.pop("id", None) or self._new_id()
        if eid in self.elements:
            raise BoardError(f"id '{eid}' already exists")
        el = {"id": eid, "type": etype, "author": actor, "created_turn": self.turn,
              "color": fields.pop("color", None) or DEFAULT_COLOR[etype],
              "layer": int(fields.pop("layer", 0) or 0),
              "tags": list(fields.pop("tags", []) or []),
              "votes": int(fields.pop("votes", 0) or 0),
              "comments": list(fields.pop("comments", []) or []),
              "group": fields.pop("group", None)}
        if el["color"] not in COLORS:
            raise BoardError(f"unknown color '{el['color']}'. Use one of {list(COLORS)}")
        if etype in BOX_TYPES:
            dw, dh = DEFAULT_SIZE[etype]
            el["x"] = _num(fields.pop("x", 0), "x")
            el["y"] = _num(fields.pop("y", 0), "y")
            el["w"] = _num(fields.pop("w", None) or dw, "w")
            el["h"] = _num(fields.pop("h", None) or dh, "h")
            if el["w"] <= 0 or el["h"] <= 0:
                raise BoardError("width and height must be positive")
            el["text"] = str(fields.pop("text", "") or "")
            if etype == "shape":
                kind = fields.pop("kind", None) or "rect"
                if kind not in SHAPE_KINDS:
                    raise BoardError(f"unknown shape kind '{kind}'. Use one of {list(SHAPE_KINDS)}")
                el["kind"] = kind
            if etype == "text":
                el["font_size"] = _num(fields.pop("font_size", None) or 24, "font_size")
        elif etype == "connector":
            src, dst = fields.pop("source", None), fields.pop("target", None)
            for ref in (src, dst):
                if ref not in self.elements or self.elements[ref]["type"] in ("connector",):
                    raise BoardError(f"connector endpoint '{ref}' is not a connectable element")
            if src == dst:
                raise BoardError("connector source and target must differ")
            el.update(source=src, target=dst, label=str(fields.pop("label", "") or ""),
                      directed=bool(fields.pop("directed", True)), text="")
        elif etype == "stroke":
            pts = fields.pop("points", None)
            el["points"] = self._check_points(pts)
            el["text"] = ""
        if fields:
            raise BoardError(f"unexpected fields for {etype}: {sorted(fields)}")
        self._touch(eid)
        self.elements[eid] = el
        self._stamp(el, actor)
        self._record(actor, "create", eid, {"type": etype})
        return eid

    @staticmethod
    def _check_points(pts):
        if not isinstance(pts, list) or len(pts) < 2:
            raise BoardError("stroke needs at least two [x, y] points")
        out = []
        for p in pts:
            if not isinstance(p, (list, tuple)) or len(p) != 2:
                raise BoardError("each point must be [x, y]")
            out.append([_num(p[0], "x"), _num(p[1], "y")])
        return out

    # ------------------------------------------------------------ mutation
    def get(self, eid):
        el = self.elements.get(eid)
        if el is None:
            raise BoardError(f"no element with id '{eid}'")
        return el

    def update(self, actor, eid, **fields):
        el = self.get(eid)
        allowed = UPDATABLE[el["type"]]
        bad = set(fields) - allowed
        if bad:
            raise BoardError(f"cannot set {sorted(bad)} on a {el['type']}")
        if "color" in fields and fields["color"] not in COLORS:
            raise BoardError(f"unknown color '{fields['color']}'")
        if "kind" in fields and fields["kind"] not in SHAPE_KINDS:
            raise BoardError(f"unknown shape kind '{fields['kind']}'")
        for k in ("source", "target"):
            if k in fields and fields[k] not in self.elements:
                raise BoardError(f"no element with id '{fields[k]}'")
        self._touch(eid)
        for k, v in fields.items():
            if k in ("w", "h", "font_size"):
                v = _num(v, k)
                if v <= 0:
                    raise BoardError(f"'{k}' must be positive")
            elif k == "layer":
                v = int(v)
            elif k == "points":
                v = self._check_points(v)
            elif k in ("text", "label"):
                v = str(v)
            elif k == "tags":
                v = list(v)
            elif k == "directed":
                v = bool(v)
            el[k] = v
        self._stamp(el, actor)
        self._record(actor, "update", eid, {"fields": sorted(fields)})

    def descendants(self, frame_id):
        """Elements whose nearest enclosing frames chain includes frame_id."""
        out = []
        for el in self.elements.values():
            if el["id"] == frame_id or el["type"] == "connector":
                continue
            if frame_id in [f["id"] for f in self.frames_containing(el)]:
                out.append(el["id"])
        return out

    def translate(self, actor, ids, dx, dy, carry=True):
        dx, dy = _num(dx, "dx"), _num(dy, "dy")
        moved = []
        todo = list(ids)
        for eid in list(todo):
            el = self.get(eid)
            if el["type"] == "frame" and carry:
                todo.extend(d for d in self.descendants(eid) if d not in todo)
        for eid in todo:
            el = self.get(eid)
            if el["type"] == "connector" or eid in moved:
                continue
            self._touch(eid)
            if el["type"] == "stroke":
                el["points"] = [[p[0] + dx, p[1] + dy] for p in el["points"]]
            else:
                el["x"] += dx
                el["y"] += dy
            self._stamp(el, actor)
            moved.append(eid)
        self._record(actor, "move", None, {"ids": moved, "dx": dx, "dy": dy})
        return moved

    def move_to(self, actor, eid, x, y, carry=True):
        el = self.get(eid)
        x0, y0, _, _ = self.bbox(el)
        return self.translate(actor, [eid], _num(x, "x") - x0, _num(y, "y") - y0, carry)

    def delete(self, actor, ids):
        gone = []
        for eid in ids:
            self.get(eid)
        victims = set(ids)
        for el in self.elements.values():
            if el["type"] == "connector" and (el["source"] in victims or el["target"] in victims):
                victims.add(el["id"])
        for eid in victims:
            self._touch(eid)
            self.elements.pop(eid)
            gone.append(eid)
        self._record(actor, "delete", None, {"ids": sorted(gone)})
        return sorted(gone)

    def set_group(self, actor, ids, group):
        for eid in ids:
            el = self.get(eid)
            self._touch(eid)
            el["group"] = group
            self._stamp(el, actor)
        self._record(actor, "group", None, {"ids": list(ids), "group": group})

    def add_comment(self, actor, eid, text):
        el = self.get(eid)
        self._touch(eid)
        el["comments"].append({"author": actor, "text": str(text), "turn": self.turn})
        self._stamp(el, actor)
        self._record(actor, "comment", eid)

    def add_votes(self, actor, eid, count):
        el = self.get(eid)
        self._touch(eid)
        el["votes"] = el.get("votes", 0) + int(count)
        self._stamp(el, actor)
        self._record(actor, "vote", eid, {"count": int(count)})

    # ------------------------------------------------------------ geometry
    def bbox(self, el):
        t = el["type"]
        if t in BOX_TYPES:
            return rect_of(el)
        if t == "stroke":
            xs = [p[0] for p in el["points"]]
            ys = [p[1] for p in el["points"]]
            return (min(xs), min(ys), max(xs), max(ys))
        a = self.center(self.elements[el["source"]])
        b = self.center(self.elements[el["target"]])
        return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))

    def center(self, el):
        x0, y0, x1, y1 = self.bbox(el)
        return ((x0 + x1) / 2, (y0 + y1) / 2)

    def frames_containing(self, el):
        """Frames whose rectangle contains the element's center, smallest first."""
        if el["type"] == "connector":
            return []
        cx, cy = self.center(el)
        out = []
        for f in self.elements.values():
            if f["type"] != "frame" or f["id"] == el["id"]:
                continue
            if el["type"] == "frame" and f["w"] * f["h"] <= el["w"] * el["h"]:
                continue
            if point_in_rect(cx, cy, rect_of(f)):
                out.append(f)
        out.sort(key=lambda f: f["w"] * f["h"])
        return out

    def frame_of(self, el):
        fs = self.frames_containing(el)
        return fs[0] if fs else None

    def connectors_of(self, eid):
        return [c for c in self.elements.values()
                if c["type"] == "connector" and (c["source"] == eid or c["target"] == eid)]

    def elements_at(self, x, y, radius=0.0):
        hits = []
        for el in self.elements.values():
            if el["type"] == "connector":
                a = self.center(self.elements[el["source"]])
                b = self.center(self.elements[el["target"]])
                d = dist_point_segment(x, y, a[0], a[1], b[0], b[1])
            else:
                d = dist_point_rect(x, y, self.bbox(el))
            if d <= max(radius, 0.0) + 1e-9:
                hits.append((d, el))
        order = {"text": 0, "sticky": 1, "shape": 2, "stroke": 3, "connector": 4, "frame": 5}
        hits.sort(key=lambda h: (h[0], order[h[1]["type"]], -h[1]["layer"]))
        return [h[1] for h in hits]

    # --------------------------------------------------------- description
    def describe(self, el):
        d = {"id": el["id"], "type": el["type"]}
        if el["type"] == "connector":
            d.update(source=el["source"], target=el["target"], directed=el["directed"])
            if el["label"]:
                d["label"] = el["label"]
        elif el["type"] == "stroke":
            pts = el["points"]
            if len(pts) > 24:
                step = len(pts) / 24
                pts = [pts[int(i * step)] for i in range(24)] + [pts[-1]]
            d["points"] = [[round(p[0]), round(p[1])] for p in pts]
        else:
            d.update(text=el["text"], x=round(el["x"]), y=round(el["y"]),
                     w=round(el["w"]), h=round(el["h"]))
            if el["type"] == "shape":
                d["kind"] = el["kind"]
            f = self.frame_of(el)
            if f is not None:
                d["frame"] = f["id"]
        d["color"] = el["color"]
        d["author"] = el["author"]
        for k in ("layer", "votes"):
            if el.get(k):
                d[k] = el[k]
        if el.get("group"):
            d["group"] = el["group"]
        if el.get("tags"):
            d["tags"] = el["tags"]
        if el.get("comments"):
            d["comments"] = [{"author": c["author"], "text": c["text"]} for c in el["comments"]]
        return d

    def snapshot(self):
        return copy.deepcopy(self.elements)

    @classmethod
    def from_snapshot(cls, elements, width=4000, height=3000):
        b = cls(width, height)
        b.elements = copy.deepcopy(elements)
        return b
