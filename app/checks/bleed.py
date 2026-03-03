import fitz  # PyMuPDF
from typing import List
from .models import CheckItem


# Common standard print sizes in points (width × height, portrait)
STANDARD_SIZES_PT: dict[str, tuple[float, float]] = {
    'Letter (8.5×11")': (612.0, 792.0),
    'Legal (8.5×14")': (612.0, 1008.0),
    'Tabloid (11×17")': (792.0, 1224.0),
    "A4": (595.28, 841.89),
    "A3": (841.89, 1190.55),
    "A5": (419.53, 595.28),
    'Half Letter (5.5×8.5")': (396.0, 612.0),
    'Business Card (3.5×2")': (252.0, 144.0),
}

MIN_BLEED_PT = 2.83  # 1 mm — absolute minimum
REQ_BLEED_PT = 8.50  # 3 mm — industry standard
PT_PER_MM = 2.8346


def _rect_approx_equal(a: fitz.Rect, b: fitz.Rect, tol: float = 2.0) -> bool:
    return (
        abs(a.x0 - b.x0) < tol
        and abs(a.y0 - b.y0) < tol
        and abs(a.x1 - b.x1) < tol
        and abs(a.y1 - b.y1) < tol
    )


def check_bleed(doc: fitz.Document) -> List[CheckItem]:
    checks: List[CheckItem] = []

    pages_with_bleedbox = 0
    pages_with_insufficient_bleed = []
    pages_with_trim = 0

    for i, page in enumerate(doc):
        media = page.mediabox
        trim = page.trimbox
        bleed = page.bleedbox

        if trim:
            pages_with_trim += 1

        if bleed and not _rect_approx_equal(bleed, media):
            pages_with_bleedbox += 1
            ref = trim if trim else media
            left = ref.x0 - bleed.x0
            bottom = ref.y0 - bleed.y0
            right = bleed.x1 - ref.x1
            top = bleed.y1 - ref.y1
            if any(v < MIN_BLEED_PT for v in (left, bottom, right, top)):
                pages_with_insufficient_bleed.append(i + 1)

    # BleedBox presence
    checks.append(
        CheckItem(
            name="BleedBox Defined",
            passed=pages_with_bleedbox > 0,
            detail=(
                f"BleedBox found on {pages_with_bleedbox}/{doc.page_count} page(s)"
                if pages_with_bleedbox
                else "No BleedBox defined — required for full-bleed print jobs"
            ),
            severity="warning",
        )
    )

    # Sufficient bleed extent (only reported when BleedBox exists)
    if pages_with_bleedbox > 0:
        checks.append(
            CheckItem(
                name="Bleed ≥ 1 mm (minimum)",
                passed=len(pages_with_insufficient_bleed) == 0,
                detail=(
                    "All pages with a BleedBox have ≥ 1 mm bleed"
                    if not pages_with_insufficient_bleed
                    else f"Insufficient bleed on page(s): {pages_with_insufficient_bleed[:10]}"
                ),
                severity="warning",
            )
        )

    # TrimBox presence
    checks.append(
        CheckItem(
            name="TrimBox Defined",
            passed=pages_with_trim == doc.page_count,
            detail=(
                "TrimBox defined on all pages"
                if pages_with_trim == doc.page_count
                else f"TrimBox missing on {doc.page_count - pages_with_trim} page(s) — printers need TrimBox for accurate cutting"
            ),
            severity="warning",
        )
    )

    return checks


def check_page_size(doc: fitz.Document) -> List[CheckItem]:
    checks: List[CheckItem] = []
    non_standard_pages: List[str] = []

    for i, page in enumerate(doc):
        w = round(page.mediabox.width, 1)
        h = round(page.mediabox.height, 1)
        matched = any(
            (abs(w - sw) < 2 and abs(h - sh) < 2)
            or (abs(w - sh) < 2 and abs(h - sw) < 2)
            for sw, sh in STANDARD_SIZES_PT.values()
        )
        if not matched:
            non_standard_pages.append(
                f'p{i + 1}: {w:.1f}×{h:.1f} pt ({w / 72:.3f}×{h / 72:.3f}")'
            )

    checks.append(
        CheckItem(
            name="Standard Page Size",
            passed=len(non_standard_pages) == 0,
            detail=(
                "All pages match a standard print size"
                if not non_standard_pages
                else f"Non-standard size(s): {', '.join(non_standard_pages[:5])}"
            ),
            severity="info",
        )
    )

    return checks
