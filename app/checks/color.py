import re
import fitz  # PyMuPDF
from typing import List
from .models import CheckItem

# Friendly display names for color spaces shown in the UI
_CS_FRIENDLY: dict[str, str] = {
    "DeviceCMYK": "CMYK (press)",
    "DeviceRGB": "RGB (screen)",
    "DeviceGray": "Grayscale",
    "Lab": "Lab",
    "ICCBased": "ICC profile",
    "DeviceN/Spot": "Spot/specialty",
}

# Color space tags to look for in raw PDF object strings
_CS_MAP: dict[str, str] = {
    "/DeviceCMYK": "DeviceCMYK",
    "/DeviceRGB": "DeviceRGB",
    "/DeviceGray": "DeviceGray",
    "/Lab": "Lab",
    "/ICCBased": "ICCBased",
}


def _scan_xrefs(doc: fitz.Document):
    """Scan all PDF indirect objects for color-related data."""
    colorspaces: set[str] = set()
    spot_names: set[str] = set()

    for xref in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(xref, compressed=False)
        except Exception:
            continue

        for tag, label in _CS_MAP.items():
            if tag in obj:
                colorspaces.add(label)

        # Separation (spot) color names
        for m in re.finditer(r"/Separation\s+/([^\s/\[\]<>()\x00]+)", obj):
            name = m.group(1)
            if name not in ("None", "All"):
                spot_names.add(name)

        # DeviceN multi-channel spot
        m_dn = re.search(r"/DeviceN\s*\[([^\]]+)\]", obj)
        if m_dn:
            for token in m_dn.group(1).split():
                n = token.lstrip("/").strip()
                if n and n not in ("None", "All"):
                    spot_names.add(n)
                    colorspaces.add("DeviceN/Spot")

    return colorspaces, spot_names


def check_color(doc: fitz.Document) -> List[CheckItem]:
    checks: List[CheckItem] = []

    colorspaces, spot_names = _scan_xrefs(doc)

    # ── RGB detection ────────────────────────────────────────────────────────
    has_rgb = "DeviceRGB" in colorspaces

    # Build a readable summary of what color spaces are present
    cs_present = sorted(
        cs
        for cs in colorspaces
        if cs
        in ("DeviceCMYK", "DeviceRGB", "DeviceGray", "Lab", "ICCBased", "DeviceN/Spot")
    )
    cs_display = [_CS_FRIENDLY.get(cs, cs) for cs in cs_present]

    checks.append(
        CheckItem(
            name="RGB Color",
            passed=not has_rgb,
            detail=(
                f"Screen color (RGB) detected — needs to be converted for printing. "
                f"Colors found: {', '.join(cs_display)}"
            )
            if has_rgb
            else (
                f"No screen colors (RGB). Colors found: {', '.join(cs_display)}"
                if cs_display
                else "No color information found in this file"
            ),
            severity="error" if has_rgb else "info",
        )
    )

    # ── Spot colors ──────────────────────────────────────────────────────────
    if spot_names:
        spots_sorted = sorted(spot_names)[:12]
        suffix = " …" if len(spot_names) > 12 else ""
        checks.append(
            CheckItem(
                name=f"Spot Colors ({len(spot_names)})",
                passed=True,
                detail="Spot color(s): " + ", ".join(spots_sorted) + suffix,
                severity="warning",
            )
        )

    return checks
