"""
Bleed & Trim checks.

Reuses infer_page_bleed() from geometry.py for all bleed/trim detection
so the same logic drives both checks and the visual preview overlay.
"""

import fitz  # PyMuPDF
from typing import List
from .models import CheckItem
from .geometry import (
    _rect_approx_equal,
    BLEED_REQUIRED_PT,
)


SIZE_TOL_PT = 1.5
BLEED_TOL_PT = 1.0


def _parse_preset_trim(preset_trim: str) -> tuple[float, float] | None:
    if not preset_trim:
        return None
    try:
        w_str, h_str = preset_trim.split(",", 1)
        w_in = float(w_str)
        h_in = float(h_str)
        if w_in > 0 and h_in > 0:
            return w_in * 72.0, h_in * 72.0
    except Exception:
        return None
    return None


def _dims_match(rect: fitz.Rect, target_w_pt: float, target_h_pt: float) -> bool:
    w = rect.width
    h = rect.height
    return (
        abs(w - target_w_pt) <= SIZE_TOL_PT and abs(h - target_h_pt) <= SIZE_TOL_PT
    ) or (abs(w - target_h_pt) <= SIZE_TOL_PT and abs(h - target_w_pt) <= SIZE_TOL_PT)


def check_bleed_trim(doc: fitz.Document, preset_trim: str = "") -> List[CheckItem]:
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

    target = _parse_preset_trim(preset_trim)
    if target is None:
        checks.append(
            CheckItem(
                name="Destination Size Selected",
                passed=False,
                detail="Select an intended trim size to validate Trim/Crop and BleedBox (.125 in).",
                severity="warning",
            )
        )
        return checks

    target_w_pt, target_h_pt = target
    checks.append(
        CheckItem(
            name="Destination Size Selected",
            passed=True,
            detail=f'Target trim: {target_w_pt / 72:.3f}" × {target_h_pt / 72:.3f}"',
            severity="info",
        )
    )

    pages_missing_trim_crop: list[int] = []
    pages_wrong_trim_crop: list[str] = []
    pages_missing_bleed: list[int] = []
    pages_wrong_bleed: list[str] = []

    for i, page in enumerate(doc):
        page_num = i + 1
        media = page.mediabox

        trim_box = page.trimbox
        has_trim = trim_box is not None and not _rect_approx_equal(trim_box, media)

        crop_box = page.cropbox
        has_crop = crop_box is not None and not _rect_approx_equal(crop_box, media)

        if has_trim:
            ref_box = trim_box
        elif has_crop:
            ref_box = crop_box
        else:
            pages_missing_trim_crop.append(page_num)
            continue

        if not _dims_match(ref_box, target_w_pt, target_h_pt):
            pages_wrong_trim_crop.append(
                f'p{page_num}: {ref_box.width / 72:.3f}"×{ref_box.height / 72:.3f}"'
            )

        bleed_box = page.bleedbox
        has_bleed = bleed_box is not None and not _rect_approx_equal(bleed_box, media)
        if not has_bleed:
            pages_missing_bleed.append(page_num)
            continue

        sides = (
            ref_box.x0 - bleed_box.x0,
            ref_box.y0 - bleed_box.y0,
            bleed_box.x1 - ref_box.x1,
            bleed_box.y1 - ref_box.y1,
        )
        if any(side <= 0 for side in sides):
            pages_wrong_bleed.append(f"p{page_num}: BleedBox not outside Trim/Crop")
            continue

        min_bleed = min(sides)
        if abs(min_bleed - BLEED_REQUIRED_PT) > BLEED_TOL_PT:
            pages_wrong_bleed.append(f'p{page_num}: {min_bleed / 72:.3f}" bleed')

    failures = (
        len(pages_missing_trim_crop)
        + len(pages_wrong_trim_crop)
        + len(pages_missing_bleed)
        + len(pages_wrong_bleed)
    )

    if failures == 0:
        checks.append(
            CheckItem(
                name="Trim / Bleed Matches Destination",
                passed=True,
                detail=(
                    f"All {doc.page_count} page(s): Trim/Crop matches selected size and "
                    f'BleedBox is .125" per side'
                ),
                severity="info",
            )
        )
    else:
        detail_parts: list[str] = []
        if pages_missing_trim_crop:
            detail_parts.append(
                "missing Trim/Crop on "
                + ", ".join(f"p{p}" for p in pages_missing_trim_crop[:6])
            )
        if pages_wrong_trim_crop:
            detail_parts.append("size mismatch " + "; ".join(pages_wrong_trim_crop[:4]))
        if pages_missing_bleed:
            detail_parts.append(
                "missing BleedBox on "
                + ", ".join(f"p{p}" for p in pages_missing_bleed[:6])
            )
        if pages_wrong_bleed:
            detail_parts.append("bleed mismatch " + "; ".join(pages_wrong_bleed[:4]))

        checks.append(
            CheckItem(
                name="Trim / Bleed Matches Destination",
                passed=False,
                detail="; ".join(detail_parts),
                severity="warning",
            )
        )

    return checks
