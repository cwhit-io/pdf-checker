"""
fix_pdf.py — utilities for detecting page geometry and producing a corrected PDF.

Provides:
  detect_print_geometry(doc)  – infer intended trim/bleed from any PDF page
  build_fixed_pdf(...)        – set TrimBox/BleedBox and optionally convert to CMYK
  GS_AVAILABLE                – bool, True when Ghostscript is on PATH
  FORM_SIZES                  – list of (label, w_in, h_in) for the UI dropdown
  BLEED_PT                    – standard 1/8" bleed in points (9.0)
"""

import io
import os
import shutil
import subprocess
import tempfile

import fitz  # PyMuPDF

from .checks.geometry import (
    INFER_TOL_PT,
    STANDARD_SIZES_PT,
    infer_page_bleed,
    _rect_approx_equal,
)

# ── Ghostscript ────────────────────────────────────────────────────────────
GS_BINARY: str | None = (
    shutil.which("gs") or shutil.which("gswin64c") or shutil.which("gswin32c")
)
GS_AVAILABLE: bool = GS_BINARY is not None

# ── UI constants ───────────────────────────────────────────────────────────

# (label, w_in, h_in)  — w_in=0 means "Custom"
FORM_SIZES: list[tuple[str, float, float]] = [
    ('Business Card (3.5×2")', 3.5, 2.0),
    ('4×6"', 4.0, 6.0),
    ('5×7"', 5.0, 7.0),
    ('5×8"', 5.0, 8.0),
    ('5.5×8.5" (Half Letter)', 5.5, 8.5),
    ('6×9"', 6.0, 9.0),
    ('8×10"', 8.0, 10.0),
    ('8.5×11" (Letter)', 8.5, 11.0),
    ('11×17" (Tabloid)', 11.0, 17.0),
    ('12×18"', 12.0, 18.0),
]

_PT_PER_MM = 72.0 / 25.4

BLEED_PT: float = 9.0  # always 1/8" bleed


# ── Geometry detection ─────────────────────────────────────────────────────


def _match_size_name(w_pt: float, h_pt: float) -> str:
    for sn, (sw, sh) in STANDARD_SIZES_PT.items():
        if (abs(w_pt - sw) < INFER_TOL_PT and abs(h_pt - sh) < INFER_TOL_PT) or (
            abs(w_pt - sh) < INFER_TOL_PT and abs(h_pt - sw) < INFER_TOL_PT
        ):
            return sn
    return "Custom"


