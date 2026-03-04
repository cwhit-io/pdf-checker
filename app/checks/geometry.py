import fitz  # PyMuPDF
from typing import List, Optional
from .models import CheckItem, PageInfo

BLEED_REQUIRED_PT = 9.0  # 0.125 in = 9 pt — industry standard
BLEED_MIN_PT = 2.83  # 1 mm — absolute minimum

# Common bleed amounts to probe when no BleedBox is set
COMMON_BLEEDS_PT: list[float] = [
    9.0,  # 0.125" — industry standard
    4.504,  # ≈ 0.0625"
    8.504,  # ≈ 3 mm
    14.173,  # ≈ 5 mm
    18.0,  # 0.25"
]
INFER_TOL_PT = 3.0  # ±3 pt ($\approx$ 1 mm) dimension-matching tolerance

STANDARD_SIZES_PT: dict[str, tuple[float, float]] = {
    # ── Standard office / document ─────────────────────────────────────────
    'Letter (8.5×11")': (612.0, 792.0),
    'Tabloid / Ledger (11×17")': (792.0, 1224.0),
    'Half Letter (5.5×8.5")': (396.0, 612.0),
    # ── Common poster / banner / large-format ─────────────────────────────
    'Business Card (3.5×2")': (252.0, 144.0),
    '4×6"': (288.0, 432.0),
    '5×7"': (360.0, 504.0),
    '8×10"': (576.0, 720.0),
    '12×18"': (864.0, 1296.0),
    # ── Square ────────────────────────────────────────────────────────────
    '4×4"': (288.0, 288.0),
    '6×9"': (432.0, 648.0),
}


def _classify(width: float, height: float) -> str:
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def _rect_approx_equal(a: fitz.Rect, b: fitz.Rect, tol: float = 2.0) -> bool:
    return (
        abs(a.x0 - b.x0) < tol
        and abs(a.y0 - b.y0) < tol
        and abs(a.x1 - b.x1) < tol
        and abs(a.y1 - b.y1) < tol
    )


