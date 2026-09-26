"""Lightweight fuzzy text matching used by both tools and graders.

Deliberately simple and deterministic: normalized substring match, then
stemmed token recall with prefix tolerance. Expected strings may contain
alternatives separated by "|" (or be given as a list).
"""
from __future__ import annotations

import re

STOP = set("a an the of to in on for and or is are be with by at as it its this that from into "
           "our we i you so do does".split())


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def stem(t):
    if len(t) > 4:
        for suf in ("ing", "ed"):
            if t.endswith(suf):
                t = t[: -len(suf)]
                break
        else:
            if t.endswith("ies"):
                t = t[:-3] + "y"
            elif t.endswith("s") and not t.endswith("ss"):
                t = t[:-1]
    if len(t) > 3 and t.endswith("e"):
        t = t[:-1]
    return t


def tokens(s):
    return [stem(t) for t in norm(s).split() if t not in STOP]


def _tok_hit(t, pool):
    if t in pool:
        return True
    if len(t) >= 4:
        return any(len(p) >= 4 and (p.startswith(t) or t.startswith(p)) for p in pool)
    return False


def score(expected, actual):
    """Return 0..1: how well `actual` covers the `expected` phrase."""
    if isinstance(expected, (list, tuple)):
        return max((score(e, actual) for e in expected), default=0.0)
    if "|" in expected:
        return score(expected.split("|"), actual)
    ne, na = norm(expected), norm(actual)
    if not ne:
        return 0.0
    if re.search(r"(^| )" + re.escape(ne) + r"($| )", na):
        return 1.0
    et = tokens(expected)
    if not et:
        return 0.0
    pool = set(tokens(actual))
    return sum(1 for t in et if _tok_hit(t, pool)) / len(et)


def matches(expected, actual, threshold=0.75):
    return score(expected, actual) >= threshold


def jaccard(a, b):
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta and not tb:
        return 1.0
    return len(ta & tb) / len(ta | tb)