def detect_print_geometry(doc: fitz.Document) -> dict:
    """
    Analyse the first page and return a dict describing the intended trim size.

    Keys:
        trim_w_in / trim_h_in   – trim dimensions in inches
        trim_w_pt / trim_h_pt   – trim dimensions in points
        bleed_pt                – bleed per side in points (0 if none)
        bleed_mm                – bleed in mm
        size_name               – matched standard name or "Custom"
        source                  – "explicit_trim" | "standard_exact" |
                                  "implied_bleed" | "custom"
        note                    – human-readable explanation
    """
    if doc.page_count == 0:
        return {
            "trim_w_in": 0,
            "trim_h_in": 0,
            "trim_w_pt": 0,
            "trim_h_pt": 0,
            "bleed_pt": 0,
            "bleed_mm": 0,
            "size_name": "Unknown",
            "source": "custom",
            "note": "No pages in document",
        }

    page = doc[0]
    media = page.mediabox
    trim_box = page.trimbox
    bleed_box = page.bleedbox
    has_explicit_trim = trim_box is not None and not _rect_approx_equal(trim_box, media)
    has_explicit_bleed = bleed_box is not None and not _rect_approx_equal(
        bleed_box, media
    )

    # 1 ── Explicit TrimBox ────────────────────────────────────────
    if has_explicit_trim:
        tw = trim_box.width
        th = trim_box.height
        b = 0.0
        if has_explicit_bleed:
            sides = (
                trim_box.x0 - bleed_box.x0,
                trim_box.y0 - bleed_box.y0,
                bleed_box.x1 - trim_box.x1,
                bleed_box.y1 - trim_box.y1,
            )
            b = max(min(sides), 0.0)
        elif not _rect_approx_equal(media, trim_box):
            sides = (
                trim_box.x0 - media.x0,
                trim_box.y0 - media.y0,
                media.x1 - trim_box.x1,
                media.y1 - trim_box.y1,
            )
            b = max(min(sides), 0.0)
        sn = _match_size_name(tw, th)
        margin_pt = max(
            (media.width - tw) / 2,
            (media.height - th) / 2,
            0.0,
        )
        marks_pt = max(margin_pt - b, 0.0)
        return {
            "trim_w_in": tw / 72,
            "trim_h_in": th / 72,
            "trim_w_pt": tw,
            "trim_h_pt": th,
            "bleed_pt": b,
            "bleed_mm": b / 72 * 25.4,
            "margin_pt": margin_pt,
            "marks_pt": marks_pt,
            "marks_mm": marks_pt / 72 * 25.4,
            "size_name": sn,
            "source": "explicit_trim",
            "note": f'TrimBox set in PDF — {tw / 72:.3f}"×{th / 72:.3f}"'
            + (
                f" with {b / 72 * 25.4:.2f} mm bleed"
                if b > 0.5
                else ", no bleed content"
            ),
        }

    # 2 ── MediaBox exactly matches a standard size ────────────────
    for sn, (sw, sh) in STANDARD_SIZES_PT.items():
        if (
            abs(media.width - sw) < INFER_TOL_PT
            and abs(media.height - sh) < INFER_TOL_PT
            and media.width >= sw - 0.5  # canvas must not be smaller than standard
            and media.height >= sh - 0.5
        ):
            return {
                "trim_w_in": sw / 72,
                "trim_h_in": sh / 72,
                "trim_w_pt": sw,
                "trim_h_pt": sh,
                "bleed_pt": 0,
                "bleed_mm": 0,
                "margin_pt": 0.0,
                "marks_pt": 0.0,
                "marks_mm": 0.0,
                "size_name": sn,
                "source": "standard_exact",
                "note": f"Page exactly matches {sn} — no bleed content in file",
            }
        if (
            abs(media.width - sh) < INFER_TOL_PT
            and abs(media.height - sw) < INFER_TOL_PT
            and media.width >= sh - 0.5
            and media.height >= sw - 0.5
        ):
            return {
                "trim_w_in": sh / 72,
                "trim_h_in": sw / 72,
                "trim_w_pt": sh,
                "trim_h_pt": sw,
                "bleed_pt": 0,
                "bleed_mm": 0,
                "margin_pt": 0.0,
                "marks_pt": 0.0,
                "marks_mm": 0.0,
                "size_name": sn,
                "source": "standard_exact",
                "note": f"Page exactly matches {sn} (landscape) — no bleed content in file",
            }

    # 3 ── MediaBox = standard trim + uniform bleed ────────────────
    bleed_info = infer_page_bleed(page)
    if bleed_info and bleed_info["source"] == "implied":
        trim = bleed_info["trim"]
        b = bleed_info["bleed_pt"]
        sn = bleed_info.get("size_name", "Custom")
        margin_pt = b  # margin == bleed here (no marks ring)
        return {
            "trim_w_in": trim.width / 72,
            "trim_h_in": trim.height / 72,
            "trim_w_pt": trim.width,
            "trim_h_pt": trim.height,
            "bleed_pt": b,
            "bleed_mm": b / 72 * 25.4,
            "margin_pt": margin_pt,
            "marks_pt": 0.0,
            "marks_mm": 0.0,
            "size_name": sn,
            "source": "implied_bleed",
            "note": (
                f"Dimensions match {sn} + {b / 72 * 25.4:.2f} mm bleed (inferred) — "
                "BleedBox/TrimBox not set"
            ),
        }

    # 4 ── Custom / unknown ────────────────────────────────────────
    return {
        "trim_w_in": media.width / 72,
        "trim_h_in": media.height / 72,
        "trim_w_pt": media.width,
        "trim_h_pt": media.height,
        "bleed_pt": 0,
        "bleed_mm": 0,
        "margin_pt": 0.0,
        "marks_pt": 0.0,
        "marks_mm": 0.0,
        "size_name": "Custom",
        "source": "custom",
        "note": f'Non-standard size ({media.width / 72:.3f}"×{media.height / 72:.3f}")',
    }


