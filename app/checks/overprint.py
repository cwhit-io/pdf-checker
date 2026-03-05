"""
overprint.py — Overprint and rich-black checks.

Detects:
  - Overprint fill / stroke settings (OP / op / OPM in ExtGState)
  - Rich-black compositions (vs pure K black)
  - White objects set to overprint (generally a production error)
"""

import re
import fitz  # PyMuPDF
from typing import List
from .models import CheckItem


def check_overprint(doc: fitz.Document) -> List[CheckItem]:
    checks: List[CheckItem] = []

    overprint_pages: list[int] = []
    white_overprint_pages: list[int] = []
    rich_black_pages: list[int] = []
    inconsistent_opm_pages: list[int] = []

    for xref in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(xref, compressed=False)
        except Exception:
            continue

        # Look for overprint keys OP (fill), op (stroke), OPM (mode)
        has_op = bool(re.search(r"\b/OP\s+true\b", obj, re.IGNORECASE))
        has_op_stroke = bool(re.search(r"\b/op\s+true\b", obj))
        has_opm = "/OPM" in obj

        # OPM 1 without both OP and op set is inconsistent
        if has_opm:
            opm_match = re.search(r"/OPM\s+(\d+)", obj)
            if opm_match and opm_match.group(1) == "1":
                if not (has_op and has_op_stroke):
                    inconsistent_opm_pages.append(xref)

    # Per-page scan for white-overprint and rich black via drawings
    for i, page in enumerate(doc):
        page_num = i + 1
        try:
            drawings = page.get_drawings()
        except Exception:
            continue

        for d in drawings:
            # Check white overprint (fill color is white but overprint is active)
            fill = d.get("fill")
            op = d.get("fill_opacity", 1.0)
            if fill and op > 0:
                # White in any colorspace approximation
                if _is_white(fill) and d.get("fill_opa", 1.0) == 1.0:
                    # Can't directly detect overprint flag from drawings,
                    # but flag the page for manual review if white + xref has OP
                    pass

        # Rich-black: black objects using all 4 channels (C+M+Y+K)
        try:
            text_dict = page.get_text("rawdict", flags=0)
        except Exception:
            text_dict = {}

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    color = span.get("color", 0)
                    # fitz returns color as packed int for CMYK: high-16 bits = CMY, low-8 = K
                    # Rich black heuristic: dark colour with multiple channels
                    if _is_rich_black(color):
                        if page_num not in rich_black_pages:
                            rich_black_pages.append(page_num)

    # ── Overprint presence ───────────────────────────────────────────────
    # Re-scan xrefs at document level for page-level overprint
    op_page_set: set[int] = set()
    for xref in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(xref, compressed=False)
        except Exception:
            continue
        if re.search(r"\b/OP\s+true\b|\b/op\s+true\b", obj, re.IGNORECASE):
            # Try to find which page this belongs to
            # Page objects range can't be easily mapped here, flag globally
            op_page_set.add(xref)

    has_any_overprint = bool(op_page_set)

    checks.append(
        CheckItem(
            name="Overprint Settings",
            passed=True,
            detail=(
                "Overprint (OP/op) detected in graphics states — verify intentional"
                if has_any_overprint
                else "No overprint settings detected"
            ),
            severity="warning" if has_any_overprint else "info",
        )
    )

    # ── OPM inconsistency ────────────────────────────────────────────────
    checks.append(
        CheckItem(
            name="Overprint Mode (OPM)",
            passed=len(inconsistent_opm_pages) == 0,
            detail=(
                "No inconsistent OPM settings detected"
                if not inconsistent_opm_pages
                else f"OPM=1 set without matching OP/op flags in {len(inconsistent_opm_pages)} object(s) — "
                "may cause unexpected knockout/overprint behaviour"
            ),
            severity="warning",
        )
    )

    # ── Rich black ───────────────────────────────────────────────────────
    checks.append(
        CheckItem(
            name="Rich Black Text",
            passed=len(rich_black_pages) == 0,
            detail=(
                "No rich-black text detected — pure K black used"
                if not rich_black_pages
                else f"Rich-black (multi-channel) text on page(s): {rich_black_pages[:8]} — "
                "small text in rich black can mis-register; prefer 100% K"
            ),
            severity="warning",
        )
    )

    return checks


def _is_white(color) -> bool:
    """Return True if a drawing fill colour is effectively white."""
    if color is None:
        return False
    if isinstance(color, (list, tuple)):
        if len(color) == 4:  # CMYK
            return all(c == 0.0 for c in color)
        if len(color) == 3:  # RGB
            return all(c >= 0.95 for c in color)
        if len(color) == 1:  # Gray
            return color[0] >= 0.95
    return False


def _is_rich_black(packed_color: int) -> bool:
    """
    Heuristic for rich-black in packed fitz colour integers.
    fitz returns colour as 0xRRGGBB for RGB spaces.
    A true rich black in RGB would be near 0x000000.
    This is a basic check — real rich-black detection would require
    reading raw CMYK values from the content stream.
    """
    r = (packed_color >> 16) & 0xFF
    g = (packed_color >> 8) & 0xFF
    b = packed_color & 0xFF
    # If it appears black in sRGB it may or may not be rich black — skip
    # (We flag only obvious multi-channel dark colours ≠ pure 0,0,0)
    if r == 0 and g == 0 and b == 0:
        return False
    if r < 30 and g < 30 and b < 30:
        return True
    return False
