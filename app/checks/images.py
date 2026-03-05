import fitz  # PyMuPDF
from typing import List
from .models import CheckItem

LOW_DPI_ERROR = 150  # Below this: definite problem
LOW_DPI_WARN = 250  # Below this: warn
TARGET_DPI = 300  # Ideal for print

HAIRLINE_PT = 0.25  # Lines thinner than this (0.25 pt ≈ 0.09 mm) are hairlines


def check_images(doc: fitz.Document) -> List[CheckItem]:
    checks: List[CheckItem] = []

    seen_xrefs: set[int] = set()
    total_images = 0
    low_dpi_errors: list[str] = []
    low_dpi_warns: list[str] = []

    for page_num, page in enumerate(doc, 1):
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            total_images += 1

            try:
                img_data = doc.extract_image(xref)
            except Exception:
                continue

            px_w = img_data.get("width", 0)
            px_h = img_data.get("height", 0)
            bpc = img_data.get("bpc", 8)

            # 1-bit lineart is always fine regardless of DPI
            if bpc == 1:
                continue

            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []

            for rect in rects:
                placed_w_in = rect.width / 72
                placed_h_in = rect.height / 72
                if placed_w_in <= 0 or placed_h_in <= 0:
                    continue

                eff_dpi = min(px_w / placed_w_in, px_h / placed_h_in)
                label = f"p{page_num}: {px_w}x{px_h}px @ {eff_dpi:.0f} dpi"

                if eff_dpi < LOW_DPI_ERROR:
                    low_dpi_errors.append(label)
                elif eff_dpi < LOW_DPI_WARN:
                    low_dpi_warns.append(label)

    if total_images == 0:
        checks.append(
            CheckItem(
                name="Image Resolution",
                passed=True,
                detail="No embedded photos or images found",
                severity="info",
            )
        )
        return checks

    # ── Low DPI errors ────────────────────────────────────────────────────
    if low_dpi_errors:
        checks.append(
            CheckItem(
                name=f"Low Resolution ({len(low_dpi_errors)} image{'s' if len(low_dpi_errors) > 1 else ''})",
                passed=False,
                detail=f"Very low resolution (below {LOW_DPI_ERROR} dpi) — will look blurry when printed: "
                + "; ".join(low_dpi_errors[:4])
                + (" …" if len(low_dpi_errors) > 4 else ""),
                severity="error",
            )
        )

    # ── Below recommended ─────────────────────────────────────────────────
    if low_dpi_warns:
        checks.append(
            CheckItem(
                name=f"Below Recommended Resolution ({len(low_dpi_warns)} image{'s' if len(low_dpi_warns) > 1 else ''})",
                passed=False,
                detail=f"Below the recommended {LOW_DPI_WARN} dpi for print: "
                + "; ".join(low_dpi_warns[:4])
                + (" …" if len(low_dpi_warns) > 4 else ""),
                severity="warning",
            )
        )

    # ── All clear ─────────────────────────────────────────────────────────
    if not low_dpi_errors and not low_dpi_warns:
        checks.append(
            CheckItem(
                name=f"Image Resolution ({total_images} image{'s' if total_images > 1 else ''})",
                passed=True,
                detail=f"All {total_images} image(s) have good resolution for print",
                severity="info",
            )
        )

    # ── Hairline detection ────────────────────────────────────────────────
    hairline_pages: list[str] = []
    for page_num, page in enumerate(doc, 1):
        try:
            drawings = page.get_drawings()
        except Exception:
            continue
        for d in drawings:
            stroke_w = d.get("width", None)
            if stroke_w is not None and 0 < stroke_w < HAIRLINE_PT:
                hairline_pages.append(f"p{page_num} ({stroke_w:.3f} pt)")
                break  # one per page is enough

    if hairline_pages:
        checks.append(
            CheckItem(
                name=f"Hairline Strokes ({len(hairline_pages)} page{'s' if len(hairline_pages) > 1 else ''})",
                passed=False,
                detail=(
                    f"Lines thinner than {HAIRLINE_PT} pt found on: "
                    + ", ".join(hairline_pages[:6])
                    + (" …" if len(hairline_pages) > 6 else "")
                    + " — may disappear or print unevenly"
                ),
                severity="warning",
            )
        )
    else:
        checks.append(
            CheckItem(
                name="Hairline Strokes",
                passed=True,
                detail=f"No strokes thinner than {HAIRLINE_PT} pt detected",
                severity="info",
            )
        )

    return checks
