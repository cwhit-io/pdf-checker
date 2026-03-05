"""
metadata.py — Document metadata and structure checks.

Covers:
  - Title, Author, Creator, Producer in DocInfo
  - XMP metadata presence
  - PDF/X and PDF/A OutputIntent
  - JavaScript presence (security / print-workflow concern)
  - Interactive form fields
  - Document-level JavaScript actions
"""

import re
import fitz  # PyMuPDF
from typing import List
from .models import CheckItem


def check_metadata(doc: fitz.Document) -> List[CheckItem]:
    checks: List[CheckItem] = []

    metadata = doc.metadata or {}

    # ── Title / Author ─────────────────────────────────────────────────────
    title = (metadata.get("title") or "").strip()
    author = (metadata.get("author") or "").strip()
    creator = (metadata.get("creator") or "").strip()
    producer = (metadata.get("producer") or "").strip()

    checks.append(
        CheckItem(
            name="Document Title",
            passed=bool(title),
            detail=f"Title: {title}" if title else "No document title set in metadata",
            severity="info",
        )
    )

    checks.append(
        CheckItem(
            name="Document Author",
            passed=bool(author),
            detail=f"Author: {author}" if author else "No author set in metadata",
            severity="info",
        )
    )

    checks.append(
        CheckItem(
            name="Creator / Producer",
            passed=True,
            detail=(
                f"Created by: {creator or '(not set)'}; "
                f"Producer: {producer or '(not set)'}"
            ),
            severity="info",
        )
    )

    # ── XMP metadata ──────────────────────────────────────────────────────
    has_xmp = False
    try:
        xmp = doc.get_xml_metadata()
        has_xmp = bool(xmp and xmp.strip())
    except Exception:
        pass

    checks.append(
        CheckItem(
            name="XMP Metadata",
            passed=has_xmp,
            detail="XMP metadata packet present"
            if has_xmp
            else "No XMP metadata found",
            severity="info",
        )
    )

    # ── JavaScript detection ──────────────────────────────────────────────
    has_js = False
    js_locations: list[str] = []

    for xref in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(xref, compressed=False)
        except Exception:
            continue

        if "/JavaScript" in obj or "/JS" in obj:
            has_js = True
            js_locations.append(f"xref {xref}")
            if len(js_locations) >= 5:
                break

    checks.append(
        CheckItem(
            name="No JavaScript",
            passed=not has_js,
            detail=(
                "No JavaScript found"
                if not has_js
                else f"JavaScript detected ({len(js_locations)} location(s)) — "
                "may be stripped or blocked by RIP/workflow"
            ),
            severity="warning" if has_js else "info",
        )
    )

    # ── Interactive form fields ───────────────────────────────────────────
    has_forms = False
    field_count = 0
    try:
        for page in doc:
            widgets = list(page.widgets())
            field_count += len(widgets)
        has_forms = field_count > 0
    except Exception:
        pass

    checks.append(
        CheckItem(
            name="Form Fields",
            passed=not has_forms,
            detail=(
                "No interactive form fields"
                if not has_forms
                else f"{field_count} form field(s) found — flatten before printing"
            ),
            severity="warning" if has_forms else "info",
        )
    )

    # ── OutputIntent (PDF/X or PDF/A) ─────────────────────────────────────
    has_output_intent = False
    output_intent_info = ""
    try:
        for xref in range(1, doc.xref_length()):
            try:
                obj = doc.xref_object(xref, compressed=False)
            except Exception:
                continue
            if "/OutputIntent" in obj or "/GTS_PDFX" in obj or "/GTS_PDFA1" in obj:
                has_output_intent = True
                # Extract S key value for type identification
                s_match = re.search(r"/S\s+/(\S+)", obj)
                if s_match:
                    output_intent_info = s_match.group(1)
                break
    except Exception:
        pass

    checks.append(
        CheckItem(
            name="OutputIntent",
            passed=True,
            detail=(
                f"OutputIntent found: {output_intent_info or 'yes'}"
                if has_output_intent
                else "No OutputIntent — add one for PDF/X compliance"
            ),
            severity="info",
        )
    )

    # ── Embedded attachments ──────────────────────────────────────────────
    has_attachments = False
    attachment_count = 0
    try:
        attachment_count = len(doc.embfile_names())
        has_attachments = attachment_count > 0
    except Exception:
        pass

    checks.append(
        CheckItem(
            name="Embedded Attachments",
            passed=not has_attachments,
            detail=(
                "No embedded file attachments"
                if not has_attachments
                else f"{attachment_count} embedded attachment(s) — may be unintentional"
            ),
            severity="info" if not has_attachments else "warning",
        )
    )

    return checks
