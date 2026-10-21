"""Automotive wire color codes (two-letter, DIN 47100 / common motorsport style)."""

COLORS: dict[str, tuple[str, str]] = {
    # code: (name, hex for drawing)
    "BK": ("Black", "#1b1b1b"),
    "BN": ("Brown", "#7b4a1e"),
    "RD": ("Red", "#d12a2a"),
    "OG": ("Orange", "#f07f13"),
    "YE": ("Yellow", "#f2d21b"),
    "GN": ("Green", "#2a9a3c"),
    "BU": ("Blue", "#2463c9"),
    "VT": ("Violet", "#7d3fb8"),
    "GY": ("Grey", "#8c8c8c"),
    "WH": ("White", "#f4f4f4"),
    "PK": ("Pink", "#f08cb4"),
    "TN": ("Tan", "#c9ad7f"),
    "LG": ("Light green", "#8fd47a"),
    "LB": ("Light blue", "#7fc1ec"),
}

WIRE_TYPES = ["TXL", "GXL", "SXL", "M22759/32", "M22759/16", "Shielded twisted pair"]
AWG_SIZES = [8, 10, 12, 14, 16, 18, 20, 22, 24, 26]

# rough OD (mm) for TXL, used only for drawing line weight
TXL_OD = {8: 4.0, 10: 3.3, 12: 2.6, 14: 2.2, 16: 1.9, 18: 1.6, 20: 1.4, 22: 1.2, 24: 1.1, 26: 1.0}


def split(color: str) -> tuple[str, str | None]:
    parts = [p.strip().upper() for p in color.replace("-", "/").split("/") if p.strip()]
    if not parts:
        return "BK", None
    return parts[0], (parts[1] if len(parts) > 1 else None)


def hex_of(code: str) -> str:
    return COLORS.get(code.upper(), ("", "#999999"))[1]


def describe(color: str) -> str:
    base, stripe = split(color)
    name = COLORS.get(base, (base,))[0]
    if stripe:
        name += f" / {COLORS.get(stripe, (stripe,))[0]} stripe"
    return name


def all_codes() -> list[str]:
    """Solid colors plus the common base/stripe combinations."""
    solids = list(COLORS)
    stripes = [f"{b}/{s}" for b in solids for s in ("WH", "BK", "RD", "YE", "GN", "BU")
               if b != s]
    return solids + stripes
