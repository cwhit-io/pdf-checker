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

# Rich-black threshold: if any single CMY channel > this in a nominally-black
# object it is considered rich black (rough, based on raw PDF stream scanning)
_RICH_BLACK_CMY_MIN = 20  # percent


def _scan_xrefs(doc: fitz.Document):
    """Scan all PDF indirect objects for color-related data."""
    colorspaces: set[str] = set()
    spot_names: set[str] = set()
    icc_xrefs: list[int] = []
    rich_black_hints: list[str] = []

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

        # ICCBased streams — collect their xrefs for profile inspection
        if "/ICCBased" in obj:
            icc_xrefs.append(xref)

        # Rich-black heuristic: CMYK value where K=1 AND any CMY > 0.2
        # Looks for patterns like "0.3 0.2 0 1 k" (CMYK fill operator)
        for m in re.finditer(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+k\b", obj):
            try:
                c, m_val, y, k = (
                    float(m.group(1)),
                    float(m.group(2)),
                    float(m.group(3)),
                    float(m.group(4)),
                )
                if k > 0.8 and (c > 0.2 or m_val > 0.2 or y > 0.2):
                    rich_black_hints.append(
                        f"C{c * 100:.0f}M{m_val * 100:.0f}Y{y * 100:.0f}K{k * 100:.0f}"
                    )
            except ValueError:
                pass

    return colorspaces, spot_names, icc_xrefs, rich_black_hints


def _check_icc_profiles(doc: fitz.Document, icc_xrefs: list[int]) -> list[str]:
    """Return a list of issue strings for detected ICC profile problems."""
    issues: list[str] = []
    seen: set[int] = set()
    for xref in icc_xrefs:
        if xref in seen:
            continue
        seen.add(xref)
        try:
            stream = doc.xref_stream_raw(xref)
            if stream and len(stream) < 128:
                issues.append(
                    f"xref {xref}: suspiciously small ICC stream ({len(stream)} bytes)"
                )
            # Basic ICC signature check: bytes 36-40 should be "acsp"
            if stream and len(stream) >= 40:
                sig = stream[36:40]
                if sig != b"acsp":
                    issues.append(f"xref {xref}: ICC profile missing 'acsp' signature")
        except Exception:
            pass
    return issues


def check_color(doc: fitz.Document) -> List[CheckItem]:
    checks: List[CheckItem] = []

    colorspaces, spot_names, icc_xrefs, rich_black_hints = _scan_xrefs(doc)

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

    # ── Rich-black ───────────────────────────────────────────────────────────
    if rich_black_hints:
        sample = sorted(set(rich_black_hints))[:5]
        checks.append(
            CheckItem(
                name="Rich-Black Detected",
                passed=False,
                detail=(
                    f"Multi-channel black values found (e.g. {', '.join(sample)}) — "
                    "small text in rich black may mis-register; prefer 100% K for body text"
                ),
                severity="warning",
            )
        )
    else:
        if "DeviceCMYK" in colorspaces:
            checks.append(
                CheckItem(
                    name="Rich-Black",
                    passed=True,
                    detail="No rich-black (multi-channel black) detected in CMYK content",
                    severity="info",
                )
            )

    # ── ICC profiles ─────────────────────────────────────────────────────────
    if icc_xrefs:
        icc_issues = _check_icc_profiles(doc, icc_xrefs)
        if icc_issues:
            checks.append(
                CheckItem(
                    name=f"ICC Profile Issues ({len(icc_issues)})",
                    passed=False,
                    detail="ICC profile problem(s): " + "; ".join(icc_issues[:3]),
                    severity="warning",
                )
            )
        else:
            checks.append(
                CheckItem(
                    name=f"ICC Profile(s) ({len(set(icc_xrefs))})",
                    passed=True,
                    detail=f"{len(set(icc_xrefs))} ICC profile stream(s) — basic signature valid",
                    severity="info",
                )
            )

    return checks
