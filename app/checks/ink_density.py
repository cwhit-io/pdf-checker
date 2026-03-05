"""
ink_density.py — Total Area Coverage (TAC / TIC) checks.

Estimates per-pixel ink coverage for rasterised PDF page thumbnails to flag
pages that exceed common press limits (typically 240–320%).

Method:
  • Render each page to a small bitmap using PyMuPDF.
  • For every pixel, estimate CMYK ink load.
    – If the page uses DeviceRGB we convert via a simple RGB→CMYK approximation.
    – If the page is CMYK-native we use the rendered values directly (approximate
      because PyMuPDF renders to RGB; a full CMM would be needed for accuracy).
  • Report the maximum and average TAC found, and which pages exceed the limit.

Note: This is an *estimate* — accurate TAC requires a full colour-managed
conversion pipeline (e.g. Ghostscript + an output ICC profile). Use this
as a quick first-pass screening tool.
"""

import fitz  # PyMuPDF
from typing import List
from .models import CheckItem

TAC_LIMIT_DEFAULT = 300  # percent — common sheetfed offset limit
TAC_WARN_OFFSET = 20  # warn when within 20 % of limit
RENDER_SCALE = 0.1  # 10 % of full res — sufficient for coverage estimate


def _rgb_to_cmyk_approx(r: float, g: float, b: float):
    """Very rough sRGB to CMYK conversion (no ICC) yielding 0–1 floats."""
    if r == 0 and g == 0 and b == 0:
        return 0.0, 0.0, 0.0, 1.0
    k = 1.0 - max(r, g, b)
    d = 1.0 - k
    if d == 0:
        return 0.0, 0.0, 0.0, 1.0
    c = (1.0 - r - k) / d
    m = (1.0 - g - k) / d
    y = (1.0 - b - k) / d
    return c, m, y, k


def check_ink_density(
    doc: fitz.Document, tac_limit: int = TAC_LIMIT_DEFAULT
) -> List[CheckItem]:
    checks: List[CheckItem] = []

    over_limit_pages: list[str] = []
    warn_pages: list[str] = []
    max_tac_overall = 0.0

    clip_mat = fitz.Matrix(RENDER_SCALE, RENDER_SCALE)

    for i, page in enumerate(doc):
        page_num = i + 1
        try:
            pix = page.get_pixmap(matrix=clip_mat, colorspace=fitz.csRGB, alpha=False)
        except Exception:
            continue

        samples = pix.samples  # bytes: R G B R G B …
        width, height = pix.width, pix.height
        if width == 0 or height == 0:
            continue

        total_pixels = width * height
        sum_tac = 0.0
        max_tac_page = 0.0

        for idx in range(total_pixels):
            r = samples[idx * 3] / 255.0
            g = samples[idx * 3 + 1] / 255.0
            b = samples[idx * 3 + 2] / 255.0
            c, m, y, k = _rgb_to_cmyk_approx(r, g, b)
            tac = (c + m + y + k) * 100.0
            sum_tac += tac
            if tac > max_tac_page:
                max_tac_page = tac

        avg_tac = sum_tac / total_pixels if total_pixels else 0.0

        if max_tac_page > max_tac_overall:
            max_tac_overall = max_tac_page

        label = f"p{page_num} (max {max_tac_page:.0f}%, avg {avg_tac:.0f}%)"
        if max_tac_page > tac_limit:
            over_limit_pages.append(label)
        elif max_tac_page > tac_limit - TAC_WARN_OFFSET:
            warn_pages.append(label)

    tac_limit_pct = tac_limit

    if over_limit_pages:
        checks.append(
            CheckItem(
                name=f"Ink Density > {tac_limit_pct}% TAC",
                passed=False,
                detail=(
                    f"Page(s) exceed {tac_limit_pct}% total area coverage (estimated): "
                    + "; ".join(over_limit_pages[:4])
                    + (" …" if len(over_limit_pages) > 4 else "")
                    + " — risk of ink trapping / slow drying on press"
                ),
                severity="error",
            )
        )
    elif warn_pages:
        checks.append(
            CheckItem(
                name=f"Ink Density Near Limit ({tac_limit_pct}% TAC)",
                passed=True,
                detail=(
                    f"Page(s) approaching {tac_limit_pct}% TAC (estimated): "
                    + "; ".join(warn_pages[:4])
                    + (" …" if len(warn_pages) > 4 else "")
                ),
                severity="warning",
            )
        )
    else:
        label = f"{max_tac_overall:.0f}%" if max_tac_overall > 0 else "N/A"
        checks.append(
            CheckItem(
                name=f"Ink Density ≤ {tac_limit_pct}% TAC",
                passed=True,
                detail=f"Estimated maximum TAC: {label} (within {tac_limit_pct}% limit)",
                severity="info",
            )
        )

    return checks
