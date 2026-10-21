"""Connector / terminal library.

Built-in parts cover the Deutsch DT, DTM and DTP families plus splices, ring
terminals and generic device pinouts. Add your own parts in
~/.ranchharness/library.json (same shape as BUILTIN below, a list of parts);
entries there override built-ins with the same key.

Part numbers were checked against distributor listings for the common
contacts, but always confirm against the TE/Deutsch datasheet before ordering.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

USER_LIBRARY = Path.home() / ".ranchharness" / "library.json"


@dataclass
class Terminal:
    pn: str
    awg_max: int        # largest wire (smallest AWG number) it accepts
    awg_min: int        # smallest wire (largest AWG number) it accepts
    desc: str = ""

    def fits(self, awg: int) -> bool:
        return self.awg_max <= awg <= self.awg_min


@dataclass
class Part:
    key: str
    name: str
    family: str
    positions: int                     # 0 = set per instance (generic parts)
    kind: str = "connector"            # connector | splice | ring | device
    contact: str = "pin"               # pin | socket | none
    housing_pn: str = ""
    secondary_lock_pn: str = ""
    cavity_plug_pn: str = ""
    boot_pn: str = ""                  # boot / backshell
    wire_seal_pn: str = ""             # per-wire seal; "integral" if built into the housing
    sealed: bool = False
    prefix: str = "J"
    mate: str = ""                     # key of the mating part
    terminals: list[Terminal] = field(default_factory=list)
    pin_labels: Optional[list[str]] = None
    multi_wire: bool = False           # splices/rings accept several wires
    notes: str = ""

    def pins(self, override: int = 0) -> list[str]:
        if self.pin_labels:
            return list(self.pin_labels)
        n = self.positions or override or 1
        return [str(i) for i in range(1, n + 1)]

    def terminal_for(self, awg: int) -> Optional[Terminal]:
        return next((t for t in self.terminals if t.fits(awg)), None)

    @classmethod
    def from_dict(cls, d: dict) -> "Part":
        d = dict(d)
        terms = [Terminal(**t) for t in d.pop("terminals", [])]
        return cls(terminals=terms, **d)


# ---- built-in parts ------------------------------------------------------

DT_PIN = [Terminal("0460-202-16141", 16, 20, "DT size 16 solid pin, 16-20 AWG"),
          Terminal("0460-215-16141", 14, 14, "DT size 16 solid pin, 14 AWG")]
DT_SOCKET = [Terminal("0462-201-16141", 16, 20, "DT size 16 solid socket, 16-20 AWG"),
             Terminal("0462-209-16141", 14, 14, "DT size 16 solid socket, 14 AWG")]
DTM_PIN = [Terminal("0460-202-20141", 20, 24, "DTM size 20 solid pin, 20-24 AWG")]
DTM_SOCKET = [Terminal("0462-201-20141", 20, 24, "DTM size 20 solid socket, 20-24 AWG")]
DTP_PIN = [Terminal("0460-204-12141", 12, 14, "DTP size 12 solid pin, 12-14 AWG")]
DTP_SOCKET = [Terminal("0462-203-12141", 12, 14, "DTP size 12 solid socket, 12-14 AWG")]


def _deutsch() -> list[Part]:
    parts = []
    fams = [
        ("DT", (2, 3, 4, 6, 8, 12), "W{n}P", "W{n}S", DT_PIN, DT_SOCKET, "0413-217-1605"),
        ("DTM", (2, 3, 4, 6, 8, 12), "WM-{n}P", "WM-{n}S", DTM_PIN, DTM_SOCKET, "0413-204-2005"),
        ("DTP", (2, 4), "WP-{n}P", "WP-{n}S", DTP_PIN, DTP_SOCKET, ""),
    ]
    for fam, sizes, wp, ws, pins, socks, plug in fams:
        for n in sizes:
            rec, plg = f"{fam}04-{n}P", f"{fam}06-{n}S"
            parts.append(Part(
                key=rec, name=f"Deutsch {rec} receptacle ({n}-way, pins)", family=f"Deutsch {fam}",
                positions=n, contact="pin", housing_pn=rec, secondary_lock_pn=wp.format(n=n),
                cavity_plug_pn=plug, wire_seal_pn="integral", sealed=True, mate=plg,
                terminals=pins))
            parts.append(Part(
                key=plg, name=f"Deutsch {plg} plug ({n}-way, sockets)", family=f"Deutsch {fam}",
                positions=n, contact="socket", housing_pn=plg, secondary_lock_pn=ws.format(n=n),
                cavity_plug_pn=plug, wire_seal_pn="integral", sealed=True, mate=rec,
                terminals=socks))
    return parts


GENERAL_WIRE = [Terminal("", 10, 26, "per device / user-specified")]

BUILTIN: list[Part] = _deutsch() + [
    Part(key="SPLICE", name="Inline splice", family="Splices & terminals", positions=1,
         kind="splice", contact="none", housing_pn="SPLICE", prefix="SP",
         pin_labels=["S"], multi_wire=True,
         notes="Set the splice part number (crimp splice or solder sleeve) in your library."),
    Part(key="RING-M6", name="Ring terminal, M6 / 1/4\"", family="Splices & terminals",
         positions=1, kind="ring", contact="none", housing_pn="RING-M6", prefix="GND",
         pin_labels=["R"], multi_wire=True),
    Part(key="RING-M8", name="Ring terminal, M8 / 5/16\"", family="Splices & terminals",
         positions=1, kind="ring", contact="none", housing_pn="RING-M8", prefix="GND",
         pin_labels=["R"], multi_wire=True),
    Part(key="DEVICE", name="Device / ECU (generic, set pin count)", family="Generic",
         positions=0, kind="device", contact="none", prefix="U", terminals=GENERAL_WIRE,
         notes="Use for an ECU, sensor or module whose connector you'll specify later."),
    Part(key="GENERIC-CONN", name="Generic connector (set pin count)", family="Generic",
         positions=0, kind="connector", contact="none", prefix="J", terminals=GENERAL_WIRE),
]


class Library:
    def __init__(self, extra_path: Path | None = USER_LIBRARY):
        self.parts: dict[str, Part] = {p.key: p for p in BUILTIN}
        self.user_path = extra_path
        if extra_path and extra_path.exists():
            self.load_file(extra_path)

    def load_file(self, path: Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for d in data:
            p = Part.from_dict(d)
            self.parts[p.key] = p

    def get(self, key: str) -> Optional[Part]:
        return self.parts.get(key)

    def families(self) -> dict[str, list[Part]]:
        out: dict[str, list[Part]] = {}
        for p in self.parts.values():
            out.setdefault(p.family, []).append(p)
        return out


_default: Library | None = None


def default_library() -> Library:
    global _default
    if _default is None:
        _default = Library()
    return _default
