"""Render a board to a standalone SVG string (for reports and human review)."""
from __future__ import annotations

import html
import math

FILL = {"yellow": "#fff3a0", "orange": "#ffd3a1", "pink": "#ffc6dc", "red": "#ff9c96",
        "purple": "#dcc8ff", "blue": "#b9dcff", "green": "#c4eec0", "gray": "#dddddd",
        "white": "#ffffff", "black": "#333333"}
INK = {"black": "#222", "white": "#fff", "gray": "#666", "red": "#c62828", "blue": "#1565c0",
       "green": "#2e7d32", "orange": "#e65100", "purple": "#6a1b9a", "pink": "#ad1457", "yellow": "#9a7d00"}
AUTHOR_TINT = {"agent": "#5b5bd6"}


def _wrap(text, width_px, font):
    max_chars = max(4, int(width_px / (font * 0.56)))
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            if len(line) + len(word) + 1 > max_chars and line:
                lines.append(line)
                line = word
            else:
                line = (line + " " + word).strip()
        lines.append(line)
    return lines


def _text_block(x, y, w, h, text, font, color="#222", anchor="middle", valign="middle"):
    lines = _wrap(text, w - 12, font)
    max_lines = max(1, int((h - 8) / (font * 1.2)))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"
    total = len(lines) * font * 1.2
    ty = y + (h - total) / 2 + font if valign == "middle" else y + font + 6
    tx = x + w / 2 if anchor == "middle" else x + 6
    out = [f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="{font}" fill="{color}" text-anchor="{anchor}" '
           f'font-family="Helvetica, Arial, sans-serif">']
    for k, ln in enumerate(lines):
        out.append(f'<tspan x="{tx:.1f}" dy="{0 if k == 0 else font * 1.2:.1f}">{html.escape(ln)}</tspan>')
    out.append("</text>")
    return "".join(out)


def _shape(el):
    x, y, w, h = el["x"], el["y"], el["w"], el["h"]
    fill = FILL.get(el["color"], "#fff")
    st = f'fill="{fill}" stroke="#444" stroke-width="2"'
    k = el["kind"]
    if k == "ellipse":
        return f'<ellipse cx="{x + w / 2}" cy="{y + h / 2}" rx="{w / 2}" ry="{h / 2}" {st}/>'
    if k == "diamond":
        return f'<polygon points="{x + w / 2},{y} {x + w},{y + h / 2} {x + w / 2},{y + h} {x},{y + h / 2}" {st}/>'
    if k == "triangle":
        return f'<polygon points="{x + w / 2},{y} {x + w},{y + h} {x},{y + h}" {st}/>'
    if k == "parallelogram":
        o = w * 0.15
        return f'<polygon points="{x + o},{y} {x + w},{y} {x + w - o},{y + h} {x},{y + h}" {st}/>'
    if k == "hexagon":
        o = w * 0.18
        return (f'<polygon points="{x + o},{y} {x + w - o},{y} {x + w},{y + h / 2} {x + w - o},{y + h} '
                f'{x + o},{y + h} {x},{y + h / 2}" {st}/>')
    if k == "cylinder":
        ry = min(14, h / 5)
        return (f'<path d="M{x},{y + ry} A{w / 2},{ry} 0 0 1 {x + w},{y + ry} V{y + h - ry} '
                f'A{w / 2},{ry} 0 0 1 {x},{y + h - ry} Z" {st}/>'
                f'<path d="M{x},{y + ry} A{w / 2},{ry} 0 0 0 {x + w},{y + ry}" fill="none" stroke="#444" stroke-width="2"/>')
    rx = 14 if k in ("rounded_rect", "cloud") else 2
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" {st}/>'


def _edge_point(board, el, toward):
    """Where a line from el's center toward `toward` exits el's box."""
    x0, y0, x1, y1 = board.bbox(el)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    if dx == 0 and dy == 0:
        return cx, cy
    sx = (x1 - x0) / 2 / abs(dx) if dx else math.inf
    sy = (y1 - y0) / 2 / abs(dy) if dy else math.inf
    s = min(sx, sy)
    return cx + dx * s, cy + dy * s