def build_confirmed_trim(
    tw_pt: float,
    th_pt: float,
    bleed_pt: float,
    media_w_pt: float,
    media_h_pt: float,
) -> dict:
    """
    Build a detected_trim dict from user-confirmed trim/bleed values.
    Used by the start-checks endpoint after the user selects a size in the modal.
    """
    sn = _match_size_name(tw_pt, th_pt)
    bleed_mm = bleed_pt / 72 * 25.4
    margin_pt = max((media_w_pt - tw_pt) / 2, (media_h_pt - th_pt) / 2, 0.0)
    marks_pt = max(margin_pt - bleed_pt, 0.0)
    return {
        "trim_w_in": round(tw_pt / 72, 4),
        "trim_h_in": round(th_pt / 72, 4),
        "trim_w_pt": tw_pt,
        "trim_h_pt": th_pt,
        "bleed_pt": bleed_pt,
        "bleed_mm": round(bleed_mm, 3),
        "margin_pt": round(margin_pt, 2),
        "marks_pt": round(marks_pt, 2),
        "marks_mm": round(marks_pt / 72 * 25.4, 3),
        "size_name": sn,
        "source": "custom",
        "note": f'Manually selected {sn} ({tw_pt / 72:.3f}"×{th_pt / 72:.3f}")'
        + (f" with {bleed_mm:.2f} mm bleed" if bleed_pt > 0.5 else ", no bleed"),
    }


def quick_has_rgb(doc: fitz.Document) -> bool:
    """True if the document contains any DeviceRGB colorspace references."""
    for xref in range(1, doc.xref_length()):
        try:
            if "/DeviceRGB" in doc.xref_object(xref, compressed=False):
                return True
        except Exception:
            pass
    return False


def quick_has_js(doc: fitz.Document) -> bool:
    """True if the document contains any JavaScript."""
    for xref in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(xref, compressed=False)
            if "/JavaScript" in obj or "/JS " in obj or "/JS\n" in obj:
                return True
        except Exception:
            pass
    return False


def quick_has_forms(doc: fitz.Document) -> bool:
    """True if the document has interactive form fields."""
    try:
        for page in doc:
            if list(page.widgets()):
                return True
    except Exception:
        pass
    return False


def quick_has_attachments(doc: fitz.Document) -> bool:
    """True if the document has embedded file attachments."""
    try:
        return bool(doc.embfile_count())
    except Exception:
        return False


def quick_has_rotation(doc: fitz.Document) -> bool:
    """True if any page has a non-zero /Rotate value."""
    try:
        for page in doc:
            if page.rotation not in (0, 360):
                return True
    except Exception:
        pass
    return False


def quick_has_transparency(doc: fitz.Document) -> bool:
    """Fast scan for any transparency (opacity / soft mask / non-Normal blend mode)."""
    import re as _re

    for xref in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(xref, compressed=False)
        except Exception:
            continue
        if "/SMask" in obj or "/BM /" in obj:
            return True
        if _re.search(r"/ca\s+(?!1(?:\.0+)?\s)[0-9]", obj):
            return True
        if _re.search(r"/CA\s+(?!1(?:\.0+)?\s)[0-9]", obj):
            return True
    return False


