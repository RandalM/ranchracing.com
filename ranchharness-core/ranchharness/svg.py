"""Standalone SVG wiring-diagram renderer (no Qt needed)."""
from __future__ import annotations

from html import escape
from pathlib import Path

from . import colors, layout
from .library import Library, default_library
from .model import Harness

FONT = "font-family='Helvetica, Arial, sans-serif'"


def _wire_width(awg: int) -> float:
    return 1.2 + colors.TXL_OD.get(awg, 1.4) * 1.1


def render(h: Harness, lib: Library | None = None, title_block: bool = True,
           collapse_bundles: bool = False) -> str:
    lib = lib or default_library()
    if not h.connectors:
        return "<svg xmlns='http://www.w3.org/2000/svg' width='200' height='60'></svg>"

    xs, ys = [], []
    for c in h.connectors:
        w, hh = layout.box_size(c, lib)
        xs += [c.x, c.x + w]
        ys += [c.y, c.y + hh]
    pad = 90
    x0, y0 = min(xs) - pad, min(ys) - pad
    W, H = max(xs) - x0 + pad, max(ys) - y0 + pad + (70 if title_block else 0)

    out = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='{x0:.0f} {y0:.0f} {W:.0f} {H:.0f}' "
           f"width='{W:.0f}' height='{H:.0f}'>",
           f"<rect x='{x0}' y='{y0}' width='{W}' height='{H}' fill='white'/>"]

    # collapsed bundles: trunk + breakouts instead of their wires
    hidden: set[str] = set()
    if collapse_bundles:
        from .exports import bundle_info
        for b in h.bundles:
            if b.show_wires or not b.wire_ids:
                continue
            wires = [h.wire(i) for i in b.wire_ids if h.wire(i)]
            g = layout.bundle_geometry(h, wires, lib)
            if not g:
                continue
            hidden.update(b.wire_ids)
            info = bundle_info(h, b)
            bw = max(7.0, min(28.0, 3.0 + info["diameter"] * 1.8))
            fill = colors.hex_of(b.color) if info["type"] else "#9a9a9a"

            def dpath(pts):
                return "M{:.1f},{:.1f} C{:.1f},{:.1f} {:.1f},{:.1f} {:.1f},{:.1f}".format(*sum(pts, ()))
            for c in g["breakouts"]:
                out.append(f"<path d='{dpath(c)}' fill='none' stroke='#555' stroke-opacity='0.6' stroke-width='1.4'/>")
            t = dpath(g["trunk"])
            out.append(f"<path d='{t}' fill='none' stroke='#333' stroke-width='{bw + 3:.1f}' stroke-linecap='round'/>")
            out.append(f"<path d='{t}' fill='none' stroke='{fill}' stroke-width='{bw:.1f}' stroke-linecap='round'/>")
            mx, my = layout.bezier_point(g["trunk"], 0.5)
            st = info["type"]
            what = (st.name.split(" (")[0] + (f" {info['size'].name}" if info["size"] else "")) if st else "no sleeving"
            txt = escape(f"{b.name} · {len(wires)} wires · {what}")
            tw = 6.2 * len(txt) + 12
            out.append(f"<rect x='{mx - tw / 2:.1f}' y='{my - bw / 2 - 22:.1f}' width='{tw:.1f}' height='17' rx='8' "
                       f"fill='white' stroke='#999' stroke-width='0.8'/>")
            out.append(f"<text x='{mx:.1f}' y='{my - bw / 2 - 10:.1f}' font-size='10' font-weight='bold' "
                       f"text-anchor='middle' {FONT}>{txt}</text>")

    # wires underneath
    for w in h.wires:
        if w.id in hidden:
            continue
        a, b = h.connector(w.a_conn), h.connector(w.b_conn)
        if not a or not b:
            continue
        pts = layout.wire_curve(layout.port(a, w.a_pin, lib), layout.exit_dir(a, lib),
                                layout.port(b, w.b_pin, lib), layout.exit_dir(b, lib))
        d = "M{:.1f},{:.1f} C{:.1f},{:.1f} {:.1f},{:.1f} {:.1f},{:.1f}".format(*sum(pts, ()))
        base, stripe = colors.split(w.color)
        ww = _wire_width(w.awg)
        out.append(f"<path d='{d}' fill='none' stroke='#333' stroke-width='{ww + 2:.1f}'/>")
        out.append(f"<path d='{d}' fill='none' stroke='{colors.hex_of(base)}' stroke-width='{ww:.1f}'/>")
        if stripe:
            out.append(f"<path d='{d}' fill='none' stroke='{colors.hex_of(stripe)}' "
                       f"stroke-width='{ww * 0.45:.1f}' stroke-dasharray='6 6'/>")
        mx, my = layout.bezier_point(pts, 0.5)
        txt = escape(f"{w.label}  {w.awg} {w.color}")
        tw = 6.2 * len(txt) + 8
        out.append(f"<rect x='{mx - tw / 2:.1f}' y='{my - 9:.1f}' width='{tw:.1f}' height='16' rx='3' "
                   f"fill='white' stroke='#999' stroke-width='0.6'/>")
        out.append(f"<text x='{mx:.1f}' y='{my + 3:.1f}' font-size='10' text-anchor='middle' {FONT}>{txt}</text>")

    # connectors on top
    for c in h.connectors:
        part = lib.get(c.part_key)
        if layout.is_node(part):
            r = layout.NODE_R
            fill = "#222" if part.kind == "splice" else "#fff"
            out.append(f"<circle cx='{c.x + r}' cy='{c.y + r}' r='{r}' fill='{fill}' stroke='#222' stroke-width='2'/>")
            out.append(f"<text x='{c.x + r}' y='{c.y - 6}' font-size='11' font-weight='bold' "
                       f"text-anchor='middle' {FONT}>{escape(c.ref)}</text>")
            if c.label:
                out.append(f"<text x='{c.x + r}' y='{c.y + 2 * r + 14}' font-size='10' fill='#555' "
                           f"text-anchor='middle' {FONT}>{escape(c.label)}</text>")
            continue
        bw, bh = layout.box_size(c, lib)
        out.append(f"<rect x='{c.x}' y='{c.y}' width='{bw}' height='{bh}' rx='4' fill='#fbfbf8' "
                   f"stroke='#222' stroke-width='1.5'/>")
        out.append(f"<rect x='{c.x}' y='{c.y}' width='{bw}' height='{layout.HEADER_H}' rx='4' fill='#e8ecf2' "
                   f"stroke='#222' stroke-width='1.5'/>")
        out.append(f"<text x='{c.x + 8}' y='{c.y + 18}' font-size='13' font-weight='bold' {FONT}>"
                   f"{escape(c.ref)}{(' — ' + escape(c.label)) if c.label else ''}</text>")
        out.append(f"<text x='{c.x + 8}' y='{c.y + 36}' font-size='10' fill='#444' {FONT}>"
                   f"{escape(part.housing_pn or part.name if part else c.part_key)}</text>")
        for i, pin in enumerate(layout.pins(c, lib)):
            ry = c.y + layout.HEADER_H + i * layout.ROW_H
            out.append(f"<line x1='{c.x}' y1='{ry}' x2='{c.x + bw}' y2='{ry}' stroke='#bbb' stroke-width='0.7'/>")
            px = c.x if c.flipped else c.x + bw - layout.PIN_COL_W
            out.append(f"<rect x='{px}' y='{ry}' width='{layout.PIN_COL_W}' height='{layout.ROW_H}' "
                       f"fill='#f0f0f0' stroke='#bbb' stroke-width='0.7'/>")
            out.append(f"<text x='{px + layout.PIN_COL_W / 2}' y='{ry + 15}' font-size='11' "
                       f"text-anchor='middle' {FONT}>{escape(pin)}</text>")
            name = c.pin_names.get(pin, "")
            if name:
                nx = c.x + layout.PIN_COL_W + 6 if c.flipped else c.x + 8
                out.append(f"<text x='{nx}' y='{ry + 15}' font-size='11' {FONT}>{escape(name)}</text>")

    if title_block:
        ty = y0 + H - 60
        out.append(f"<rect x='{x0 + 20}' y='{ty}' width='{W - 40}' height='44' fill='none' stroke='#222'/>")
        out.append(f"<text x='{x0 + 30}' y='{ty + 27}' font-size='15' font-weight='bold' {FONT}>"
                   f"{escape(h.name)}</text>")
        meta = f"P/N {h.part_number or '—'}  ·  Rev {h.revision}  ·  {len(h.connectors)} connectors, {len(h.wires)} wires"
        out.append(f"<text x='{x0 + W - 30}' y='{ty + 27}' font-size='12' text-anchor='end' {FONT}>"
                   f"{escape(meta)}</text>")
    out.append("</svg>")
    return "\n".join(out)


def write(h: Harness, path: str | Path, lib: Library | None = None, collapse_bundles: bool = False) -> None:
    Path(path).write_text(render(h, lib, collapse_bundles=collapse_bundles), encoding="utf-8")
