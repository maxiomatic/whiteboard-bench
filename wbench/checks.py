"""Deterministic check library.

Each check takes (board, spec, ctx) and returns (score in [0, 1] or None, detail).
None means "not applicable / not evaluated" (e.g. a rubric check with no judge)
and is excluded from the weighted average.

Checks refer to elements by *content* (fuzzy text) or by *selectors*, never by
agent-assigned ids, so any agent that produces an equivalent board passes.
"""
from __future__ import annotations

import itertools
import math

from . import textmatch as tm
from .board import Board, rect_of, overlap_area, point_in_rect, dist_point_rect

CONTENT_TYPES = ("sticky", "shape", "text")
TYPE_PRIORITY = {"shape": 0, "sticky": 1, "text": 2, "frame": 3}


# ----------------------------------------------------------------- selectors
def _author_ok(author, want):
    if want in (None, "any"):
        return True
    if want == "agent":
        return author == "agent"
    if want == "human":
        return author.startswith("human")
    return author == want


def select(board, sel=None):
    """Filter elements by a selector dict.

    Keys: type (str|list), text (fuzzy), author, color, kind, layer, frame
    (fuzzy title, "*" = any frame, "none" = outside frames), created_turn, tag.
    Default type is sticky/shape/text.
    """
    sel = sel or {}
    types = sel.get("type", CONTENT_TYPES)
    if isinstance(types, str):
        types = (types,)
    out = []
    for el in board.elements.values():
        if el["type"] not in types:
            continue
        if "text" in sel and not tm.matches(sel["text"], _text(el), sel.get("threshold", 0.75)):
            continue
        if not _author_ok(el["author"], sel.get("author")):
            continue
        if "color" in sel and el["color"] not in _as_list(sel["color"]):
            continue
        if "kind" in sel and el.get("kind") not in _as_list(sel["kind"]):
            continue
        if "layer" in sel and el.get("layer", 0) != sel["layer"]:
            continue
        if "created_turn" in sel and el.get("created_turn") != sel["created_turn"]:
            continue
        if "tag" in sel and sel["tag"] not in el.get("tags", []):
            continue
        if "frame" in sel and not _in_frame(board, el, sel["frame"]):
            continue
        out.append(el)
    return out


def _as_list(v):
    return v if isinstance(v, (list, tuple)) else [v]


def _text(el):
    return el.get("text") or el.get("label") or ""


def _in_frame(board, el, title):
    frames = board.frames_containing(el)
    if title == "*":
        return bool(frames)
    if title in (None, "none"):
        return not frames
    return any(tm.matches(title, f["text"]) for f in frames)


def find_one(board, text, sel=None, threshold=0.75, exclude=()):
    """Best element for `text`, preferring connected shapes over loose labels."""
    sel = dict(sel or {})
    sel.setdefault("type", ("sticky", "shape", "text", "frame"))
    cands = []
    for el in select(board, sel):
        if el["id"] in exclude:
            continue
        s = tm.score(text, _text(el))
        if s >= threshold:
            connected = 1 if board.connectors_of(el["id"]) else 0
            cands.append((s, connected, -TYPE_PRIORITY.get(el["type"], 9), el))
    if not cands:
        return None
    cands.sort(key=lambda c: (c[0], c[1], c[2]), reverse=True)
    return cands[0][3]


def _resolve(board, item, sel=None):
    """Item may be a text string or {"text":..} or {"selector":..}. Returns list."""
    if isinstance(item, str):
        el = find_one(board, item, sel)
        return [el] if el else []
    if "selector" in item:
        return select(board, item["selector"])
    el = find_one(board, item["text"], item.get("where", sel))
    return [el] if el else []


def _label(item):
    return item if isinstance(item, str) else item.get("text") or str(item.get("selector"))


def _frac(hits, total, missing):
    if total == 0:
        return None, "nothing to check"
    detail = f"{hits:g}/{total}"
    if missing:
        detail += " | missing/failed: " + "; ".join(str(m) for m in missing[:8])
    return hits / total, detail


# --------------------------------------------------------------- text checks
def c_texts_present(board, spec, ctx):
    pool = select(board, spec.get("where"))
    thr = spec.get("threshold", 0.75)
    missing = [i for i in spec["items"] if not any(tm.matches(i, _text(e), thr) for e in pool)]
    return _frac(len(spec["items"]) - len(missing), len(spec["items"]), missing)


def c_texts_absent(board, spec, ctx):
    pool = select(board, spec.get("where"))
    thr = spec.get("threshold", 0.75)
    found = [i for i in spec["items"] if any(tm.matches(i, _text(e), thr) for e in pool)]
    s, _ = _frac(len(spec["items"]) - len(found), len(spec["items"]), [])
    return s, ("present but should not be: " + "; ".join(found)) if found else "none present"


