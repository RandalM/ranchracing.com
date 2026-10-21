"""Wire/cut list and BOM generation (pure Python)."""
from __future__ import annotations

import csv
import io
from collections import OrderedDict
from pathlib import Path

from . import colors
from . import tools as tools_mod
from .tools import ToolLibrary
from .library import Library, default_library
from .model import Harness

MM_PER_FT = 304.8


def _sort_key(label: str):
    digits = "".join(ch for ch in label if ch.isdigit())
    return (label.rstrip("0123456789"), int(digits) if digits else 0, label)


def _terminal_pn(h: Harness, lib: Library, cid: str, awg: int) -> str:
    c = h.connector(cid)
    part = lib.get(c.part_key) if c else None
    if not part or part.contact == "none":
        return ""
    t = part.terminal_for(awg)
    return t.pn if t else f"NO TERMINAL FOR {awg} AWG"


def wire_list(h: Harness, lib: Library | None = None) -> list[dict]:
    lib = lib or default_library()
    rows = []
    for w in sorted(h.wires, key=lambda w: _sort_key(w.label)):
        a, b = h.connector(w.a_conn), h.connector(w.b_conn)
        rows.append(OrderedDict([
            ("Wire", w.label),
            ("Signal", w.signal or (a.pin_names.get(w.a_pin, "") if a else "")),
            ("From", a.ref if a else "?"),
            ("From pin", w.a_pin),
            ("From terminal", _terminal_pn(h, lib, w.a_conn, w.awg)),
            ("To", b.ref if b else "?"),
            ("To pin", w.b_pin),
            ("To terminal", _terminal_pn(h, lib, w.b_conn, w.awg)),
            ("AWG", w.awg),
            ("Type", w.wire_type),
            ("Color", w.color),
            ("Color name", colors.describe(w.color)),
            ("Length (mm)", round(w.length_mm)),
            ("Length (in)", round(w.length_mm / 25.4, 1)),
            ("Bundle", ", ".join(b.name for b in h.bundles_of(w.id))),
        ]))
    return rows


def bom(h: Harness, lib: Library | None = None) -> list[dict]:
    lib = lib or default_library()
    items: "OrderedDict[str, dict]" = OrderedDict()

    def add(pn: str, desc: str, qty: float, unit: str, ref: str, category: str):
        if not pn:
            return
        key = f"{category}|{pn}"
        it = items.setdefault(key, {"Category": category, "Part number": pn,
                                    "Description": desc, "Qty": 0, "Unit": unit, "Used on": []})
        it["Qty"] += qty
        if ref and ref not in it["Used on"]:
            it["Used on"].append(ref)

    for c in sorted(h.connectors, key=lambda c: _sort_key(c.ref)):
        part = lib.get(c.part_key)
        if not part:
            add(c.part_key, "UNKNOWN PART", 1, "ea", c.ref, "1 Connectors & splices")
            continue
        if part.kind in ("connector", "splice", "ring"):
            add(part.housing_pn, part.name, 1, "ea", c.ref, "1 Connectors & splices")
        if part.secondary_lock_pn:
            add(part.secondary_lock_pn, f"Secondary lock for {part.housing_pn}", 1, "ea", c.ref,
                "2 Locks & boots")
        used = set()
        for w in h.wires_at(c.id):
            for cid, pin in ((w.a_conn, w.a_pin), (w.b_conn, w.b_pin)):
                if cid != c.id or (pin, w.id) in used:
                    continue
                used.add((pin, w.id))
                if part.contact != "none":
                    t = part.terminal_for(w.awg)
                    if t:
                        add(t.pn, t.desc, 1, "ea", c.ref, "3 Terminals")
                    else:
                        add(f"?{part.key}-{w.awg}AWG", f"No terminal for {w.awg} AWG in {part.key}",
                            1, "ea", c.ref, "3 Terminals")
                seal = c.seal_pn or part.wire_seal_pn
                if seal and seal.lower() != "integral":
                    add(seal, f"Wire seal for {part.housing_pn or part.key}", 1, "ea", c.ref,
                        "4 Seals & plugs")
        boot = c.boot_pn or part.boot_pn
        if boot:
            add(boot, f"Boot / backshell for {part.housing_pn or part.key}", 1, "ea", c.ref, "2 Locks & boots")
        if part.sealed and part.cavity_plug_pn:
            occupied = {pin for pin, _ in used}
            empty = len([p for p in part.pins(c.positions) if p not in occupied])
            if empty:
                add(part.cavity_plug_pn, "Cavity sealing plug", empty, "ea", c.ref, "4 Seals & plugs")

    waste = 1 + max(h.waste_factor, 0)
    for b in h.bundles:
        i = bundle_info(h, b)
        if i["type"] and i["pn"] and i["wires"]:
            desc = i["type"].name + (f" {i['size'].name}" if i["size"] else "") + (f", {b.color}" if b.color else "")
            add(i["pn"], desc, i["qty"] * waste, i["unit"], b.name, "6 Sleeving")
    for w in h.wires:
        pn = f"{w.wire_type}-{w.awg}-{w.color.replace('/', '')}"
        desc = f"{w.awg} AWG {w.wire_type}, {colors.describe(w.color)}"
        add(pn, desc, w.length_mm / MM_PER_FT * waste, "ft", w.label, "5 Wire")

    rows = []
    for n, it in enumerate(sorted(items.values(), key=lambda i: (i["Category"], i["Part number"])), 1):
        qty = it["Qty"]
        rows.append(OrderedDict([
            ("Item", n),
            ("Category", it["Category"][2:]),
            ("Part number", it["Part number"]),
            ("Description", it["Description"]),
            ("Qty", round(qty, 1) if it["Unit"] in ("ft", "m") else int(qty)),
            ("Unit", it["Unit"]),
            ("Used on", ", ".join(sorted(it["Used on"], key=_sort_key))),
        ]))
    return rows


