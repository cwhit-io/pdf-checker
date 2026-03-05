import io
import math

import fitz  # PyMuPDF
from fastapi import FastAPI, File, Form, UploadFile, Request, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, Response
from PIL import Image, ImageDraw

from .utils import load_pdf_from_bytes
from .jobs import (
    GROUPS,
    GROUP_LABELS,
    GROUP_ICONS,
    create_job,
    get_job,
    store_results,
    update_job_trim,
)
from .checks.geometry import get_page_infos, get_page_boxes, infer_page_bleed
from .checks.bleed_trim import check_bleed_trim
from .checks.fonts import check_fonts
from .checks.color import check_color
from .checks.images import check_images
from .checks.safe_zone import check_safe_zone
from .checks.transparency import check_transparency
from .checks.overprint import check_overprint
from .checks.ink_density import check_ink_density
from .checks.security import check_security
from .checks.metadata import check_metadata
from .fix_pdf import (
    detect_print_geometry,
    quick_has_rgb,
    build_fixed_pdf,
    build_confirmed_trim,
    compute_boxes,
    FORM_SIZES,
    BLEED_PT,
    GS_AVAILABLE,
)

app = FastAPI(title="PDF Print Readiness Checker", version="1.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ── Jinja2 filters ─────────────────────────────────────────────────────────


def _badge_class(check) -> str:
    if check.passed:
        return "badge-pass"
    return {
        "error": "badge-fail",
        "warning": "badge-warning",
        "info": "badge-info",
    }.get(check.severity, "badge-fail")


def _badge_label(check) -> str:
    if check.passed:
        return "Pass"
    return {"error": "Fail", "warning": "Warning", "info": "Info"}.get(
        check.severity, "Fail"
    )


templates.env.filters["badge_class"] = _badge_class
templates.env.filters["badge_label"] = _badge_label


# ── Pages ──────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ── Upload ─────────────────────────────────────────────────────────────────


@app.post("/check/upload", response_class=HTMLResponse)
async def upload_pdf(request: Request, file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        return _error(request, "Only PDF files are accepted.", 400)

    contents = await file.read()
    if not contents:
        return _error(request, "Uploaded file is empty.", 400)

    try:
        doc = load_pdf_from_bytes(contents)
    except Exception as exc:
        return _error(request, f"Could not parse PDF: {exc}", 422)

    pages = get_page_infos(doc)
    detected_trim = detect_print_geometry(doc)
    job_id = create_job(file.filename, contents, doc.page_count, pages, detected_trim)

    confirmed_trim = build_confirmed_trim(
        detected_trim["trim_w_pt"],
        detected_trim["trim_h_pt"],
        BLEED_PT,
        pages[0].width_pt,
        pages[0].height_pt,
    )
    update_job_trim(job_id, confirmed_trim)

    page_boxes = get_page_boxes(doc)
    has_rgb = quick_has_rgb(doc)

    return templates.TemplateResponse(
        "partials/results_container.html",
        {
            "request": request,
            "job_id": job_id,
            "filename": file.filename,
            "page_count": doc.page_count,
            "pages": pages,
            "page_boxes": page_boxes,
            "groups": GROUPS,
            "group_labels": GROUP_LABELS,
            "group_icons": GROUP_ICONS,
            "detected_trim": confirmed_trim,
            "has_rgb": has_rgb,
            "form_sizes": FORM_SIZES,
            "gs_available": GS_AVAILABLE,
        },
    )


# ── Per-group check endpoints ──────────────────────────────────────────────


@app.get("/check/{job_id}/bleed_trim", response_class=HTMLResponse)
async def run_bleed_trim(
    request: Request,
    job_id: str,
    preset_trim: str = Query(default=""),
):
    job = _require_job(job_id)
    doc = load_pdf_from_bytes(job.pdf_bytes)
    checks = check_bleed_trim(doc, preset_trim=preset_trim)
    store_results(job_id, "bleed_trim", checks)
    return _cards(request, checks)


@app.get("/check/{job_id}/fonts", response_class=HTMLResponse)
async def run_fonts(request: Request, job_id: str):
    job = _require_job(job_id)
    doc = load_pdf_from_bytes(job.pdf_bytes)
    checks = check_fonts(doc)
    store_results(job_id, "fonts", checks)
    return _cards(request, checks)


@app.get("/check/{job_id}/color", response_class=HTMLResponse)
async def run_color(request: Request, job_id: str):
    job = _require_job(job_id)
    doc = load_pdf_from_bytes(job.pdf_bytes)
    checks = check_color(doc)
    store_results(job_id, "color", checks)
    return _cards(request, checks)


@app.get("/check/{job_id}/images", response_class=HTMLResponse)
async def run_images(request: Request, job_id: str):
    job = _require_job(job_id)
    doc = load_pdf_from_bytes(job.pdf_bytes)
    checks = check_images(doc)
    store_results(job_id, "images", checks)
    return _cards(request, checks)


@app.get("/check/{job_id}/safe_zone", response_class=HTMLResponse)
async def run_safe_zone(request: Request, job_id: str):
    job = _require_job(job_id)
    doc = load_pdf_from_bytes(job.pdf_bytes)
    checks = check_safe_zone(doc)
    store_results(job_id, "safe_zone", checks)
    return _cards(request, checks)


@app.get("/check/{job_id}/transparency", response_class=HTMLResponse)
async def run_transparency(request: Request, job_id: str):
    job = _require_job(job_id)
    doc = load_pdf_from_bytes(job.pdf_bytes)
    checks = check_transparency(doc)
    store_results(job_id, "transparency", checks)
    return _cards(request, checks)


@app.get("/check/{job_id}/overprint", response_class=HTMLResponse)
async def run_overprint(request: Request, job_id: str):
    job = _require_job(job_id)
    doc = load_pdf_from_bytes(job.pdf_bytes)
    checks = check_overprint(doc)
    store_results(job_id, "overprint", checks)
    return _cards(request, checks)


@app.get("/check/{job_id}/ink_density", response_class=HTMLResponse)
async def run_ink_density(request: Request, job_id: str):
    job = _require_job(job_id)
    doc = load_pdf_from_bytes(job.pdf_bytes)
    checks = check_ink_density(doc)
    store_results(job_id, "ink_density", checks)
    return _cards(request, checks)


@app.get("/check/{job_id}/security", response_class=HTMLResponse)
async def run_security(request: Request, job_id: str):
    job = _require_job(job_id)
    doc = load_pdf_from_bytes(job.pdf_bytes)
    checks = check_security(doc, len(job.pdf_bytes))
    store_results(job_id, "security", checks)
    return _cards(request, checks)


@app.get("/check/{job_id}/metadata", response_class=HTMLResponse)
async def run_metadata(request: Request, job_id: str):
    job = _require_job(job_id)
    doc = load_pdf_from_bytes(job.pdf_bytes)
    checks = check_metadata(doc)
    store_results(job_id, "metadata", checks)
    return _cards(request, checks)


# ── Download fixed PDF ────────────────────────────────────────────────────


@app.post("/check/{job_id}/download-fixed")
async def download_fixed_pdf(
    job_id: str,
    preset_trim: str = Form(default="0,0"),
    trim_w_in: float = Form(default=0.0),
    trim_h_in: float = Form(default=0.0),
    apply_trim_bleed: str = Form(default=""),
    convert_cmyk: str = Form(default=""),
):
    job = _require_job(job_id)
    use_trim_fix = apply_trim_bleed == "1"

    if use_trim_fix:
        bleed_pt = BLEED_PT
    else:
        bleed_pt = float(job.detected_trim.get("bleed_pt", 0.0) or 0.0)

    if use_trim_fix:
        # Resolve requested trim dimensions
        try:
            pw_str, ph_str = preset_trim.split(",", 1)
            pw, ph = float(pw_str), float(ph_str)
        except Exception:
            pw, ph = 0.0, 0.0

        if pw > 0 and ph > 0:
            tw_pt = pw * 72
            th_pt = ph * 72
        elif trim_w_in > 0 and trim_h_in > 0:
            tw_pt = trim_w_in * 72
            th_pt = trim_h_in * 72
        else:
            tw_pt = job.detected_trim.get("trim_w_pt", job.pages[0].width_pt)
            th_pt = job.detected_trim.get("trim_h_pt", job.pages[0].height_pt)
    else:
        # Preserve detected/native trim when fix toggle is off
        tw_pt = job.detected_trim.get("trim_w_pt", job.pages[0].width_pt)
        th_pt = job.detected_trim.get("trim_h_pt", job.pages[0].height_pt)

    do_cmyk = convert_cmyk == "1"

    fixed_bytes, _notes = build_fixed_pdf(
        job.pdf_bytes, tw_pt, th_pt, bleed_pt, do_cmyk
    )

    stem = job.filename.rsplit(".", 1)[0]
    out_name = f"{stem}_fixed.pdf"
    return Response(
        content=fixed_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )


# ── Overall status (polled by badge) ──────────────────────────────────────


# ── Page preview with annotated overlays ─────────────────────────────────


@app.get("/check/{job_id}/preview/{page_num}")
async def get_page_preview(
    job_id: str,
    page_num: int,
    scale: float = Query(default=0.35, ge=0.1, le=6.0),
    ov_trim_w_pt: float = Query(default=0.0),
    ov_trim_h_pt: float = Query(default=0.0),
    ov_bleed_pt: float = Query(default=-1.0),
    overlay: int = Query(default=1),
):
    """Render a PDF page as JPEG with bleed/trim/safe-zone overlays.

    Optional ov_* params override the auto-detected geometry so the fix
    panel can show a live preview of the user’s chosen trim/bleed values.
    ov_bleed_pt=-1 means “use auto-detected value”.
    """
    job = _require_job(job_id)
    doc = load_pdf_from_bytes(job.pdf_bytes)

    if page_num < 1 or page_num > doc.page_count:
        raise HTTPException(status_code=404, detail="Page not found")

    page = doc[page_num - 1]
    mat = fitz.Matrix(scale, scale)
    # PyMuPDF renders only the CropBox area by default.  When the CropBox is
    # inset from the MediaBox (common in Illustrator/Canva exports where
    # CropBox = TrimBox), the rendered image starts at the CropBox origin, but
    # all overlay coordinate math is in MediaBox space — causing every overlay
    # line to be shifted by the CropBox inset offset.
    # Fix: write CropBox = MediaBox directly into the page dict (bypassing
    # PyMuPDF's strict-containment validation in set_cropbox) so the pixmap
    # covers the entire canvas and pixel (0,0) aligns with MediaBox (0,0).
    media = page.mediabox
    doc.xref_set_key(
        page.xref,
        "CropBox",
        f"[{media.x0} {media.y0} {media.x1} {media.y1}]",
    )
    pix = page.get_pixmap(matrix=mat, alpha=False)

    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("RGBA")

    if not overlay:
        img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        buf.seek(0)
        return Response(content=buf.read(), media_type="image/jpeg")

    # ── Resolve trim & bleed rectangles ─────────────────────────────
    # If the caller supplies explicit override dimensions use compute_boxes
    # (the centered-content algorithm); otherwise fall back to infer_page_bleed
    # which reads the PDF’s own box metadata.
    is_override = ov_trim_w_pt > 0 and ov_trim_h_pt > 0
    if is_override:
        effective_bleed = ov_bleed_pt if ov_bleed_pt >= 0 else 9.0
        trim_rect, bleed_rect, _ = compute_boxes(
            media, ov_trim_w_pt, ov_trim_h_pt, effective_bleed
        )
        is_implied = False  # user-specified — show at full opacity
    else:
        bleed_info = infer_page_bleed(page)
        if bleed_info is not None:
            trim_rect = bleed_info["trim"]
            bleed_rect = bleed_info["bleed"]
            is_implied = bleed_info["source"] == "implied"
        else:
            trim_rect = None
            bleed_rect = None
            is_implied = False

    # ref rect: trim line (or full media if no trim detected)
    ref = trim_rect if trim_rect is not None else media

    # ── Expand canvas when trim+bleed extends outside the media box ──
    pad_l = pad_t = pad_r = pad_b = 0
    if bleed_rect is not None:
        pad_l = max(0, math.ceil((media.x0 - bleed_rect.x0) * scale))
        pad_t = max(0, math.ceil((media.y0 - bleed_rect.y0) * scale))
        pad_r = max(0, math.ceil((bleed_rect.x1 - media.x1) * scale))
        pad_b = max(0, math.ceil((bleed_rect.y1 - media.y1) * scale))

    if pad_l or pad_t or pad_r or pad_b:
        new_w = img.width + pad_l + pad_r
        new_h = img.height + pad_t + pad_b
        expanded = Image.new("RGBA", (new_w, new_h), (215, 215, 222, 255))
        expanded.paste(img, (pad_l, pad_t))
        img = expanded

    overlay_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay_img)

    def to_px(rect: fitz.Rect):
        return (
            (rect.x0 - media.x0) * scale + pad_l,
            (rect.y0 - media.y0) * scale + pad_t,
            (rect.x1 - media.x0) * scale + pad_l,
            (rect.y1 - media.y0) * scale + pad_t,
        )

    # Implied-bleed overlays are slightly more transparent to signal uncertainty
    lw = max(2, round(scale * 2))
    bleed_fill_a = 60 if is_implied else 90
    bleed_line_a = 170 if is_implied else 230

    # ── Bleed zone: red fill between bleed edge and trim line ────
    if bleed_rect is not None:
        bx0, by0, bx1, by1 = to_px(bleed_rect)
        rx0, ry0, rx1, ry1 = to_px(ref)
        for strip in [
            (bx0, by0, bx1, ry0),  # top
            (bx0, ry1, bx1, by1),  # bottom
            (bx0, ry0, rx0, ry1),  # left
            (rx1, ry0, bx1, ry1),  # right
        ]:
            draw.rectangle(strip, fill=(220, 40, 40, bleed_fill_a))
        draw.rectangle(
            [bx0, by0, bx1 - 1, by1 - 1],
            outline=(220, 40, 40, bleed_line_a),
            width=lw,
        )

    # ── Safe zone: amber fill between trim line and 0.25" inset ─
    safe_margin_pt = 0.25 * 72  # 18 pt
    if (ref.width > safe_margin_pt * 2) and (ref.height > safe_margin_pt * 2):
        safe_rect = fitz.Rect(
            ref.x0 + safe_margin_pt,
            ref.y0 + safe_margin_pt,
            ref.x1 - safe_margin_pt,
            ref.y1 - safe_margin_pt,
        )
        sx0, sy0, sx1, sy1 = to_px(safe_rect)
        rx0, ry0, rx1, ry1 = to_px(ref)
        for strip in [
            (rx0, ry0, rx1, sy0),  # top danger band
            (rx0, sy1, rx1, ry1),  # bottom danger band
            (rx0, sy0, sx0, sy1),  # left danger band
            (sx1, sy0, rx1, sy1),  # right danger band
        ]:
            draw.rectangle(strip, fill=(255, 180, 0, 65))
        draw.rectangle(
            [sx0, sy0, sx1 - 1, sy1 - 1],
            outline=(20, 160, 70, 240),
            width=lw,
        )

    # ── Trim / cut line: blue border ─────────────────────────────
    rx0, ry0, rx1, ry1 = to_px(ref)
    draw.rectangle(
        [rx0, ry0, rx1 - 1, ry1 - 1],
        outline=(30, 90, 210, 240),
        width=lw,
    )

    img = Image.alpha_composite(img, overlay_img).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    buf.seek(0)
    return Response(content=buf.read(), media_type="image/jpeg")


@app.get("/check/{job_id}/status", response_class=HTMLResponse)
async def check_status(request: Request, job_id: str):
    job = _require_job(job_id)
    done = job.is_complete()
    return templates.TemplateResponse(
        "partials/overall_badge.html",
        {
            "request": request,
            "job_id": job_id,
            "done": done,
            "passed": job.overall_pass() if done else False,
            "quality_score": job.quality_score if done else None,
        },
    )


# ── Helpers ────────────────────────────────────────────────────────────────


def _require_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


def _cards(request: Request, checks):
    return templates.TemplateResponse(
        "partials/check_cards.html", {"request": request, "checks": checks}
    )


def _error(request: Request, message: str, status: int):
    return templates.TemplateResponse(
        "partials/error.html",
        {"request": request, "message": message},
        status_code=status,
    )