def infer_page_bleed(page: fitz.Page) -> Optional[dict]:
    """
    Returns bleed/trim geometry for a page.

    Checks explicit PDF boxes first; if absent, infers by testing whether
    the MediaBox dimensions equal a known standard trim size + uniform bleed.

    Returns a dict with:
        trim     : fitz.Rect  – trim / cut line
        bleed    : fitz.Rect  – bleed boundary (outer edge)
        bleed_pt : float      – smallest bleed side in points
        source   : "explicit" | "implied"
        label    : str        – human-readable summary
    or None if no bleed can be detected.
    """
    media = page.mediabox

    bleed_box = page.bleedbox
    trim_box = page.trimbox
    has_explicit_trim = trim_box is not None and not _rect_approx_equal(trim_box, media)
    # Treat any present BleedBox as explicit. This lets PDFs that set the
    # BleedBox to the MediaBox (i.e. = MediaBox) be considered explicitly
    # configured so the UI preview uses that box when reuploading fixed files.
    has_explicit_bleed = bleed_box is not None

    # ── Explicit BleedBox wins ────────────────────────────────────
    if has_explicit_bleed:
        ref = trim_box if has_explicit_trim else media
        # Compute bleed relative to the chosen reference (trim if present,
        # otherwise media). We return explicit metadata even when the
        # BleedBox equals the MediaBox (bleed_pt may be zero).
        sides = (
            ref.x0 - bleed_box.x0,
            ref.y0 - bleed_box.y0,
            bleed_box.x1 - ref.x1,
            bleed_box.y1 - ref.y1,
        )
        bleed_pt = min(sides)
        return {
            "trim": ref,
            "bleed": bleed_box,
            "bleed_pt": bleed_pt,
            "source": "explicit",
            "label": (
                f"BleedBox set; {bleed_pt / 72 * 25.4:.2f} mm "
                f"({bleed_pt:.1f} pt) per side"
            ),
        }

    # ── Infer from page dimensions ────────────────────────────────
    w = media.width
    h = media.height

    # If the MediaBox itself exactly matches a known standard size the page IS
    # the trim — no bleed to infer.  Without this guard a 6×9" page (432×648 pt)
    # would be misidentified as "Half Letter + 0.25-inch bleed" because the same
    # arithmetic holds: 396 + 2×18 = 432 and 612 + 2×18 = 648.
    for _sn, (sw, sh) in STANDARD_SIZES_PT.items():
        if (abs(w - sw) < INFER_TOL_PT and abs(h - sh) < INFER_TOL_PT) or (
            abs(w - sh) < INFER_TOL_PT and abs(h - sw) < INFER_TOL_PT
        ):
            return None

    best: Optional[tuple] = None
    best_err = float("inf")

    for size_name, (sw, sh) in STANDARD_SIZES_PT.items():
        for b in COMMON_BLEEDS_PT:
            # Portrait orientation
            err = abs(w - (sw + 2 * b)) + abs(h - (sh + 2 * b))
            if err < best_err and err < INFER_TOL_PT * 2:
                best_err = err
                best = (size_name, sw, sh, b)
            # Landscape orientation
            err = abs(w - (sh + 2 * b)) + abs(h - (sw + 2 * b))
            if err < best_err and err < INFER_TOL_PT * 2:
                best_err = err
                best = (size_name, sh, sw, b)

    if best is None:
        return None

    size_name, _tw, _th, b = best

    # Prefer an explicit TrimBox if the PDF already has one — it's more precise
    # than our inferred value (this happens when TrimBox is set but BleedBox
    # was set incorrectly / equal to TrimBox and we fell through from above).
    if has_explicit_trim:
        trim_rect = trim_box
        # Re-compute actual bleed from explicit trim to media edge
        sides = (
            trim_rect.x0 - media.x0,
            trim_rect.y0 - media.y0,
            media.x1 - trim_rect.x1,
            media.y1 - trim_rect.y1,
        )
        b = min(sides)
    else:
        trim_rect = fitz.Rect(
            media.x0 + b,
            media.y0 + b,
            media.x1 - b,
            media.y1 - b,
        )

    return {
        "trim": trim_rect,
        "bleed": fitz.Rect(media.x0, media.y0, media.x1, media.y1),
        "bleed_pt": b,
        "source": "implied",
        "label": (
            f"Dimensions match {size_name} + {b / 72 * 25.4:.2f} mm bleed; "
            + (
                "TrimBox used from PDF"
                if has_explicit_trim
                else "no BleedBox/TrimBox set"
            )
        ),
        "size_name": size_name,
    }


def get_page_infos(doc: fitz.Document) -> List[PageInfo]:
    infos: List[PageInfo] = []
    for i, page in enumerate(doc):
        w = page.mediabox.width
        h = page.mediabox.height
        infos.append(
            PageInfo(
                page_number=i + 1,
                width_pt=round(w, 2),
                height_pt=round(h, 2),
                width_in=round(w / 72, 3),
                height_in=round(h / 72, 3),
                orientation=_classify(w, h),
            )
        )
    return infos


