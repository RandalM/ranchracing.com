"""Crimp tool library: which crimper, die/locator and setting to use for a terminal.

Stored per user in ~/.ranchharness/crimp_tools.json, separate from harness files,
because it describes your shop's tools rather than one harness.
An entry with awg = 0 applies to every gauge for that terminal; an entry with a
specific AWG wins over it.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .model import new_id

USER_TOOLS = Path.home() / ".ranchharness" / "crimp_tools.json"


@dataclass
class CrimpTool:
    terminal_pn: str
    awg: int = 0                 # 0 = any gauge
    crimper: str = ""            # e.g. "Deutsch HDT-48-00"
    die: str = ""                # die set / locator / positioner
    setting: str = ""            # selector position, dial number, pressure…
    notes: str = ""
    id: str = field(default_factory=new_id)


class ToolLibrary:
    def __init__(self, path: Path | None = USER_TOOLS):
        self.path = path
        self.tools: list[CrimpTool] = []
        if path and path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.tools = [CrimpTool(**d) for d in data]

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(t) for t in self.tools], indent=2), encoding="utf-8")

    def lookup(self, terminal_pn: str, awg: int) -> Optional[CrimpTool]:
        """Specific gauge beats "any gauge"; filled-in entries beat blank ones."""
        pn = terminal_pn.strip().upper()
        cands = [t for t in self.tools if t.terminal_pn.strip().upper() == pn and t.awg in (awg, 0)]
        if not cands:
            return None
        filled = lambda t: bool(t.crimper or t.die or t.setting)  # noqa: E731
        cands.sort(key=lambda t: (not filled(t), t.awg != awg))
        return cands[0]

    def find(self, terminal_pn: str, awg: int) -> Optional[CrimpTool]:
        pn = terminal_pn.strip().upper()
        return next((t for t in self.tools if t.terminal_pn.strip().upper() == pn and t.awg == awg), None)

    def add(self, **kw) -> CrimpTool:
        t = CrimpTool(**kw)
        self.tools.append(t)
        return t

    def remove(self, tid: str) -> None:
        self.tools = [t for t in self.tools if t.id != tid]


def describe(t: Optional[CrimpTool]) -> str:
    if not t:
        return ""
    bits = [t.crimper, f"die {t.die}" if t.die else "", f"setting {t.setting}" if t.setting else ""]
    return " · ".join(b for b in bits if b)


_default: ToolLibrary | None = None


def default_tools() -> ToolLibrary:
    global _default
    if _default is None:
        _default = ToolLibrary()
    return _default
