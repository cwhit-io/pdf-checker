import fitz  # PyMuPDF
from typing import List
from .models import CheckItem


MAX_FILE_SIZE_MB = 100


def check_general(doc: fitz.Document, file_size_bytes: int) -> List[CheckItem]:
    checks: List[CheckItem] = []

    # Allowed page sizes (in inches)
    allowed_sizes = [
        (8.5, 11),
        (4, 6),
        (3.5, 2),
        (4, 4),
        (12, 18),
    ]
    allowed_sizes_set = set(tuple(sorted((w, h))) for w, h in allowed_sizes)
    all_pages_allowed = True
    details = []
    for i in range(doc.page_count):
        page = doc.load_page(i)
        rect = page.rect
        width_in = rect.width / 72
        height_in = rect.height / 72
        size_tuple = tuple(sorted((round(width_in, 2), round(height_in, 2))))
        if size_tuple not in allowed_sizes_set:
            all_pages_allowed = False
            details.append(
                f"Page {i + 1}: {width_in:.2f} x {height_in:.2f} in — not allowed"
            )
        else:
            details.append(
                f"Page {i + 1}: {width_in:.2f} x {height_in:.2f} in — allowed"
            )
    checks.append(
        CheckItem(
            name="Allowed Page Size(s)",
            passed=all_pages_allowed,
            detail="; ".join(details),
            severity="error" if not all_pages_allowed else "info",
        )
    )

    # Password / encryption
    checks.append(
        CheckItem(
            name="Not Password Protected",
            passed=not doc.is_encrypted,
            detail="Document is not password protected"
            if not doc.is_encrypted
            else "Document is encrypted/password protected — cannot be processed by a RIP",
            severity="error",
        )
    )

    # Has at least one page
    checks.append(
        CheckItem(
            name="Has Pages",
            passed=doc.page_count > 0,
            detail=f"Document contains {doc.page_count} page(s)",
            severity="error",
        )
    )

    return checks
