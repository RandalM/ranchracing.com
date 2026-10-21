"""Browser-facing wrapper around the vendored ranchharness core.

Keeps the vendored package files byte-identical to the desktop app so they're
easy to re-sync later; all web-specific glue (JSON-friendly state snapshots,
hit-testing, a single mutable module-level harness) lives here instead.
"""
from __future__ import annotations

from ranchharness.model import Harness
from ranchharness.library import default_library
from ranchharness import layout, colors
from ranchharness import svg as svg_mod
from ranchharness import exports
from ranchharness import checks as checks_mod

PORT_R = 9.0 + 4.0
NODE_HIT_R = layout.NODE_R + 4.0

_lib = default_library()
_harness = Harness(name="Untitled harness")


def new_harness(name: str = "Untitled harness") -> dict:
    global _harness
    _harness = Harness(name=name)
    return state()


def load_harness(json_text: str) -> dict:
    global _harness
    _harness = Harness.from_json(json_text)
    return state()


def rename_harness(name: str) -> dict:
    _harness.name = name
    return state()


def to_json() -> str:
    return _harness.to_json()


def add_connector(part_key: str, positions: int, x: float, y: float, label: str = "") -> dict:
    part = _lib.get(part_key)
    prefix = part.prefix if part else "J"
    c = _harness.add_connector(part_key, prefix=prefix, positions=positions, x=x, y=y, label=label)
    return state(selected=c.id)


def move_connector(cid: str, x: float, y: float) -> dict:
    c = _harness.connector(cid)
    if c:
        c.x, c.y = x, y
    return state(selected=cid)


def update_connector(cid: str, **fields) -> dict:
    c = _harness.connector(cid)
    if c:
        for k, v in fields.items():
            setattr(c, k, v)
    return state(selected=cid)


def delete_connector(cid: str) -> dict:
    _harness.remove_connector(cid)
    return state()


def add_wire(a_cid: str, a_pin: str, b_cid: str, b_pin: str, **fields) -> dict:
    a, b = _harness.connector(a_cid), _harness.connector(b_cid)
    if not a or not b or (a_cid == b_cid and a_pin == b_pin):
        return state()
    w = _harness.add_wire(a, a_pin, b, b_pin, **fields)
    return state(selected=w.id)


def update_wire(wid: str, **fields) -> dict:
    w = _harness.wire(wid)
    if w:
        for k, v in fields.items():
            setattr(w, k, v)
    return state(selected=wid)


def delete_wire(wid: str) -> dict:
    _harness.remove_wire(wid)
    return state()


def port_at(x: float, y: float, allow_nodes: bool = True):
    """Nearest pin within hit-test radius, as {conn, pin} or None."""
    best, best_d = None, None
    for c in _harness.connectors:
        part = _lib.get(c.part_key)
        is_node = layout.is_node(part)
        if is_node and not allow_nodes:
            continue
        radius = NODE_HIT_R if is_node else PORT_R
        for pin in layout.pins(c, _lib):
            px, py = layout.port(c, pin, _lib)
            d = ((px - x) ** 2 + (py - y) ** 2) ** 0.5
            if d <= radius and (best_d is None or d < best_d):
                best, best_d = {"conn": c.id, "pin": pin}, d
    return best


def state(selected: str | None = None) -> dict:
    conns = []
    for c in _harness.connectors:
        part = _lib.get(c.part_key)
        w, h = layout.box_size(c, _lib)
        pins = layout.pins(c, _lib)
        conns.append({
            "id": c.id, "ref": c.ref, "label": c.label, "x": c.x, "y": c.y,
            "flipped": c.flipped, "positions": c.positions,
            "is_node": layout.is_node(part),
            "w": w, "h": h,
            "pins": pins,
            "pin_ports": {p: list(layout.port(c, p, _lib)) for p in pins},
            "pin_names": dict(c.pin_names),
        })
    wires = []
    for wr in _harness.wires:
        a, b = _harness.connector(wr.a_conn), _harness.connector(wr.b_conn)
        if not a or not b:
            continue
        p1, d1 = layout.port(a, wr.a_pin, _lib), layout.exit_dir(a, _lib)
        p2, d2 = layout.port(b, wr.b_pin, _lib), layout.exit_dir(b, _lib)
        curve = [list(pt) for pt in layout.wire_curve(p1, d1, p2, d2)]
        base, _stripe = colors.split(wr.color)
        wires.append({
            "id": wr.id, "label": wr.label,
            "a_conn": wr.a_conn, "a_pin": wr.a_pin, "b_conn": wr.b_conn, "b_pin": wr.b_pin,
            "awg": wr.awg, "color": wr.color, "wire_type": wr.wire_type,
            "length_mm": wr.length_mm, "signal": wr.signal,
            "curve": curve, "hex": colors.hex_of(base),
        })
    issues = [{"level": i.level, "message": i.message, "obj_id": i.obj_id}
              for i in checks_mod.check(_harness, _lib)]
    return {
        "name": _harness.name, "connectors": conns, "wires": wires, "issues": issues,
        "selected": selected,
    }


def catalog() -> dict:
    return {"colors": colors.all_codes(), "wire_types": list(colors.WIRE_TYPES),
            "awg": list(colors.AWG_SIZES)}


def export_svg() -> str:
    return svg_mod.render(_harness, _lib)


def export_wirelist_csv() -> str:
    return exports.to_csv(exports.wire_list(_harness, _lib))


def export_bom_csv() -> str:
    return exports.to_csv(exports.bom(_harness, _lib))
