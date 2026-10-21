"""Core harness data model. Pure Python, no Qt, so it can be scripted and tested."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

FILE_VERSION = 1


def new_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Connector:
    """One placed connector (or splice / device pigtail) in the harness."""
    part_key: str                      # key into the connector library
    ref: str                           # designator, e.g. "J1", "INJ1", "SP1"
    label: str = ""                    # human description, e.g. "Injector #1"
    pin_names: dict[str, str] = field(default_factory=dict)  # pin -> signal name
    x: float = 0.0
    y: float = 0.0
    flipped: bool = False              # False: wires leave to the right
    positions: int = 0                 # pin count for generic/variable parts
    pin_desc: dict[str, str] = field(default_factory=dict)  # pin -> longer description
    boot_pn: str = ""                  # overrides the library boot / backshell
    seal_pn: str = ""                  # overrides the library wire seal
    notes: str = ""
    id: str = field(default_factory=new_id)


@dataclass
class Wire:
    a_conn: str                        # connector id
    a_pin: str
    b_conn: str
    b_pin: str
    awg: int = 18
    color: str = "BK"                  # base color, or base/stripe e.g. "RD/WH"
    wire_type: str = "TXL"
    length_mm: float = 500.0
    signal: str = ""
    label: str = ""                    # wire number printed on the harness, e.g. "W1"
    id: str = field(default_factory=new_id)


@dataclass
class Bundle:
    """A group of wires that run together and share sleeving."""
    name: str
    wire_ids: list[str] = field(default_factory=list)
    sleeving: str = ""                 # key into the sleeving library ("" = none)
    size: str = ""                     # "" = pick automatically from bundle diameter
    color: str = "BK"
    length_mm: float = 0.0             # 0 = use the shortest wire in the bundle
    show_wires: bool = False           # keep wires visible even when bundles are collapsed
    notes: str = ""
    id: str = field(default_factory=new_id)


@dataclass
class Harness:
    name: str = "Untitled harness"
    part_number: str = ""
    revision: str = "A"
    notes: str = ""
    waste_factor: float = 0.10         # extra wire added to BOM totals
    connectors: list[Connector] = field(default_factory=list)
    wires: list[Wire] = field(default_factory=list)
    bundles: list[Bundle] = field(default_factory=list)

    # ---- lookup -------------------------------------------------------
    def connector(self, cid: str) -> Optional[Connector]:
        return next((c for c in self.connectors if c.id == cid), None)

    def wire(self, wid: str) -> Optional[Wire]:
        return next((w for w in self.wires if w.id == wid), None)

    def by_ref(self, ref: str) -> Optional[Connector]:
        return next((c for c in self.connectors if c.ref == ref), None)

    def wires_at(self, cid: str, pin: str | None = None) -> list[Wire]:
        out = []
        for w in self.wires:
            if (w.a_conn == cid and (pin is None or w.a_pin == pin)) or \
               (w.b_conn == cid and (pin is None or w.b_pin == pin)):
                out.append(w)
        return out

    # ---- editing ------------------------------------------------------
    def next_ref(self, prefix: str) -> str:
        used = {c.ref for c in self.connectors}
        n = 1
        while f"{prefix}{n}" in used:
            n += 1
        return f"{prefix}{n}"

    def next_wire_label(self) -> str:
        used = {w.label for w in self.wires}
        n = 1
        while f"W{n}" in used:
            n += 1
        return f"W{n}"

    def add_connector(self, part_key: str, prefix: str = "J", **kw) -> Connector:
        kw.setdefault("ref", self.next_ref(prefix))
        c = Connector(part_key=part_key, **kw)
        self.connectors.append(c)
        return c

    def add_wire(self, a: Connector, a_pin, b: Connector, b_pin, **kw) -> Wire:
        kw.setdefault("label", self.next_wire_label())
        w = Wire(a_conn=a.id, a_pin=str(a_pin), b_conn=b.id, b_pin=str(b_pin), **kw)
        self.wires.append(w)
        return w

    def remove_connector(self, cid: str) -> None:
        self.connectors = [c for c in self.connectors if c.id != cid]
        self.wires = [w for w in self.wires if w.a_conn != cid and w.b_conn != cid]
        self._prune_bundles()

    def remove_wire(self, wid: str) -> None:
        self.wires = [w for w in self.wires if w.id != wid]
        self._prune_bundles()

    def _prune_bundles(self) -> None:
        ids = {w.id for w in self.wires}
        for b in self.bundles:
            b.wire_ids = [i for i in b.wire_ids if i in ids]

    # ---- bundles ------------------------------------------------------
    def bundle(self, bid: str) -> Optional[Bundle]:
        return next((b for b in self.bundles if b.id == bid), None)

    def bundles_of(self, wid: str) -> list[Bundle]:
        return [b for b in self.bundles if wid in b.wire_ids]

    def next_bundle_name(self) -> str:
        used = {b.name for b in self.bundles}
        n = 1
        while f"B{n}" in used:
            n += 1
        return f"B{n}"

    def add_bundle(self, wire_ids, **kw) -> Bundle:
        kw.setdefault("name", self.next_bundle_name())
        b = Bundle(wire_ids=[i for i in dict.fromkeys(wire_ids) if self.wire(i)], **kw)
        self.bundles.append(b)
        return b

    def remove_bundle(self, bid: str) -> None:
        self.bundles = [b for b in self.bundles if b.id != bid]

    def endpoint_text(self, cid: str, pin: str) -> str:
        c = self.connector(cid)
        return f"{c.ref if c else '?'}:{pin}"

    # ---- persistence --------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["version"] = FILE_VERSION
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Harness":
        d = dict(d)
        d.pop("version", None)
        conns = [Connector(**c) for c in d.pop("connectors", [])]
        wires = [Wire(**w) for w in d.pop("wires", [])]
        bundles = [Bundle(**b) for b in d.pop("bundles", [])]
        return cls(connectors=conns, wires=wires, bundles=bundles, **d)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Harness":
        return cls.from_dict(json.loads(text))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Harness":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))
