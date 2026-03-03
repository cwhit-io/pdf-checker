import re
import fitz  # PyMuPDF
from typing import List
from .models import CheckItem

MIN_FONT_SIZE_PT = 6.0  # below this is illegible under any normal conditions
WARN_FONT_SIZE_PT = 8.0  # below this is risky for small stock / fine detail


def check_fonts(doc: fitz.Document) -> List[CheckItem]:
    checks: List[CheckItem] = []

    # name -> {embedded, subset, ftype}
    all_fonts: dict[str, dict] = {}
    unembedded: set[str] = set()
    type3_fonts: set[str] = set()

    # Collect per-span font sizes
    small_error: list[str] = []  # < MIN_FONT_SIZE_PT
    small_warn: list[str] = []  # < WARN_FONT_SIZE_PT

    for page_num, page in enumerate(doc, 1):
        for font in page.get_fonts(full=True):
            _xref, ext, ftype, basefont, name, *_ = font
            display_name = name or basefont or "Unknown"
            embedded = bool(ext)
            is_type3 = ftype == "Type3"
            if display_name not in all_fonts:
                all_fonts[display_name] = {
                    "embedded": embedded,
                    "subset": "+" in display_name,
                    "type": ftype,
                }
            if not embedded:
                unembedded.add(display_name)
            if is_type3:
                type3_fonts.add(display_name)

        # Font size scan — walk the raw text spans
        for block in page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)[
            "blocks"
        ]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size", 0)
                    text_sample = span.get("text", "").strip()[:30]
                    if not text_sample or size <= 0:
                        continue
                    label = f'p{page_num}: "{text_sample}" ({size:.1f} pt)'
                    if size < MIN_FONT_SIZE_PT:
                        small_error.append(label)
                    elif size < WARN_FONT_SIZE_PT:
                        small_warn.append(label)

    total = len(all_fonts)

    # ── Font embedding ─────────────────────────────────────────────────────
    checks.append(
        CheckItem(
            name="All Fonts Embedded",
            passed=len(unembedded) == 0,
            detail=(
                f"All {total} font(s) included in the file"
                if not unembedded
                else f"Fonts not included in the PDF (may not print correctly): {', '.join(sorted(unembedded))}"
            ),
            severity="error",
        )
    )

    # ── Type 3 fonts ────────────────────────────────────────────────────────
    if type3_fonts:
        checks.append(
            CheckItem(
                name="Type 3 Fonts",
                passed=False,
                detail=f"Old-format font(s) found — may not print correctly: {', '.join(sorted(type3_fonts))}",
                severity="warning",
            )
        )

    # ── Minimum font size ────────────────────────────────────────────────────
    if small_error:
        checks.append(
            CheckItem(
                name=f"Font Too Small (under {MIN_FONT_SIZE_PT:.0f} pt)",
                passed=False,
                detail=f"{len(small_error)} instance(s) smaller than {MIN_FONT_SIZE_PT} pt — likely too small to read when printed: "
                + "; ".join(small_error[:4])
                + (" …" if len(small_error) > 4 else ""),
                severity="error",
            )
        )
    if small_warn:
        checks.append(
            CheckItem(
                name=f"Font May Be Too Small (under {WARN_FONT_SIZE_PT:.0f} pt)",
                passed=False,
                detail=f"{len(small_warn)} instance(s) between {MIN_FONT_SIZE_PT}–{WARN_FONT_SIZE_PT} pt — may be hard to read on small stock: "
                + "; ".join(small_warn[:4])
                + (" …" if len(small_warn) > 4 else ""),
                severity="warning",
            )
        )
    if not small_error and not small_warn:
        checks.append(
            CheckItem(
                name="Font Sizes",
                passed=True,
                detail=f"All text ≥ {WARN_FONT_SIZE_PT} pt",
                severity="info",
            )
        )

    # ── Font inventory ──────────────────────────────────────────────────────
    if total:
        clean_names = sorted({re.sub(r"^[A-Z]{6}\+", "", n) for n in all_fonts})
        truncated = clean_names[:12]
        suffix = " …" if len(clean_names) > 12 else ""
        checks.append(
            CheckItem(
                name=f"Font Inventory ({total})",
                passed=True,
                detail=", ".join(truncated) + suffix,
                severity="info",
            )
        )

    return checks