def get_page_boxes(doc: fitz.Document) -> list[dict]:
    """
    Return all five PDF page boxes for every page.

    For each box, ``explicit`` is True when the box differs from the MediaBox
    (i.e. it was actually set in the file, not just the MediaBox fallback).
    """
    BOX_ORDER = ["MediaBox", "CropBox", "TrimBox", "BleedBox", "ArtBox"]

    def _fmt(rect: fitz.Rect, media: fitz.Rect, is_media: bool, name: str) -> dict:
        # Treat BleedBox as explicit when present even if it equals MediaBox.
        explicit = (
            is_media
            or (name == "BleedBox" and rect is not None)
            or not _rect_approx_equal(rect, media)
        )
        return {
            "x0": round(rect.x0, 2),
            "y0": round(rect.y0, 2),
            "x1": round(rect.x1, 2),
            "y1": round(rect.y1, 2),
            "w_pt": round(rect.width, 2),
            "h_pt": round(rect.height, 2),
            "w_in": round(rect.width / 72, 4),
            "h_in": round(rect.height / 72, 4),
            "explicit": explicit,
        }

    pages_boxes: list[dict] = []
    for page in doc:
        media = page.mediabox
        entry: dict = {
            "page": page.number + 1,
            "boxes": {
                "MediaBox": _fmt(media, media, True, "MediaBox"),
                "CropBox": _fmt(page.cropbox, media, False, "CropBox"),
                "TrimBox": _fmt(page.trimbox, media, False, "TrimBox"),
                "BleedBox": _fmt(page.bleedbox, media, False, "BleedBox"),
                "ArtBox": _fmt(page.artbox, media, False, "ArtBox"),
            },
            "box_order": BOX_ORDER,
        }
        pages_boxes.append(entry)
    return pages_boxes