# ── PDF mutation ───────────────────────────────────────────────────────────


def compute_boxes(
    media: fitz.Rect,
    trim_w_pt: float,
    trim_h_pt: float,
    bleed_pt: float,
) -> tuple[fitz.Rect, fitz.Rect, fitz.Rect]:
    """
    Given a MediaBox and desired trim/bleed, return (trim_rect, bleed_rect, crop_rect)
    using the centered-content assumption:

        margin   = (media_w - trim_w) / 2   (same formula for height)
        bleed    = min(requested_bleed, margin)  — can't exceed media edge

        TrimBox  = trim size, centered in MediaBox           (cut line)
        BleedBox = TrimBox expanded by actual_bleed          (bleed guides)
        CropBox  = TrimBox  — Illustrator artboard / viewer crop

    Illustrator uses CropBox as its artboard, so CropBox == TrimBox gives
    the correct artboard size.  BleedBox is distinct, so Illustrator will
    display the red bleed guides correctly.
    """
    margin_x = (media.width - trim_w_pt) / 2
    margin_y = (media.height - trim_h_pt) / 2

    if margin_x < 0 or margin_y < 0:
        # Trim doesn't fit — try swapping w/h to match canvas orientation
        margin_x_rot = (media.width - trim_h_pt) / 2
        margin_y_rot = (media.height - trim_w_pt) / 2
        if margin_x_rot >= 0 and margin_y_rot >= 0:
            trim_w_pt, trim_h_pt = trim_h_pt, trim_w_pt
            margin_x, margin_y = margin_x_rot, margin_y_rot
            actual_bleed = min(bleed_pt, margin_x, margin_y)
        else:
            # Trim is larger than media in all orientations — allow boxes outside media.
            # set_pdf_boxes will expand the MediaBox via _expand_and_center.
            actual_bleed = bleed_pt
    else:
        actual_bleed = min(bleed_pt, margin_x, margin_y)

    trim_rect = fitz.Rect(
        media.x0 + margin_x,
        media.y0 + margin_y,
        media.x0 + margin_x + trim_w_pt,
        media.y0 + margin_y + trim_h_pt,
    )
    bleed_rect = fitz.Rect(
        trim_rect.x0 - actual_bleed,
        trim_rect.y0 - actual_bleed,
        trim_rect.x1 + actual_bleed,
        trim_rect.y1 + actual_bleed,
    )
    # CropBox == TrimBox: Illustrator uses CropBox as the artboard,
    # so this gives the correct print size as the artboard boundary.
    return trim_rect, bleed_rect, trim_rect


def _expand_and_center(
    doc: fitz.Document,
    trim_w_pt: float,
    trim_h_pt: float,
    bleed_pt: float,
) -> fitz.Document:
    """
    Return a new Document where each page has been expanded to (trim + 2*bleed),
    with the original content centered on the new canvas.
    Used when the requested trim size is larger than the original MediaBox.
    """
    new_doc = fitz.open()
    for i in range(len(doc)):
        page = doc[i]
        old_w = page.rect.width
        old_h = page.rect.height

        # Match the same orientation-swap logic as compute_boxes
        tw, th = trim_w_pt, trim_h_pt
        mx = (old_w - tw) / 2
        my = (old_h - th) / 2
        if mx < 0 or my < 0:
            mx_r = (old_w - th) / 2
            my_r = (old_h - tw) / 2
            if mx_r >= 0 and my_r >= 0:
                tw, th = th, tw

        new_w = tw + 2 * bleed_pt
        new_h = th + 2 * bleed_pt
        offset_x = (new_w - old_w) / 2
        offset_y = (new_h - old_h) / 2

        new_page = new_doc.new_page(width=new_w, height=new_h)
        dest = fitz.Rect(offset_x, offset_y, offset_x + old_w, offset_y + old_h)
        new_page.show_pdf_page(dest, doc, i)

    return new_doc