def c_count(board, spec, ctx):
    n = len(select(board, spec.get("selector")))
    lo, hi = spec.get("min", 0), spec.get("max", math.inf)
    if lo <= n <= hi:
        return 1.0, f"count={n}"
    if spec.get("strict"):
        return 0.0, f"count={n}, expected [{lo}, {hi}]"
    s = n / lo if n < lo else hi / n if n else 0.0
    return s, f"count={n}, expected [{lo}, {hi}]"


def c_max_words(board, spec, ctx):
    els = select(board, spec.get("selector"))
    bad = [e["text"] for e in els if len(e["text"].split()) > spec["max"]]
    return _frac(len(els) - len(bad), len(els), bad)


def c_distinct(board, spec, ctx):
    els = select(board, spec.get("selector"))
    kept = []
    for e in els:
        if all(tm.jaccard(e["text"], k) < spec.get("max_jaccard", 0.5) for k in kept):
            kept.append(e["text"])
    return min(1.0, len(kept) / spec["min"]), f"{len(kept)} distinct of {len(els)} (need {spec['min']})"


def c_said(board, spec, ctx):
    msgs = [m["text"] for m in ctx.messages if spec.get("scope") == "all" or m["turn"] == ctx.turn]
    blob = " \n ".join(msgs)
    thr = spec.get("threshold", 0.75)
    if spec.get("any"):
        ok = any(tm.matches(i, blob, thr) for i in spec["items"])
        return (1.0 if ok else 0.0), ("matched" if ok else "none of the expected phrases were said")
    missing = [i for i in spec["items"] if not tm.matches(i, blob, thr)]
    return _frac(len(spec["items"]) - len(missing), len(spec["items"]), missing)


# ------------------------------------------------------------- structure
def c_frames(board, spec, ctx):
    frames = [e for e in board.elements.values() if e["type"] == "frame"]
    missing = [t for t in spec["titles"] if not any(tm.matches(t, f["text"]) for f in frames)]
    return _frac(len(spec["titles"]) - len(missing), len(spec["titles"]), missing)


def c_in_frame(board, spec, ctx):
    hits, total, failed = 0, 0, []
    for item in spec.get("items", []):
        total += 1
        els = _resolve(board, item)
        if els and _in_frame(board, els[0], item["frame"]):
            hits += 1
        else:
            failed.append(f"{item['text']} -> {item['frame']}" + ("" if els else " (not found)"))
    if "selector" in spec:
        for el in select(board, spec["selector"]):
            total += 1
            if _in_frame(board, el, spec["frame"]):
                hits += 1
            else:
                failed.append(f"'{el['text'][:30]}' not in {spec['frame']}")
    return _frac(hits, total, failed)


def _pair_f1(gold_labels, pred_labels):
    tp = fp = fn = 0
    for i, j in itertools.combinations(range(len(gold_labels)), 2):
        g = gold_labels[i] == gold_labels[j]
        p = pred_labels[i] == pred_labels[j]
        tp += g and p
        fp += (not g) and p
        fn += g and not p
    if tp == 0:
        return 0.0
    prec, rec = tp / (tp + fp), tp / (tp + fn)
    return 2 * prec * rec / (prec + rec)


def _spatial_components(board, els, gap):
    parent = {e["id"]: e["id"] for e in els}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in itertools.combinations(els, 2):
        ra, rb = board.bbox(a), board.bbox(b)
        dx = max(rb[0] - ra[2], ra[0] - rb[2], 0)
        dy = max(rb[1] - ra[3], ra[1] - rb[3], 0)
        if max(dx, dy) <= gap:
            parent[find(a["id"])] = find(b["id"])
    return {e["id"]: find(e["id"]) for e in els}


def c_clusters(board, spec, ctx):
    """Pairwise F1 between the gold grouping and the board's grouping.

    method: "frame" (innermost frame), "group" (group id), or "spatial"
    (single-linkage over elements in `pool`, joined when closer than `gap`).
    """
    method = spec.get("method", "frame")
    gold, items = [], []
    for gi, grp in enumerate(spec["groups"]):
        for t in grp:
            gold.append(gi)
            items.append(t)
    comp = None
    if method == "spatial":
        pool = select(board, spec.get("pool"))
        comp = _spatial_components(board, pool, spec.get("gap", 60))
    pred, missing = [], []
    for k, t in enumerate(items):
        el = find_one(board, t, spec.get("where"))
        if el is None:
            pred.append(f"missing{k}")
            missing.append(t)
            continue
        if method == "frame":
            f = board.frame_of(el)
            pred.append(f["id"] if f else f"none{k}")
        elif method == "group":
            pred.append(el.get("group") or f"none{k}")
        else:
            pred.append(comp.get(el["id"], f"none{k}"))
    f1 = _pair_f1(gold, pred)
    found = 1 - len(missing) / len(items)
    detail = f"pair-F1={f1:.2f}, found={found:.2f}"
    if missing:
        detail += " | missing: " + "; ".join(missing[:6])
    return f1 * found, detail


