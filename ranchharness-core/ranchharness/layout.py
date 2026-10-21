"""Shared drawing geometry so the editor and the SVG exporter agree."""
from __future__ import annotations

from .library import Library, Part
from .model import Connector

BOX_W = 210.0
HEADER_H = 46.0
ROW_H = 22.0
PIN_COL_W = 30.0
NODE_R = 9.0          # splice / ring node radius


def is_node(part: Part | None) -> bool:
    return bool(part and part.kind in ("splice", "ring"))


def pins(c: Connector, lib: Library) -> list[str]:
    part = lib.get(c.part_key)
    return part.pins(c.positions) if part else [str(i) for i in range(1, (c.positions or 1) + 1)]


def box_size(c: Connector, lib: Library) -> tuple[float, float]:
    part = lib.get(c.part_key)
    if is_node(part):
        return NODE_R * 2, NODE_R * 2
    return BOX_W, HEADER_H + ROW_H * len(pins(c, lib))


def port(c: Connector, pin: str, lib: Library) -> tuple[float, float]:
    """Scene coordinate where a wire attaches to (c, pin)."""
    part = lib.get(c.part_key)
    if is_node(part):
        return c.x + NODE_R, c.y + NODE_R
    pl = pins(c, lib)
    i = pl.index(pin) if pin in pl else 0
    y = c.y + HEADER_H + ROW_H * i + ROW_H / 2
    x = c.x if c.flipped else c.x + BOX_W
    return x, y


def exit_dir(c: Connector, lib: Library) -> float:
    """+1 if wires leave to the right, -1 to the left, 0 for nodes."""
    if is_node(lib.get(c.part_key)):
        return 0.0
    return -1.0 if c.flipped else 1.0


def wire_curve(p1, d1, p2, d2):
    """Cubic bezier control points between two ports."""
    (x1, y1), (x2, y2) = p1, p2
    reach = max(50.0, abs(x2 - x1) * 0.45)
    if d1 == 0:
        d1 = 1.0 if x2 >= x1 else -1.0
    if d2 == 0:
        d2 = 1.0 if x1 >= x2 else -1.0
    return (x1, y1), (x1 + d1 * reach, y1), (x2 + d2 * reach, y2), (x2, y2)


def bezier_point(pts, t: float):
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = pts
    u = 1 - t
    x = u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3
    y = u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3
    return x, y


# ---- collapsed bundles ----------------------------------------------------

def _mean(pts):
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def bundle_geometry(h, wires, lib: Library):
    """Trunk + breakouts for drawing a bundle as one object.

    Each wire's two ends are split into a "left" and "right" group (a 2-means split
    that keeps one end of every wire on each side). The trunk runs between two hubs
    placed 30% / 70% of the way between the group centres; every pin gets a thin
    breakout curve to its hub.
    Returns None if there's nothing to draw.
    """
    pairs = []
    for w in wires:
        a, b = h.connector(w.a_conn), h.connector(w.b_conn)
        if not a or not b:
            continue
        ea = (port(a, w.a_pin, lib), exit_dir(a, lib))
        eb = (port(b, w.b_pin, lib), exit_dir(b, lib))
        pairs.append((ea, eb) if ea[0][0] <= eb[0][0] else (eb, ea))
    if not pairs:
        return None
    for _ in range(6):
        cl = _mean([p[0][0] for p in pairs])
        cr = _mean([p[1][0] for p in pairs])
        new = []
        for e1, e2 in pairs:
            keep = _dist(e1[0], cl) + _dist(e2[0], cr)
            swap = _dist(e2[0], cl) + _dist(e1[0], cr)
            new.append((e1, e2) if keep <= swap else (e2, e1))
        if new == pairs:
            break
        pairs = new
    cl = _mean([p[0][0] for p in pairs])
    cr = _mean([p[1][0] for p in pairs])
    if _dist(cl, cr) < 20:
        cr = (cl[0] + 80, cl[1])
    hl = (cl[0] + (cr[0] - cl[0]) * 0.3, cl[1] + (cr[1] - cl[1]) * 0.3)
    hr = (cl[0] + (cr[0] - cl[0]) * 0.7, cl[1] + (cr[1] - cl[1]) * 0.7)
    d = 1.0 if hr[0] >= hl[0] else -1.0
    trunk = wire_curve(hl, d, hr, -d)
    breakouts = []
    seen = set()
    for e1, e2 in pairs:
        for (pt, pdir), hub, hdir in ((e1, hl, -d), (e2, hr, d)):
            key = (round(pt[0], 1), round(pt[1], 1), hub)
            if key in seen:          # several wires on one splice node -> one breakout
                continue
            seen.add(key)
            breakouts.append(wire_curve(pt, pdir, hub, hdir))
    return {"hubs": (hl, hr), "trunk": trunk, "breakouts": breakouts}
