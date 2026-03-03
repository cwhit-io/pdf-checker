"""
Bleed & Trim checks.

Reuses infer_page_bleed() from geometry.py for all bleed/trim detection
so the same logic drives both checks and the visual preview overlay.
"""

import fitz  # PyMuPDF
from typing import List
from .models import CheckItem
from .geometry import (
    infer_page_bleed,
    _rect_approx_equal,
    _classify,
    BLEED_REQUIRED_PT,
    STANDARD_SIZES_PT,
    INFER_TOL_PT,
)


def check_bleed_trim(doc: fitz.Document) -> List[CheckItem]:
    checks: List[CheckItem] = []

    if doc.page_count == 0:
        checks.append(
            CheckItem(
                name="Has Pages",
                passed=False,
                detail="Document has no pages",
                severity="error",
            )
        )
        return checks

    # ── Page dimensions & trim size ──────────────────────────────
    # Collect unique page sizes and identify whether they match a known trim size
    size_summaries: list[str] = []
    sizes_seen: set[tuple[float, float]] = set()

    for i, page in enumerate(doc):
        w = round(page.mediabox.width, 1)
        h = round(page.mediabox.height, 1)
        key = (min(w, h), max(w, h))
        if key in sizes_seen:
            continue
        sizes_seen.add(key)

        bleed_info = infer_page_bleed(page)

        # Is this an exact standard size?
        exact_match = next(
            (
                name
                for name, (sw, sh) in STANDARD_SIZES_PT.items()
                if (abs(w - sw) < 2 and abs(h - sh) < 2)
                or (abs(w - sh) < 2 and abs(h - sw) < 2)
            ),
            None,
        )

        if exact_match:
            size_summaries.append(f'{w / 72:.3f}"×{h / 72:.3f}" ({exact_match})')
        elif bleed_info and bleed_info["source"] == "implied":
            b_mm = bleed_info["bleed_pt"] / 72 * 25.4
            b_in = bleed_info["bleed_pt"] / 72
            size_summaries.append(
                f'{w / 72:.3f}"×{h / 72:.3f}" '
                f'({bleed_info["size_name"]} + {b_in:.3f}" bleed)'
            )
        else:
            size_summaries.append(f'{w / 72:.3f}"×{h / 72:.3f}" (non-standard size)')

    mixed = len(sizes_seen) > 1
    checks.append(
        CheckItem(
            name="Page / Trim Size",
            passed=not mixed,
            detail="; ".join(size_summaries[:6]),
            severity="warning" if mixed else "info",
        )
    )

    # ── Bleed presence ───────────────────────────────────────────
    pages_explicit_bleed = 0
    pages_implied_bleed = 0
    pages_no_bleed: list[int] = []
    insufficient_bleed: list[str] = []
    implied_details: list[str] = []

    for i, page in enumerate(doc):
        info = infer_page_bleed(page)
        if info is None:
            pages_no_bleed.append(i + 1)
            continue
        if info["source"] == "explicit":
            pages_explicit_bleed += 1
        else:
            pages_implied_bleed += 1
            b_mm = info["bleed_pt"] / 72 * 25.4
            implied_details.append(
                f"p{i + 1}: {info['size_name']} + {b_mm:.2f} mm (detected)"
            )
        # Check bleed amount for both explicit and implied
        if info["bleed_pt"] < BLEED_REQUIRED_PT:
            b_mm = info["bleed_pt"] / 72 * 25.4
            insufficient_bleed.append(f"p{i + 1}: {b_mm:.2f} mm")

    total_with_bleed = pages_explicit_bleed + pages_implied_bleed

    if pages_no_bleed and total_with_bleed == 0:
        bleed_passed = False
        bleed_detail = (
            'No bleed detected. For full-bleed designs, add at least \u215b" (3 mm) of bleed '
            "and set the bleed and trim markers in your design file."
        )
        bleed_severity = "warning"
    elif pages_explicit_bleed == doc.page_count:
        bleed_passed = True
        bleed_detail = f"Bleed area set on all {doc.page_count} page(s)"
        bleed_severity = "info"
    elif pages_explicit_bleed > 0:
        bleed_passed = False
        bleed_detail = (
            f"Bleed area found on {pages_explicit_bleed}/{doc.page_count} page(s); "
            f"missing on {len(pages_no_bleed)} page(s)"
        )
        bleed_severity = "warning"
    else:
        # Only implied bleed
        bleed_passed = False
        bleed_detail = (
            "Bleed space found in page dimensions, but bleed and trim markers aren't set in the PDF — "
            + "; ".join(implied_details[:3])
        )
        bleed_severity = "info"

    # Bleed, BleedBox and TrimBox warnings are resolved by Download Fixed PDF.

    return checks
