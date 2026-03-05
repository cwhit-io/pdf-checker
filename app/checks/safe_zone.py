import fitz  # PyMuPDF
from typing import List
from .models import CheckItem
from .geometry import infer_page_bleed, _rect_approx_equal

SAFE_ZONE_MARGIN_IN = 0.25  # 0.25" inset from the trim edge


def _parse_preset_trim(preset_trim: str) -> tuple[float, float] | None:
    if not preset_trim:
        return None
    try:
        w_str, h_str = preset_trim.split(",", 1)
        w_in, h_in = float(w_str), float(h_str)
        if w_in > 0 and h_in > 0:
            return w_in * 72.0, h_in * 72.0
    except Exception:
        pass
    return None


def _trim_rect_for_page(
    page: fitz.Page, preset_w_pt: float | None, preset_h_pt: float | None
) -> fitz.Rect | None:
    """Return the best available trim rect for safe-zone measurement.

    Priority:
      1. User-confirmed preset size (centered on mediabox)
      2. Explicit TrimBox / CropBox in the PDF
      3. Inferred trim from bleed geometry
    Returns None if nothing reliable is known.
    """
    media = page.mediabox

    if preset_w_pt is not None and preset_h_pt is not None:
        # Centre the trim rect on the media box
        cx = (media.x0 + media.x1) / 2
        cy = (media.y0 + media.y1) / 2
        # Respect portrait/landscape of the media box
        mw = media.width
        mh = media.height
        if (mw >= mh) == (preset_w_pt >= preset_h_pt):
            tw, th = preset_w_pt, preset_h_pt
        else:
            tw, th = preset_h_pt, preset_w_pt
        return fitz.Rect(cx - tw / 2, cy - th / 2, cx + tw / 2, cy + th / 2)

    # Explicit PDF boxes
    trim_box = page.trimbox
    if trim_box is not None and not _rect_approx_equal(trim_box, media):
        return trim_box
    crop_box = page.cropbox
    if crop_box is not None and not _rect_approx_equal(crop_box, media):
        return crop_box

    # Inferred from bleed geometry (only if PDF actually has a distinct BleedBox)
    bleed_info = infer_page_bleed(page)
    if bleed_info is not None and bleed_info.get("source") == "explicit":
        trim = bleed_info["trim"]
        # Only use the inferred trim if it's meaningfully inside the MediaBox,
        # i.e. the PDF genuinely has a BleedBox that is larger than the trim.
        if not _rect_approx_equal(trim, page.mediabox):
            return trim

    return None


def check_safe_zone(doc: fitz.Document, preset_trim: str = "") -> List[CheckItem]:
    checks: List[CheckItem] = []
    violations: list[str] = []
    margin_pt = SAFE_ZONE_MARGIN_IN * 72

    parsed = _parse_preset_trim(preset_trim)
    preset_w_pt = parsed[0] if parsed else None
    preset_h_pt = parsed[1] if parsed else None

    # Check at least page 1 to see whether we can determine a trim rect
    first_ref = (
        _trim_rect_for_page(doc[0], preset_w_pt, preset_h_pt)
        if doc.page_count
        else None
    )
    if first_ref is None:
        checks.append(
            CheckItem(
                name="Safe Zone",
                passed=True,
                detail="Select a trim size above to validate safe zone margins.",
                severity="info",
            )
        )
        return checks

    for i, page in enumerate(doc):
        ref = _trim_rect_for_page(page, preset_w_pt, preset_h_pt)
        if ref is None:
            ref = page.mediabox

        safe_x0 = ref.x0 + margin_pt
        safe_y0 = ref.y0 + margin_pt
        safe_x1 = ref.x1 - margin_pt
        safe_y1 = ref.y1 - margin_pt

        for block in page.get_text("blocks"):
            x0, y0, x1, y1 = block[:4]
            text_sample = (block[4] if len(block) > 4 else "").strip()[:40]
            if not text_sample:
                continue
            if x0 < safe_x0 or y0 < safe_y0 or x1 > safe_x1 or y1 > safe_y1:
                # Find the most-violated edge (largest positive value = worst overshoot)
                offending_edge = max(
                    (
                        (safe_x0 - x0, "left"),
                        (safe_y0 - y0, "top"),
                        (x1 - safe_x1, "right"),
                        (y1 - safe_y1, "bottom"),
                    ),
                    key=lambda t: t[0],
                )
                dist_pt = offending_edge[0]
                edge = offending_edge[1]
                violations.append(
                    f'p{i + 1} ({edge}): "{text_sample}" — '
                    f"{dist_pt / 72 * 25.4:.1f} mm from safe edge"
                )

    checks.append(
        CheckItem(
            name="Safe Zone",
            passed=len(violations) == 0,
            detail="All text is safely away from the cut edge"
            if not violations
            else f"{len(violations)} text block(s) too close to the cut edge: "
            + "; ".join(violations[:4])
            + (" …" if len(violations) > 4 else ""),
            severity="warning" if violations else "info",
        )
    )
    return checks
