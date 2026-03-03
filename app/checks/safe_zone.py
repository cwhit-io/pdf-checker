import fitz  # PyMuPDF
from typing import List
from .models import CheckItem
from .geometry import infer_page_bleed, _rect_approx_equal

SAFE_ZONE_MARGIN_IN = 0.25  # 0.25" inset from the trim edge


def check_safe_zone(doc: fitz.Document) -> List[CheckItem]:
    checks: List[CheckItem] = []
    violations: list[str] = []
    margin_pt = SAFE_ZONE_MARGIN_IN * 72

    for i, page in enumerate(doc):
        # Use inferred trim rect so the safe zone is measured from the
        # actual cut line, not raw media edge (handles implied-bleed files)
        bleed_info = infer_page_bleed(page)
        if bleed_info is not None:
            ref = bleed_info["trim"]
        else:
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
                # Report the nearest edge
                offending_edge = min(
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
