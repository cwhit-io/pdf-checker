import re
import fitz  # PyMuPDF
from typing import List
from .models import CheckItem

MAX_FILE_SIZE_MB = 500
SUPPORTED_VERSION = 1.7
# PDF permission bit positions (PDF spec)
_PERM_PRINT = 1 << 2  # bit 3
_PERM_COPY = 1 << 4  # bit 5
_PERM_MODIFY = 1 << 3  # bit 4


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

    # ── Modification permission ─────────────────────────────────
    can_modify = (not doc.is_encrypted) or bool(perm & _PERM_MODIFY)
    checks.append(
        CheckItem(
            name="Modification Permission",
            passed=True,
            detail="Modification allowed"
            if can_modify
            else "Modification restricted (informational)",
            severity="info",
        )
    )

    # ── PDF version ─────────────────────────────────────────────
    metadata = doc.metadata or {}
    pdf_format = (metadata.get("format") or "").strip()
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

    # ── Digital signatures ──────────────────────────────────────
    sig_count = 0
    try:
        for page in doc:
            for widget in page.widgets() or []:
                if (
                    hasattr(widget, "field_type")
                    and widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE
                ):
                    sig_count += 1
    except Exception:
        pass

    checks.append(
        CheckItem(
            name="Digital Signatures",
            passed=sig_count == 0,
            detail=(
                "No digital signature fields found"
                if sig_count == 0
                else f"{sig_count} digital signature field(s) — verify signatures before printing"
            ),
            severity="warning" if sig_count > 0 else "info",
        )
    )

    # ── Hidden layers (OCG) ─────────────────────────────────────
    hidden_layers: list[str] = []
    try:
        ocgs = doc.get_ocgs()
        if ocgs:
            for xref, info in ocgs.items():
                state = info.get("state", "")
                if state == "OFF":
                    hidden_layers.append(info.get("name", f"layer {xref}"))
    except Exception:
        pass

    checks.append(
        CheckItem(
            name="Hidden Layers",
            passed=len(hidden_layers) == 0,
            detail=(
                "No hidden optional content layers"
                if not hidden_layers
                else f"Hidden layer(s): {', '.join(hidden_layers[:6])} — may contain content not intended for print"
            ),
            severity="warning" if hidden_layers else "info",
        )
    )

    # ── Document-level actions ──────────────────────────────────
    has_open_action = False
    try:
        for xref in range(1, doc.xref_length()):
            try:
                obj = doc.xref_object(xref, compressed=False)
            except Exception:
                continue
            if "/OpenAction" in obj or "/AA" in obj:
                has_open_action = True
                break
    except Exception:
        pass

    checks.append(
        CheckItem(
            name="Document Actions",
            passed=not has_open_action,
            detail=(
                "No automatic document-level actions detected"
                if not has_open_action
                else "OpenAction or additional-actions (AA) detected — may run scripts on open"
            ),
            severity="warning" if has_open_action else "info",
        )
    )

    return checks