def to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    wr = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    wr.writeheader()
    wr.writerows(rows)
    return buf.getvalue()


def write_csv(rows: list[dict], path: str | Path) -> None:
    Path(path).write_text(to_csv(rows), encoding="utf-8", newline="")


# ---- connector details / pinout ------------------------------------------

def _is_node(lib: Library, c) -> bool:
    p = lib.get(c.part_key) if c else None
    return bool(p and p.kind in ("splice", "ring"))


def _pin_label(c, pin: str) -> str:
    name = c.pin_names.get(pin, "")
    return f"{c.ref}:{pin}" + (f" ({name})" if name else "")


def trace(h: Harness, lib: Library, cid: str, via_wire: str) -> list[str]:
    """Endpoints reached by going through a splice/ring node, excluding the wire we came in on."""
    out, seen_nodes, seen_wires = [], {cid}, {via_wire}
    stack = [cid]
    while stack:
        node = stack.pop()
        for w in h.wires_at(node):
            if w.id in seen_wires:
                continue
            seen_wires.add(w.id)
            ocid, opin = (w.b_conn, w.b_pin) if w.a_conn == node else (w.a_conn, w.a_pin)
            oc = h.connector(ocid)
            if not oc:
                continue
            if _is_node(lib, oc) and ocid not in seen_nodes:
                seen_nodes.add(ocid)
                out.append(f"{oc.ref} [{w.label}]")
                stack.append(ocid)
            else:
                out.append(f"{_pin_label(oc, opin)} [{w.label}]")
    return out


