import fitz  # PyMuPDF
from typing import List
from .models import CheckItem

MAX_FILE_SIZE_MB = 500
SUPPORTED_VERSION = 1.7
# PDF permission bit positions (PDF spec)
_PERM_PRINT = 1 << 2  # bit 3
_PERM_COPY = 1 << 4  # bit 5


def check_security(doc: fitz.Document, file_size_bytes: int) -> List[CheckItem]:
    checks: List[CheckItem] = []

    # ── File size ───────────────────────────────────────────────
    size_mb = file_size_bytes / (1024 * 1024)
    checks.append(
        CheckItem(
            name="File Size",
            passed=size_mb <= MAX_FILE_SIZE_MB,
            detail=f"{size_mb:.2f} MB{f' — exceeds {MAX_FILE_SIZE_MB} MB limit' if size_mb > MAX_FILE_SIZE_MB else ''}",
            severity="warning",
        )
    )

    # ── Encryption ──────────────────────────────────────────────
    checks.append(
        CheckItem(
            name="Not Encrypted",
            passed=not doc.is_encrypted,
            detail=(
                "File is not password-protected"
                if not doc.is_encrypted
                else "File is password-protected — Fiery may not be able to open it"
            ),
            severity="error",
        )
    )

    # ── Print permission ────────────────────────────────────────
    # Unencrypted docs return -1 or large int (all bits set)
    perm = doc.permissions
    can_print = (not doc.is_encrypted) or bool(perm & _PERM_PRINT)
    checks.append(
        CheckItem(
            name="Print Permission Allowed",
            passed=can_print,
            detail=(
                "Printing is permitted"
                if can_print
                else "Printing is restricted — Fiery may refuse this job"
            ),
            severity="error",
        )
    )

    # ── Copy permission (informational) ─────────────────────────
    can_copy = (not doc.is_encrypted) or bool(perm & _PERM_COPY)
    checks.append(
        CheckItem(
            name="Copy Permission",
            passed=can_copy,
            detail="Copy/extract permission is enabled"
            if can_copy
            else "Copy permission is disabled",
            severity="info",
        )
    )

    # ── PDF version ─────────────────────────────────────────────
    metadata = doc.metadata or {}
    pdf_format = (metadata.get("format") or "").strip()  # e.g. "PDF 1.7"
    try:
        ver = float(pdf_format.replace("PDF ", "").replace("PDF-", "").strip())
    except (ValueError, AttributeError):
        ver = 0.0
    version_ok = 0.0 < ver <= SUPPORTED_VERSION
    checks.append(
        CheckItem(
            name="PDF Version ≤ 1.7",
            passed=version_ok,
            detail=f"Version: {pdf_format or 'unknown'}",
            severity="warning",
        )
    )

    return checks

    return checks
