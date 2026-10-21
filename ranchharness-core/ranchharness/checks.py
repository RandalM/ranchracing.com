"""Design rule checks."""
from __future__ import annotations

from dataclasses import dataclass

from .library import Library, default_library
from .model import Harness


@dataclass
class Issue:
    level: str        # "error" | "warning"
    message: str
    obj_id: str = ""  # connector or wire id to select


def pins_of(h: Harness, cid: str, lib: Library) -> list[str]:
    c = h.connector(cid)
    if not c:
        return []
    p = lib.get(c.part_key)
    return p.pins(c.positions) if p else [str(i) for i in range(1, (c.positions or 1) + 1)]


def check(h: Harness, lib: Library | None = None) -> list[Issue]:
    lib = lib or default_library()
    issues: list[Issue] = []

    refs: dict[str, int] = {}
    for c in h.connectors:
        refs[c.ref] = refs.get(c.ref, 0) + 1
        if not lib.get(c.part_key):
            issues.append(Issue("error", f"{c.ref}: unknown part '{c.part_key}'", c.id))
    for ref, n in refs.items():
        if n > 1:
            issues.append(Issue("error", f"Designator {ref} used {n} times"))

    labels: dict[str, int] = {}
    for w in h.wires:
        if w.label:
            labels[w.label] = labels.get(w.label, 0) + 1
    for lab, n in labels.items():
        if n > 1:
            issues.append(Issue("warning", f"Wire number {lab} used {n} times"))

    occupancy: dict[tuple[str, str], list[str]] = {}
    for w in h.wires:
        for cid, pin in ((w.a_conn, w.a_pin), (w.b_conn, w.b_pin)):
            c = h.connector(cid)
            if not c:
                issues.append(Issue("error", f"{w.label}: end attached to a missing connector", w.id))
                continue
            if pin not in pins_of(h, cid, lib):
                issues.append(Issue("error", f"{w.label}: {c.ref} has no pin {pin}", w.id))
            occupancy.setdefault((cid, pin), []).append(w.label or w.id)
            part = lib.get(c.part_key)
            if part and part.terminals and part.contact != "none":
                if not part.terminal_for(w.awg):
                    rng = ", ".join(f"{t.awg_max}-{t.awg_min}" for t in part.terminals)
                    issues.append(Issue("error",
                        f"{w.label}: {w.awg} AWG has no terminal in {c.ref} ({part.key}, accepts {rng} AWG)",
                        w.id))
        if w.a_conn == w.b_conn and w.a_pin == w.b_pin:
            issues.append(Issue("error", f"{w.label}: both ends on the same pin", w.id))
        if w.length_mm <= 0:
            issues.append(Issue("warning", f"{w.label}: length not set", w.id))

    for (cid, pin), wl in occupancy.items():
        c = h.connector(cid)
        part = lib.get(c.part_key) if c else None
        if len(wl) > 1 and not (part and part.multi_wire):
            issues.append(Issue("warning",
                f"{c.ref}:{pin} has {len(wl)} wires ({', '.join(wl)}); use a splice unless the terminal is rated for it",
                cid))

    from .exports import bundle_info
    for b in h.bundles:
        st = bundle_info(h, b)["status"]
        if st != "ok":
            issues.append(Issue("warning", f"Bundle {b.name}: {st}", b.id))

    for c in h.connectors:
        if not h.wires_at(c.id):
            issues.append(Issue("warning", f"{c.ref}: nothing connected", c.id))
    return issues