def connector_details(h: Harness, cid: str, lib: Library | None = None,
                      tools: ToolLibrary | None = None) -> dict:
    """Everything about one connector: resolved part numbers and a per-pin routing table."""
    lib = lib or default_library()
    tools = tools if tools is not None else tools_mod.default_tools()
    c = h.connector(cid)
    part = lib.get(c.part_key)
    seal = (c.seal_pn or (part.wire_seal_pn if part else "")) or ""
    seal_txt = "Integral to housing" if seal.lower() == "integral" else seal
    info = OrderedDict([
        ("Designator", c.ref),
        ("Label", c.label),
        ("Part", part.name if part else f"UNKNOWN ({c.part_key})"),
        ("Housing P/N", part.housing_pn if part else c.part_key),
        ("Mates with", part.mate if part else ""),
        ("Secondary lock P/N", part.secondary_lock_pn if part else ""),
        ("Boot / backshell P/N", c.boot_pn or (part.boot_pn if part else "")),
        ("Wire seal P/N", seal_txt),
        ("Cavity plug P/N", part.cavity_plug_pn if part else ""),
        ("Terminals available", "; ".join(f"{t.pn} ({t.awg_max}-{t.awg_min} AWG)"
                                          for t in (part.terminals if part else []) if t.pn)),
    ])
    pins = part.pins(c.positions) if part else [str(i) for i in range(1, (c.positions or 1) + 1)]
    rows = []
    terminals_used: dict[str, int] = {}
    for pin in pins:
        wires = h.wires_at(c.id, pin)
        base = OrderedDict([("Pin", pin), ("Signal", c.pin_names.get(pin, "")),
                            ("Description", c.pin_desc.get(pin, ""))])
        if not wires:
            rows.append(OrderedDict(base, **{
                "Wire": "", "AWG": "", "Color": "", "Length (mm)": "", "Terminal P/N": "",
                "Crimper": "", "Die": "", "Crimp setting": "",
                "Seal / plug": (part.cavity_plug_pn + " (plug)") if part and part.sealed and part.cavity_plug_pn else "",
                "To": "— unused —", "Route": ""}))
            continue
        for w in sorted(wires, key=lambda w: _sort_key(w.label)):
            ocid, opin = (w.b_conn, w.b_pin) if (w.a_conn == c.id and w.a_pin == pin) else (w.a_conn, w.a_pin)
            oc = h.connector(ocid)
            term = ""
            tool = None
            if part and part.contact != "none":
                t = part.terminal_for(w.awg)
                term = t.pn if t else f"NONE FOR {w.awg} AWG"
                terminals_used[term] = terminals_used.get(term, 0) + 1
            tool = tools.lookup(term, w.awg) if term else None
            if oc and _is_node(lib, oc):
                to = f"{oc.ref} ({lib.get(oc.part_key).name}{', ' + oc.label if oc.label else ''})"
                legs = trace(h, lib, ocid, w.id)
                route = f"{c.ref}:{pin} → {w.label} → {oc.ref}" + \
                    (" → " + ", ".join(legs) if legs else " (terminates)")
            else:
                to = _pin_label(oc, opin) if oc else "?"
                route = f"{c.ref}:{pin} → {w.label} → {oc.ref + ':' + opin if oc else '?'}"
            rows.append(OrderedDict(base, **{
                "Wire": w.label, "AWG": w.awg, "Color": w.color, "Length (mm)": round(w.length_mm),
                "Terminal P/N": term,
                "Crimper": tool.crimper if tool else "", "Die": tool.die if tool else "",
                "Crimp setting": tool.setting if tool else "",
                "Seal / plug": seal_txt if seal else "",
                "To": to, "Route": route,
                "_wire_id": w.id, "_to_id": ocid, "_wire_signal": w.signal}))
    info["Terminals used"] = "; ".join(f"{n}× {pn}" for pn, n in terminals_used.items())
    info["Pins used"] = f"{len({r['Pin'] for r in rows if r['Wire']})} of {len(pins)}"
    return {"info": info, "rows": rows, "notes": c.notes}


def pinout_report(h: Harness, lib: Library | None = None,
                  tools: ToolLibrary | None = None) -> list[dict]:
    """Flat CSV-friendly pinout of every connector."""
    lib = lib or default_library()
    out = []
    for c in sorted(h.connectors, key=lambda c: _sort_key(c.ref)):
        d = connector_details(h, c.id, lib, tools)
        inf = d["info"]
        for r in d["rows"]:
            out.append(OrderedDict([
                ("Connector", c.ref), ("Label", c.label), ("Housing P/N", inf["Housing P/N"]),
                ("Boot P/N", inf["Boot / backshell P/N"]), ("Wire seal P/N", inf["Wire seal P/N"]),
                ("Lock P/N", inf["Secondary lock P/N"]),
                *[(k, v) for k, v in r.items() if not k.startswith("_")]]))
    return out