def render_svg(board, participants=None, margin=60):
    els = list(board.elements.values())
    boxes = [board.bbox(e) for e in els]
    for p in (participants or {}).values():
        r = p.get("reach")
        if r:
            boxes.append((r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]))
    if not boxes:
        boxes = [(0, 0, 800, 600)]
    x0 = min(b[0] for b in boxes) - margin
    y0 = min(b[1] for b in boxes) - margin
    x1 = max(b[2] for b in boxes) + margin
    y1 = max(b[3] for b in boxes) + margin
    w, h = x1 - x0, y1 - y0
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.0f} {y0:.0f} {w:.0f} {h:.0f}" '
           f'width="{min(1200, w):.0f}" style="background:#fafaf7">',
           '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
           'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#333"/></marker></defs>']
    for name, p in (participants or {}).items():
        r = p.get("reach")
        if r:
            col = FILL.get(p.get("color", "gray"), "#ddd")
            out.append(f'<rect x="{r["x"]}" y="{r["y"]}" width="{r["w"]}" height="{r["h"]}" fill="{col}" '
                       f'fill-opacity="0.18" stroke="{col}" stroke-dasharray="12 8" stroke-width="3"/>')
            out.append(f'<text x="{r["x"] + 10}" y="{r["y"] + h * 0.012 + 24}" font-size="26" fill="#777" '
                       f'font-family="Helvetica, Arial, sans-serif">{html.escape(p.get("name", name))}\'s reach</text>')
    order = {"frame": 0, "stroke": 1, "shape": 2, "sticky": 3, "text": 4, "connector": 5}
    for el in sorted(els, key=lambda e: (e.get("layer", 0), order[e["type"]])):
        t = el["type"]
        op = 1.0 if el.get("layer", 0) >= 0 else 0.45
        g = f'<g opacity="{op}">'
        if t == "frame":
            out.append(g + f'<rect x="{el["x"]}" y="{el["y"]}" width="{el["w"]}" height="{el["h"]}" '
                       f'fill="{FILL.get(el["color"], "#fff")}" fill-opacity="0.55" stroke="#999" stroke-width="2" rx="6"/>'
                       + _text_block(el["x"], el["y"], el["w"], 44, el["text"], 26, "#555", "start", "top") + "</g>")
        elif t == "sticky":
            shadow = ' stroke="#5b5bd6" stroke-width="3"' if el["author"] == "agent" else ""
            if el.get("layer", 0) > 0:
                shadow += ' filter="drop-shadow(8px 8px 6px rgba(0,0,0,.35))"'
            out.append(g + f'<rect x="{el["x"]}" y="{el["y"]}" width="{el["w"]}" height="{el["h"]}" '
                       f'fill="{FILL.get(el["color"], "#fff3a0")}"{shadow}/>'
                       + _text_block(el["x"], el["y"], el["w"], el["h"], el["text"], 18) + "</g>")
            if el.get("votes"):
                out.append(f'<circle cx="{el["x"] + el["w"] - 16}" cy="{el["y"] + 16}" r="14" fill="#d32f2f"/>'
                           f'<text x="{el["x"] + el["w"] - 16}" y="{el["y"] + 21}" font-size="15" fill="#fff" '
                           f'text-anchor="middle" font-family="Helvetica, Arial, sans-serif">{el["votes"]}</text>')
        elif t == "shape":
            out.append(g + _shape(el) + _text_block(el["x"], el["y"], el["w"], el["h"], el["text"], 18) + "</g>")
        elif t == "text":
            fs = el.get("font_size", 24)
            out.append(g + _text_block(el["x"], el["y"], el["w"], el["h"], el["text"], fs,
                                       INK.get(el["color"], "#222"), "start") + "</g>")
        elif t == "stroke":
            pts = " ".join(f"{p[0]:.0f},{p[1]:.0f}" for p in el["points"])
            out.append(f'<polyline points="{pts}" fill="none" stroke="{INK.get(el["color"], "#222")}" '
                       f'stroke-width="4" stroke-linecap="round" stroke-linejoin="round" opacity="{op}"/>')
        elif t == "connector":
            a, b = board.elements[el["source"]], board.elements[el["target"]]
            p1 = _edge_point(board, a, board.center(b))
            p2 = _edge_point(board, b, board.center(a))
            mk = ' marker-end="url(#arr)"' if el["directed"] else ""
            out.append(f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" x2="{p2[0]:.1f}" y2="{p2[1]:.1f}" '
                       f'stroke="{INK.get(el["color"], "#333")}" stroke-width="2.5"{mk}/>')
            if el.get("label"):
                mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
                out.append(f'<rect x="{mx - 4 - len(el["label"]) * 4.5:.1f}" y="{my - 13:.1f}" '
                           f'width="{len(el["label"]) * 9 + 8:.1f}" height="20" fill="#fafaf7"/>'
                           f'<text x="{mx:.1f}" y="{my + 3:.1f}" font-size="15" text-anchor="middle" fill="#333" '
                           f'font-family="Helvetica, Arial, sans-serif">{html.escape(el["label"])}</text>')
    out.append("</svg>")
    return "".join(out)