def set_pdf_boxes(
    pdf_bytes: bytes,
    trim_w_pt: float,
    trim_h_pt: float,
    bleed_pt: float,
) -> bytes:
    """
    Set TrimBox, BleedBox, and CropBox on every page.

    Box layout (centered-content assumption):
      - TrimBox  = trim size, centered  — the cut line
      - BleedBox = trim + bleed per side — bleed guides in Illustrator/Acrobat
      - CropBox  = TrimBox              — Illustrator artboard / viewer crop

    When the selected trim is larger than the original MediaBox, the page is
    first expanded via _expand_and_center so the content fits within the new canvas.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    # Detect whether any page needs MediaBox expansion
    needs_expansion = False
    for page in doc:
        media = page.mediabox
        mx = (media.width - trim_w_pt) / 2
        my = (media.height - trim_h_pt) / 2
        if mx < 0 or my < 0:
            mx_r = (media.width - trim_h_pt) / 2
            my_r = (media.height - trim_w_pt) / 2
            if not (mx_r >= 0 and my_r >= 0):
                needs_expansion = True
                break

    if needs_expansion:
        doc = _expand_and_center(doc, trim_w_pt, trim_h_pt, bleed_pt)
        for page in doc:
            media = page.mediabox
            # Expanded page dims = trim + 2*bleed; trim sits at (bleed, bleed)
            pg_tw = round(media.width - 2 * bleed_pt, 4)
            pg_th = round(media.height - 2 * bleed_pt, 4)
            trim_rect = fitz.Rect(
                bleed_pt, bleed_pt, bleed_pt + pg_tw, bleed_pt + pg_th
            )
            bleed_rect = fitz.Rect(0, 0, media.width, media.height)
            page.set_trimbox(trim_rect)
            page.set_bleedbox(bleed_rect)
            page.parent.xref_set_key(
                page.xref,
                "CropBox",
                f"[{trim_rect.x0} {trim_rect.y0} {trim_rect.x1} {trim_rect.y1}]",
            )
    else:
        for page in doc:
            trim_rect, bleed_rect, crop_rect = compute_boxes(
                page.mediabox, trim_w_pt, trim_h_pt, bleed_pt
            )
            page.set_trimbox(trim_rect)
            page.set_bleedbox(bleed_rect)
            # Write CropBox directly into the page dictionary to avoid PyMuPDF's
            # coordinate-system side-effects from the high-level set_cropbox() call.
            page.parent.xref_set_key(
                page.xref,
                "CropBox",
                f"[{crop_rect.x0} {crop_rect.y0} {crop_rect.x1} {crop_rect.y1}]",
            )

    buf = io.BytesIO()
    doc.save(buf, garbage=4, deflate=True)
    buf.seek(0)
    return buf.read()


def convert_to_cmyk_gs(pdf_bytes: bytes) -> tuple[bytes, str]:
    """
    Convert PDF to CMYK using Ghostscript.

    Returns (result_bytes, error_message).
    On success error_message is "".
    On failure result_bytes is the original unchanged bytes.
    """
    if not GS_AVAILABLE:
        return (
            pdf_bytes,
            "Ghostscript not found on PATH — install it to enable CMYK conversion",
        )

    in_fd, in_path = tempfile.mkstemp(suffix=".pdf")
    out_fd, out_path = tempfile.mkstemp(suffix=".pdf")
    try:
        os.write(in_fd, pdf_bytes)
        os.close(in_fd)
        os.close(out_fd)

        result = subprocess.run(
            [
                GS_BINARY,
                "-dBATCH",
                "-dNOPAUSE",
                "-dSAFER",
                "-q",
                "-sDEVICE=pdfwrite",
                "-dCompatibilityLevel=1.4",
                "-sColorConversionStrategy=CMYK",
                "-dProcessColorModel=/DeviceCMYK",
                "-dOverrideICC=true",
                f"-sOutputFile={out_path}",
                in_path,
            ],
            capture_output=True,
            timeout=120,
        )

        if result.returncode != 0:
            err = result.stderr.decode(errors="replace")[:400]
            return pdf_bytes, f"Ghostscript error: {err}"

        with open(out_path, "rb") as f:
            return f.read(), ""

    except subprocess.TimeoutExpired:
        return pdf_bytes, "Ghostscript timed out after 120 s"
    except Exception as exc:
        return pdf_bytes, str(exc)
    finally:
        try:
            os.unlink(in_path)
        except OSError:
            pass
        try:
            os.unlink(out_path)
        except OSError:
            pass


def remove_javascript(pdf_bytes: bytes) -> tuple[bytes, str]:
    """Remove all JavaScript from the PDF using PyMuPDF scrub."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        doc.scrub(
            javascript=True,
            attached_files=False,
            embedded_files=False,
            hidden_text=False,
            metadata=False,
            redact_images=0,
            reset_fields=False,
            reset_responses=False,
            sanitize_links=False,
            xml_metadata=False,
        )
        out = doc.tobytes(garbage=3, deflate=True)
        doc.close()
        return out, ""
    except Exception as exc:
        return pdf_bytes, str(exc)