def crimp_sheet(h: Harness, lib: Library | None = None, tools: ToolLibrary | None = None) -> list[dict]:
    """Bench sheet: each terminal/gauge combination, how many, and which tool settings to use."""
    lib = lib or default_library()
    tools = tools if tools is not None else tools_mod.default_tools()
    combos: "OrderedDict[tuple[str, int], dict]" = OrderedDict()
    for w in h.wires:
        for cid in (w.a_conn, w.b_conn):
            c = h.connector(cid)
            part = lib.get(c.part_key) if c else None
            if not part or part.contact == "none":
                continue
            t = part.terminal_for(w.awg)
            if not t:
                continue
            e = combos.setdefault((t.pn, w.awg), {"qty": 0, "refs": [], "desc": t.desc})
            e["qty"] += 1
            if c.ref not in e["refs"]:
                e["refs"].append(c.ref)
    rows = []
    for (pn, awg), e in sorted(combos.items()):
        tool = tools.lookup(pn, awg)
        if tool and not (tool.crimper or tool.die or tool.setting):
            tool = None
        rows.append(OrderedDict([
            ("Terminal P/N", pn), ("Description", e["desc"]), ("AWG", awg), ("Qty", e["qty"]),
            ("Crimper", tool.crimper if tool else "— not set —"),
            ("Die / locator", tool.die if tool else ""),
            ("Setting", tool.setting if tool else ""),
            ("Notes", tool.notes if tool else ""),
            ("Used on", ", ".join(sorted(e["refs"], key=_sort_key))),
        ]))
    return rows


# ---- bundles & sleeving -------------------------------------------------

def bundle_info(h: Harness, b, sleeves=None) -> dict:
    from . import sleeving as sl
    sleeves = sleeves or sl.default_sleeving()
    wires = [h.wire(i) for i in b.wire_ids if h.wire(i)]
    d = sl.bundle_diameter([sl.wire_od(w.awg, w.wire_type) for w in wires])
    length = b.length_mm or (min(w.length_mm for w in wires) if wires else 0.0)
    st = sleeves.get(b.sleeving) if b.sleeving else None
    rec = st.recommend(d) if st and st.kind != "tape" else None
    size = (st.size(b.size) if (st and b.size) else rec) if st and st.kind != "tape" else None
    status = ""
    if not wires:
        status = "empty"
    elif not st:
        status = "no sleeving" if not b.sleeving else f"unknown sleeving '{b.sleeving}'"
    elif st.kind == "tape":
        status = "ok"
    elif not size:
        status = "no size fits"
    elif not size.fits(d):
        status = f"{size.name} doesn't fit {d:.1f} mm (try {rec.name})" if rec else "size doesn't fit"
    else:
        status = "ok"
    qty, unit = 0.0, "ft"
    if st and st.kind == "tape":
        qty, unit = sl.tape_length_mm(length, d, st.tape_width_mm, st.overlap) / 1000, "m"
    elif st:
        qty = length / MM_PER_FT
    return {"wires": wires, "diameter": d, "length": length, "type": st, "size": size,
            "recommended": rec, "pn": st.part_number(size, b.color) if st else "",
            "status": status, "qty": qty, "unit": unit}


def bundle_report(h: Harness, sleeves=None) -> list[dict]:
    rows = []
    for b in sorted(h.bundles, key=lambda b: _sort_key(b.name)):
        i = bundle_info(h, b, sleeves)
        st = i["type"]
        rows.append(OrderedDict([
            ("Bundle", b.name), ("Wires", ", ".join(w.label for w in sorted(i["wires"], key=lambda w: _sort_key(w.label)))),
            ("Wire count", len(i["wires"])), ("Diameter (mm)", round(i["diameter"], 1)),
            ("Sleeving", st.name if st else ""),
            ("Size", (i["size"].name if i["size"] else "") + ("" if b.size or not i["size"] else " (auto)")),
            ("Part number", i["pn"]), ("Color", b.color if st else ""),
            ("Length (mm)", round(i["length"])),
            ("Material qty", f"{i['qty']:.1f} {i['unit']}" if st else ""),
            ("Status", i["status"]), ("Notes", b.notes),
        ]))
    return rows
