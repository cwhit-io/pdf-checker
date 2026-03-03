import fitz  # PyMuPDF
from typing import List, Tuple
from .models import CheckItem, PageInfo


def _classify(width: float, height: float) -> str:
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


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


def check_orientation(doc: fitz.Document) -> List[CheckItem]:
    checks: List[CheckItem] = []
    page_infos = get_page_infos(doc)

    if not page_infos:
        return checks

    # Consistent orientation across all pages
    orientations = [p.orientation for p in page_infos]
    unique_orientations = set(orientations)
    consistent = len(unique_orientations) == 1

    checks.append(
        CheckItem(
            name="Consistent Page Orientation",
            passed=consistent,
            detail=(
                f"All {len(page_infos)} page(s) are {orientations[0]}"
                if consistent
                else f"Mixed orientations detected: {', '.join(sorted(unique_orientations))}"
            ),
            severity="warning",
        )
    )

    # Unintended page rotation (PDF rotation transform applied on top of content)
    rotated_pages = [i + 1 for i, page in enumerate(doc) if page.rotation != 0]
    checks.append(
        CheckItem(
            name="No Page Rotation Applied",
            passed=len(rotated_pages) == 0,
            detail=(
                "No pages have a PDF rotation transform applied"
                if not rotated_pages
                else f"Page(s) with rotation transform: {rotated_pages[:10]} — content may print unexpectedly"
            ),
            severity="warning",
        )
    )

    return checks