def remove_attachments(pdf_bytes: bytes) -> tuple[bytes, str]:
    """Remove all embedded file attachments from the PDF."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        names = list(doc.embfile_names())
        if not names:
            doc.close()
            return pdf_bytes, ""
        for name in names:
            try:
                doc.embfile_del(name)
            except Exception:
                pass
        out = doc.tobytes(garbage=3, deflate=True)
        doc.close()
        return out, ""
    except Exception as exc:
        return pdf_bytes, str(exc)


def normalize_page_rotation(pdf_bytes: bytes) -> tuple[bytes, str]:
    """Reset all page /Rotate entries to 0."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        rotated = 0
        for page in doc:
            if page.rotation not in (0, 360):
                page.set_rotation(0)
                rotated += 1
        if rotated == 0:
            doc.close()
            return pdf_bytes, ""
        out = doc.tobytes(garbage=3, deflate=True)
        doc.close()
        return out, ""
    except Exception as exc:
        return pdf_bytes, str(exc)


def _gs_pdf_write(
    pdf_bytes: bytes,
    extra_args: list[str],
    timeout: int = 120,
) -> tuple[bytes, str]:
    """Shared Ghostscript pdfwrite helper. Returns (bytes, error_str)."""
    if not GS_AVAILABLE:
        return pdf_bytes, "Ghostscript not found on PATH"

    in_fd, in_path = tempfile.mkstemp(suffix=".pdf")
    out_fd, out_path = tempfile.mkstemp(suffix=".pdf")
    try:
        os.write(in_fd, pdf_bytes)
        os.close(in_fd)
        os.close(out_fd)

        cmd = (
            [
                GS_BINARY,
                "-dBATCH",
                "-dNOPAUSE",
                "-dSAFER",
                "-q",
                "-sDEVICE=pdfwrite",
                f"-sOutputFile={out_path}",
            ]
            + extra_args
            + [in_path]
        )

        result = subprocess.run(cmd, capture_output=True, timeout=timeout)

        if result.returncode != 0:
            err = result.stderr.decode(errors="replace")[:400]
            return pdf_bytes, f"Ghostscript error: {err}"

        with open(out_path, "rb") as f:
            return f.read(), ""

    except subprocess.TimeoutExpired:
        return pdf_bytes, f"Ghostscript timed out after {timeout} s"
    except Exception as exc:
        return pdf_bytes, str(exc)
    finally:
        for p in (in_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def flatten_transparency_gs(pdf_bytes: bytes) -> tuple[bytes, str]:
    """Flatten transparency by rendering to PDF 1.3 (Ghostscript)."""
    return _gs_pdf_write(
        pdf_bytes,
        ["-dCompatibilityLevel=1.3"],
    )


def flatten_forms_gs(pdf_bytes: bytes) -> tuple[bytes, str]:
    """Flatten interactive form fields into static content (Ghostscript)."""
    return _gs_pdf_write(
        pdf_bytes,
        [
            "-dCompatibilityLevel=1.4",
            "-dPrinted=true",
            "-dNOCACHE",
        ],
    )


def downgrade_pdf_version_gs(pdf_bytes: bytes) -> tuple[bytes, str]:
    """Downgrade PDF to version 1.7 (Ghostscript)."""
    return _gs_pdf_write(
        pdf_bytes,
        ["-dCompatibilityLevel=1.7"],
    )


def build_fixed_pdf(
    pdf_bytes: bytes,
    trim_w_pt: float,
    trim_h_pt: float,
    bleed_pt: float,
    convert_cmyk: bool = False,
    remove_js: bool = False,
    flatten_forms: bool = False,
    remove_attachments_flag: bool = False,
    normalize_rotation: bool = False,
    flatten_transparency: bool = False,
    downgrade_version: bool = False,
) -> tuple[bytes, list[str]]:
    """
    Assemble a corrected PDF applying all requested fixes.

    Returns (fixed_bytes, notes) where notes is a list of human-readable
    strings describing what was done (or any warnings).
    """
    notes: list[str] = []
    current = pdf_bytes

    # --- PyMuPDF-only fixes (fast, no GS needed) ---
    if remove_js:
        current, err = remove_javascript(current)
        if err:
            notes.append(f"⚠ Remove JavaScript failed: {err}")
        else:
            notes.append("✓ JavaScript removed")

    if remove_attachments_flag:
        current, err = remove_attachments(current)
        if err:
            notes.append(f"⚠ Remove attachments failed: {err}")
        else:
            notes.append("✓ Embedded attachments removed")

    if normalize_rotation:
        current, err = normalize_page_rotation(current)
        if err:
            notes.append(f"⚠ Normalize rotation failed: {err}")
        else:
            notes.append("✓ Page rotation normalized to 0°")

    # --- Ghostscript fixes ---
    if flatten_transparency:
        current, err = flatten_transparency_gs(current)
        if err:
            notes.append(f"⚠ Flatten transparency skipped: {err}")
        else:
            notes.append(
                "✓ Transparency flattened (PDF 1.3 compatible) via Ghostscript"
            )

    if flatten_forms:
        current, err = flatten_forms_gs(current)
        if err:
            notes.append(f"⚠ Flatten forms skipped: {err}")
        else:
            notes.append("✓ Interactive form fields flattened via Ghostscript")

    if downgrade_version:
        current, err = downgrade_pdf_version_gs(current)
        if err:
            notes.append(f"⚠ Downgrade PDF version skipped: {err}")
        else:
            notes.append("✓ PDF downgraded to version 1.7 via Ghostscript")

    # --- CMYK color conversion (GS, after structural fixes) ---
    if convert_cmyk:
        current, err = convert_to_cmyk_gs(current)
        if err:
            notes.append(f"⚠ CMYK conversion skipped: {err}")
        else:
            notes.append("✓ Converted to CMYK color space via Ghostscript")

    # --- Geometry fixes (always last so boxes survive GS re-write) ---
    current = set_pdf_boxes(current, trim_w_pt, trim_h_pt, bleed_pt)

    tw_in = trim_w_pt / 72
    th_in = trim_h_pt / 72
    notes.append(f'✓ TrimBox set to {tw_in:.3f}"×{th_in:.3f}"')

    if bleed_pt > 0.5:
        b_mm = bleed_pt / 72 * 25.4
        notes.append(
            f"✓ BleedBox set to media edge — "
            f"{b_mm:.2f} mm bleed area labeled "
            f"(content must already extend to this edge)"
        )
    else:
        notes.append("✓ BleedBox set to media edge (no bleed area)")

    return current, notes