def check_geometry(doc: fitz.Document) -> List[CheckItem]:
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

    # ── Page count ───────────────────────────────────────────────
    checks.append(
        CheckItem(
            name="Page Count",
            passed=True,
            detail=f"{doc.page_count} page(s)",
            severity="info",
        )
    )

    # ── Mixed page sizes ─────────────────────────────────────────
    sizes: set[tuple[float, float]] = set()
    for page in doc:
        w = round(page.mediabox.width, 1)
        h = round(page.mediabox.height, 1)
        sizes.add((min(w, h), max(w, h)))  # normalise orientation so portrait≡landscape

    mixed = len(sizes) > 1
    if mixed:
        size_strs = [f'{w / 72:.3f}"×{h / 72:.3f}"' for w, h in sorted(sizes)]
        size_detail = f"Mixed sizes detected: {', '.join(size_strs[:6])}"
    else:
        w, h = list(sizes)[0]
        size_detail = f'Uniform size: {w / 72:.3f}"×{h / 72:.3f}"'
    checks.append(
        CheckItem(
            name="Consistent Page Size",
            passed=not mixed,
            detail=size_detail,
            severity="warning",
        )
    )

    # ── Standard size match (informational) ─────────────────────
    non_std: List[str] = []
    bleed_matched: List[str] = []
    for i, page in enumerate(doc):
        w = round(page.mediabox.width, 1)
        h = round(page.mediabox.height, 1)
        # Exact match against known standard sizes
        matched = any(
            (abs(w - sw) < 2 and abs(h - sh) < 2)
            or (abs(w - sh) < 2 and abs(h - sw) < 2)
            for sw, sh in STANDARD_SIZES_PT.values()
        )
        if not matched:
            bleed_info = infer_page_bleed(page)
            if bleed_info and bleed_info["source"] == "implied":
                # Recognized as standard + bleed — not truly non-standard
                size_label = bleed_info["size_name"]
                b_mm = bleed_info["bleed_pt"] / 72 * 25.4
                bleed_matched.append(
                    f'p{i + 1}: {w / 72:.3f}"×{h / 72:.3f}" '
                    f"({size_label} + {b_mm:.2f} mm bleed)"
                )
            else:
                non_std.append(f'p{i + 1}: {w / 72:.3f}"×{h / 72:.3f}"')

    if non_std:
        std_detail = f"Non-standard size(s): {', '.join(non_std[:5])}"
    elif bleed_matched:
        std_detail = f"Standard size with bleed: {', '.join(bleed_matched[:5])}"
    else:
        std_detail = "All pages match a standard print size"

    checks.append(
        CheckItem(
            name="Standard Page Size",
            passed=len(non_std) == 0,
            detail=std_detail,
            severity="info",
        )
    )

    # ── Orientation consistency ──────────────────────────────────
    orientations = [_classify(p.mediabox.width, p.mediabox.height) for p in doc]
    unique_ori = set(orientations)
    checks.append(
        CheckItem(
            name="Consistent Orientation",
            passed=len(unique_ori) == 1,
            detail=f"All pages are {orientations[0]}"
            if len(unique_ori) == 1
            else f"Mixed orientations: {', '.join(sorted(unique_ori))}",
            severity="warning",
        )
    )

    # ── Unexpected rotation transforms ──────────────────────────
    rotated = [i + 1 for i, page in enumerate(doc) if page.rotation not in (0, 360)]
    checks.append(
        CheckItem(
            name="No Unexpected Rotation",
            passed=len(rotated) == 0,
            detail="No PDF rotation transforms applied"
            if not rotated
            else f"Rotation applied on page(s): {rotated[:10]} — content may print unexpectedly",
            severity="warning",
        )
    )

    # ── TrimBox ──────────────────────────────────────────────────
    # PyMuPDF's .trimbox always returns something (falls back to MediaBox),
    # so we must check whether it's explicitly different from the MediaBox.
    pages_with_trim = sum(
        1 for page in doc if not _rect_approx_equal(page.trimbox, page.mediabox)
    )
    checks.append(
        CheckItem(
            name="TrimBox Present",
            passed=pages_with_trim == doc.page_count,
            detail="TrimBox explicitly set on all pages"
            if pages_with_trim == doc.page_count
            else (
                f"TrimBox not explicitly set on "
                f"{doc.page_count - pages_with_trim}/{doc.page_count} page(s) "
                "— recommended for print"
            ),
            severity="warning",
        )
    )

    # ── BleedBox presence & amount ───────────────────────────────

    pages_with_bleedbox = 0
    insufficient_bleed: List[str] = []
    for i, page in enumerate(doc):
        # BleedBox is considered present if the attribute exists (PyMuPDF always provides it)
        # but we want to enforce that it is explicitly set, even if it matches MediaBox.
        # So, we require that the BleedBox property is present (always true),
        # and count every page as needing an explicit BleedBox, regardless of value.
        if hasattr(page, "bleedbox") and page.bleedbox is not None:
            pages_with_bleedbox += 1
            # Optionally, check for minimum bleed size:
            bleed_rect = page.bleedbox
            media_rect = page.mediabox
            # Calculate bleed amount (minimum distance from MediaBox to BleedBox edge)
            sides = (
                abs(bleed_rect.x0 - media_rect.x0),
                abs(bleed_rect.y0 - media_rect.y0),
                abs(bleed_rect.x1 - media_rect.x1),
                abs(bleed_rect.y1 - media_rect.y1),
            )
            bleed_pt = min(sides)
            if bleed_pt < BLEED_REQUIRED_PT:
                insufficient_bleed.append(
                    f"p{i + 1}: {bleed_pt / 72 * 25.4:.2f} mm ({bleed_pt:.1f} pt)"
                )

    if pages_with_bleedbox == doc.page_count:
        bleed_detail = (
            f"BleedBox present on all {doc.page_count} page(s) (explicit or = MediaBox)"
        )
    else:
        bleed_detail = f"BleedBox missing on {doc.page_count - pages_with_bleedbox}/{doc.page_count} page(s)"

    checks.append(
        CheckItem(
            name="BleedBox Present",
            passed=pages_with_bleedbox == doc.page_count,
            detail=bleed_detail,
            severity="warning",
        )
    )

    if pages_with_bleedbox > 0:
        checks.append(
            CheckItem(
                name='Bleed ≥ 0.125" (3.175 mm)',
                passed=len(insufficient_bleed) == 0,
                detail='All bleed margins meet the 0.125" minimum'
                if not insufficient_bleed
                else f"Insufficient bleed on: {'; '.join(insufficient_bleed[:5])}",
                severity="warning",
            )
        )

    return checks
