import re
import fitz  # PyMuPDF
from typing import List
from .models import CheckItem

VECTOR_COMPLEXITY_THRESHOLD = 5_000  # drawing objects per page


def check_transparency(doc: fitz.Document) -> List[CheckItem]:
    checks: List[CheckItem] = []

    has_transparency = False
    non_normal_blends: set[str] = set()
    has_soft_mask = False
    has_layers = False
    heavy_pages: List[int] = []

    # ── OCG / Optional Content Groups (layers) ───────────────────
    try:
        ocgs = doc.get_ocgs()
        has_layers = bool(ocgs)
        layer_count = len(ocgs) if ocgs else 0
    except Exception:
        layer_count = 0

    # ── Scan xref objects for transparency-related keys ──────────
    for xref in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(xref, compressed=False)
        except Exception:
            continue

        # Soft mask (alpha channels)
        sm_match = re.search(r"/SMask\s+/(\w+)", obj)
        if "/SMask" in obj and (not sm_match or sm_match.group(1) != "None"):
            has_soft_mask = True

        # Blend modes other than Normal / Compatible
        for m in re.finditer(r"/BM\s*/(\w+)", obj):
            bm = m.group(1)
            if bm not in ("Normal", "Compatible"):
                non_normal_blends.add(bm)

        # Opacity < 1 in graphics states
        for key in ("/ca ", "/CA "):
            if key in obj:
                m = re.search(rf"{re.escape(key.strip())}\s+([\d.]+)", obj)
                if m:
                    try:
                        if float(m.group(1)) < 1.0:
                            has_transparency = True
                    except ValueError:
                        pass

    # ── Per-page drawing inspection ──────────────────────────────
    for i, page in enumerate(doc):
        try:
            drawings = page.get_drawings()
        except Exception:
            continue

        if len(drawings) > VECTOR_COMPLEXITY_THRESHOLD:
            heavy_pages.append(i + 1)

        for d in drawings:
            if d.get("opacity", 1.0) < 1.0:
                has_transparency = True
            bm = (d.get("blend_mode") or "Normal").strip()
            if bm and bm not in ("Normal", "Compatible"):
                non_normal_blends.add(bm)

    # ── Results ──────────────────────────────────────────────────

    checks.append(
        CheckItem(
            name="Transparency",
            passed=True,
            detail=(
                "Transparency detected — confirm flattening settings in Fiery"
                if has_transparency
                else "No transparency detected"
            ),
            severity="warning" if has_transparency else "info",
        )
    )

    checks.append(
        CheckItem(
            name="Blend Modes",
            passed=len(non_normal_blends) == 0,
            detail="All blend modes are Normal"
            if not non_normal_blends
            else f"Non-Normal blend mode(s): {', '.join(sorted(non_normal_blends))} — verify flattening",
            severity="warning",
        )
    )

    checks.append(
        CheckItem(
            name="Soft Masks / Alpha",
            passed=not has_soft_mask,
            detail="No soft masks or alpha channels found"
            if not has_soft_mask
            else "Soft mask(s) / alpha channel(s) present — transparency flattening required",
            severity="warning",
        )
    )

    # ...removed Layers (OCG) check for volunteer workflow...

    checks.append(
        CheckItem(
            name="Page Vector Complexity",
            passed=len(heavy_pages) == 0,
            detail=(
                "All pages within normal vector complexity bounds"
                if not heavy_pages
                else f"High vector object count (>{VECTOR_COMPLEXITY_THRESHOLD:,}) on page(s): {heavy_pages[:5]} — may slow Fiery processing"
            ),
            severity="warning",
        )
    )

    return checks