def c_graph(board, spec, ctx):
    """Match expected nodes/edges against connectors on the board.

    score = 0.25 * node recall + 0.75 * edge F1. Reversed edges earn half
    credit; undirected connectors for directed edges earn 0.75; a missing or
    wrong expected label multiplies that edge's credit by 0.75.
    """
    directed = spec.get("directed", True)
    nodes = spec["nodes"]
    where = spec.get("where", {"type": ("shape", "sticky", "text", "frame")})
    # greedy unique assignment by score
    pairs = []
    for n in nodes:
        for el in select(board, where):
            s = tm.score(n, _text(el))
            if s >= 0.75:
                pairs.append((s, 1 if board.connectors_of(el["id"]) else 0,
                              -TYPE_PRIORITY.get(el["type"], 9), n, el["id"]))
    pairs.sort(reverse=True, key=lambda p: p[:3])
    node_el, used = {}, set()
    for s, _, _, n, eid in pairs:
        if n not in node_el and eid not in used:
            node_el[n] = eid
            used.add(eid)
    node_recall = len(node_el) / len(nodes)
    conns = [c for c in board.elements.values() if c["type"] == "connector"]
    matched_conns, credit, failed = set(), 0.0, []
    for e in spec["edges"]:
        a, b = node_el.get(e[0]), node_el.get(e[1])
        label = e[2] if len(e) > 2 else None
        best, best_c = 0.0, None
        if a and b:
            for c in conns:
                if {c["source"], c["target"]} != {a, b}:
                    continue
                if not directed:
                    s = 1.0
                elif not c["directed"]:
                    s = 0.75
                elif c["source"] == a:
                    s = 1.0
                else:
                    s = 0.5
                if label and not tm.matches(label, c.get("label", "")):
                    s *= 0.75
                if s > best:
                    best, best_c = s, c["id"]
        if best_c:
            matched_conns.add(best_c)
        if best < 1.0:
            failed.append(f"{e[0]}->{e[1]}" + (f" [{label}]" if label else "") + f" ({best:.2f})")
        credit += best
    extra = [c for c in conns if c["id"] not in matched_conns
             and c["source"] in used and c["target"] in used]
    recall = credit / len(spec["edges"])
    precision = credit / (credit + len(extra)) if credit + len(extra) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    score = 0.25 * node_recall + 0.75 * f1
    missing_nodes = [n for n in nodes if n not in node_el]
    detail = f"nodes {len(node_el)}/{len(nodes)}, edge recall {recall:.2f}, precision {precision:.2f}"
    if missing_nodes:
        detail += " | missing nodes: " + "; ".join(missing_nodes)
    if failed:
        detail += " | weak edges: " + "; ".join(failed[:6])
    if extra:
        detail += f" | {len(extra)} unexpected connector(s)"
    return score, detail


def c_node_kinds(board, spec, ctx):
    hits, failed = 0, []
    for item in spec["items"]:
        el = find_one(board, item["text"])
        want = _as_list(item["kind"])
        ok = el is not None and ((el["type"] == "shape" and el["kind"] in want) or el["type"] in want)
        hits += ok
        if not ok:
            got = None if el is None else (el.get("kind") or el["type"])
            failed.append(f"{item['text']}: got {got}, want {want}")
    return _frac(hits, len(spec["items"]), failed)


def c_property(board, spec, ctx):
    hits, total, failed = 0, 0, []
    for item in spec["items"]:
        els = _resolve(board, item)
        if not els:
            total += 1
            failed.append(f"{_label(item)} (not found)")
            continue
        for el in els:
            total += 1
            val = el.get(item["field"])
            op = item.get("op", "eq")
            want = item["value"]
            ok = (val == want if op == "eq" else val != want if op == "ne"
                  else val in want if op == "in" else False)
            hits += ok
            if not ok:
                failed.append(f"{_text(el)[:30]}.{item['field']}={val}")
    return _frac(hits, total, failed)


# --------------------------------------------------------------- spatial
def c_no_overlap(board, spec, ctx):
    els = select(board, spec.get("selector"))
    frac = spec.get("min_fraction", 0.1)
    bad, pairs = set(), []
    for a, b in itertools.combinations(els, 2):
        if a.get("layer", 0) != b.get("layer", 0):
            continue
        ra, rb = rect_of(a), rect_of(b)
        area = overlap_area(ra, rb)
        if area > frac * min(a["w"] * a["h"], b["w"] * b["h"]):
            bad.update((a["id"], b["id"]))
            pairs.append(f"'{a['text'][:18]}' x '{b['text'][:18]}'")
    if not els:
        return None, "no elements"
    return 1 - len(bad) / len(els), f"{len(bad)} of {len(els)} elements overlap" + (
        (": " + "; ".join(pairs[:5])) if pairs else "")


def c_order(board, spec, ctx):
    axis = 0 if spec.get("axis", "y") == "x" else 1
    pos = []
    for t in spec["items"]:
        el = find_one(board, t, spec.get("where"))
        pos.append(board.center(el)[axis] if el else None)
    good = total = 0
    for i, j in itertools.combinations(range(len(pos)), 2):
        total += 1
        if pos[i] is not None and pos[j] is not None and pos[i] < pos[j]:
            good += 1
    missing = [t for t, p in zip(spec["items"], pos) if p is None]
    return _frac(good, total, missing)


def _rel_ok(board, a, rel, b, dist):
    ca, cb = board.center(a), board.center(b)
    if rel == "left_of":
        return ca[0] < cb[0] - 10
    if rel == "right_of":
        return ca[0] > cb[0] + 10
    if rel == "above":
        return ca[1] < cb[1] - 10
    if rel == "below":
        return ca[1] > cb[1] + 10
    if rel == "near":
        return math.dist(ca, cb) <= dist
    if rel == "inside":
        return point_in_rect(ca[0], ca[1], board.bbox(b))
    raise ValueError(rel)


def c_relation(board, spec, ctx):
    hits, failed = 0, []
    for it in spec["items"]:
        a, b = find_one(board, it["a"]), find_one(board, it["b"])
        ok = a is not None and b is not None and _rel_ok(board, a, it["rel"], b, it.get("dist", 300))
        hits += ok
        if not ok:
            failed.append(f"{it['a']} {it['rel']} {it['b']}")
    return _frac(hits, len(spec["items"]), failed)


def c_aligned(board, spec, ctx):
    axis = 1 if spec.get("axis", "y") == "y" else 0
    els = select(board, spec["selector"]) if "selector" in spec else [
        e for e in (find_one(board, t) for t in spec["items"]) if e]
    if len(els) < 2:
        return (0.0 if spec.get("items") else None), "fewer than two elements found"
    vals = [board.center(e)[axis] for e in els]
    spread = max(vals) - min(vals)
    tol = spec.get("tol", 20)
    s = 1.0 if spread <= tol else max(0.0, 1 - (spread - tol) / (4 * tol))
    return s, f"spread {spread:.0f}px (tol {tol})"


def c_grid_aligned(board, spec, ctx):
    els = select(board, spec.get("selector"))
    tol = spec.get("tol", 12)
    if len(els) < 2:
        return None, "fewer than two elements"
    ok = 0
    for e in els:
        others = [o for o in els if o is not e]
        col = any(abs(o["x"] - e["x"]) <= tol for o in others)
        row = any(abs(o["y"] - e["y"]) <= tol for o in others)
        ok += col and row
    return ok / len(els), f"{ok}/{len(els)} elements share a row and a column with another"


def c_in_region(board, spec, ctx):
    hits, total, failed = 0, 0, []
    for item in spec["items"]:
        region = item.get("region") or ctx.participants[item["participant"]]["reach"]
        r = (region["x"], region["y"], region["x"] + region["w"], region["y"] + region["h"])
        els = _resolve(board, item)
        if not els:
            total += 1
            failed.append(f"{_label(item)} (not found)")
        for el in els:
            total += 1
            c = board.center(el)
            if point_in_rect(c[0], c[1], r):
                hits += 1
            else:
                failed.append(f"{_text(el)[:30]} at ({c[0]:.0f},{c[1]:.0f})")
    return _frac(hits, total, failed)


def c_near_point(board, spec, ctx):
    hits, failed = 0, []
    for item in spec["items"]:
        el = find_one(board, item["text"])
        ok = el is not None and dist_point_rect(item["point"][0], item["point"][1],
                                                board.bbox(el)) <= item.get("radius", 100)
        hits += ok
        if not ok:
            failed.append(item["text"])
    return _frac(hits, len(spec["items"]), failed)


def c_quadrants(board, spec, ctx):
    """items: [{text, v: hi|lo, h: hi|lo}]. hi-v above lo-v, lo-h left of hi-h."""
    pos = {}
    for it in spec["items"]:
        el = find_one(board, it["text"])
        pos[it["text"]] = board.center(el) if el else None
    good = total = 0
    for a, b in itertools.combinations(spec["items"], 2):
        pa, pb = pos[a["text"]], pos[b["text"]]
        if a["v"] != b["v"]:
            total += 1
            hi, lo = (pa, pb) if a["v"] == "hi" else (pb, pa)
            good += bool(hi and lo and hi[1] < lo[1])
        if a["h"] != b["h"]:
            total += 1
            lo_, hi_ = (pa, pb) if a["h"] == "lo" else (pb, pa)
            good += bool(hi_ and lo_ and lo_[0] < hi_[0])
    missing = [t for t, p in pos.items() if p is None]
    return _frac(good, total, missing)


def c_nearest_label(board, spec, ctx):
    labels = {}
    for lab in spec["labels"]:
        labels[lab] = find_one(board, lab, {"type": ("text", "frame", "shape", "sticky")})
    hits, failed = 0, []
    for it in spec["items"]:
        el = find_one(board, it["text"], exclude=[l["id"] for l in labels.values() if l])
        if el is None:
            failed.append(f"{it['text']} (not found)")
            continue
        c = board.center(el)
        best, best_d = None, math.inf
        for lab, lel in labels.items():
            if lel is None:
                continue
            if lel["type"] == "frame":
                d = dist_point_rect(c[0], c[1], board.bbox(lel))
            else:
                d = math.dist(c, board.center(lel))
            if d < best_d:
                best, best_d = lab, d
        ok = best == it["label"]
        hits += ok
        if not ok:
            failed.append(f"{it['text']}: nearest '{best}', want '{it['label']}'")
    return _frac(hits, len(spec["items"]), failed)


# -------------------------------------------------------------- relations
def c_each_connected(board, spec, ctx):
    srcs = select(board, spec["from"])
    targets = {e["id"]: e for e in select(board, spec["to"])}
    need = spec.get("min", 1)
    near = spec.get("near")
    if not srcs:
        return 0.0, "no source elements"
    total, failed = 0.0, []
    for s in srcs:
        n = 0
        for c in board.connectors_of(s["id"]):
            other = c["target"] if c["source"] == s["id"] else c["source"]
            if other in targets:
                if near is None or math.dist(board.center(s), board.center(targets[other])) <= near:
                    n += 1
        total += min(1.0, n / need)
        if n < need:
            failed.append(f"'{s['text'][:25]}' has {n}")
    return _frac(total, len(srcs), failed)


# ---------------------------------------------------------------- history
def c_preserve_human(board, spec, ctx):
    """Human-authored elements from a snapshot still exist (same id) with the
    same text and, optionally, the same position."""
    snap = Board.from_snapshot(ctx.snapshots[spec.get("snapshot", "initial")])
    sel = dict(spec.get("selector") or {})
    sel.setdefault("author", "human")
    sel.setdefault("type", ("sticky", "shape", "text", "frame", "stroke"))
    base = select(snap, sel)
    allow = set()
    for t in spec.get("allow_changed", []):
        allow |= {e["id"] for e in base if tm.matches(t, _text(e))}
    hits, failed = 0, []
    for e in base:
        cur = board.elements.get(e["id"])
        ok = cur is not None
        if ok and spec.get("text", True) and e["id"] not in allow:
            ok = cur.get("text") == e.get("text")
        if ok and spec.get("positions"):
            ok = math.dist(board.center(cur), snap.center(e)) <= spec.get("tol", 5)
        hits += ok
        if not ok:
            failed.append(f"'{_text(e)[:25]}'" + (" deleted" if cur is None else " changed"))
    return _frac(hits, len(base), failed)


def c_matches_snapshot(board, spec, ctx):
    snap = Board.from_snapshot(ctx.snapshots[spec["snapshot"]])
    base = select(snap, spec.get("selector"))
    tol = spec.get("tol", 5)
    hits, failed = 0, []
    for e in base:
        cur = board.elements.get(e["id"])
        ok = cur is not None and math.dist(board.center(cur), snap.center(e)) <= tol
        hits += ok
        if not ok:
            failed.append(_text(e)[:25])
    return _frac(hits, len(base), failed)


# ------------------------------------------------------------------ judge
def c_rubric(board, spec, ctx):
    if ctx.judge is None:
        return None, "skipped (no judge configured)"
    return ctx.judge(board, spec, ctx)


CHECKS = {name[2:]: fn for name, fn in globals().items() if name.startswith("c_")}
